from datetime import date
from decimal import Decimal

from backend.engine import LedgerEvent, RatePoint, calculate_ledger


def test_rate_change_applies_from_effective_date() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 1), "withdrawal", Decimal("10000.00")),
        ],
        sanctioned_limit=Decimal("20000.00"),
        rate_history=[
            RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00")),
            RatePoint(date(2026, 1, 3), Decimal("12.50"), Decimal("9.00")),
        ],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    expected_interest = (
        Decimal("10000.00") * Decimal("10.95") / Decimal("100") / Decimal("365")
        + Decimal("10000.00") * Decimal("10.95") / Decimal("100") / Decimal("365")
        + Decimal("10000.00") * Decimal("12.50") / Decimal("100") / Decimal("365")
    )

    assert result["total_interest_accrued"] == expected_interest.quantize(Decimal("0.01"))


def test_penal_rate_changes_independently() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 1), "withdrawal", Decimal("12000.00")),
        ],
        sanctioned_limit=Decimal("10000.00"),
        rate_history=[
            RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00")),
            RatePoint(date(2026, 1, 3), Decimal("10.95"), Decimal("12.00")),
        ],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    expected_penalty = (
        Decimal("2000.00") * Decimal("8.00") / Decimal("100") / Decimal("365")
        + Decimal("2000.00") * Decimal("8.00") / Decimal("100") / Decimal("365")
        + Decimal("2000.00") * Decimal("12.00") / Decimal("100") / Decimal("365")
    )

    assert result["total_penalties_charged"] == expected_penalty.quantize(Decimal("0.01"))


def test_rate_history_before_start_date_uses_latest_baseline() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 10), "withdrawal", Decimal("10000.00")),
        ],
        sanctioned_limit=Decimal("20000.00"),
        rate_history=[
            RatePoint(date(2026, 1, 1), Decimal("10.00"), Decimal("8.00")),
            RatePoint(date(2026, 1, 5), Decimal("12.00"), Decimal("8.00")),
        ],
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 10),
    )

    expected = (
        Decimal("10000.00")
        * Decimal("12.00")
        / Decimal("100")
        / Decimal("365")
    ).quantize(Decimal("0.01"))

    assert result["total_interest_accrued"] == expected
