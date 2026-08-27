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


def test_repayment_cannot_create_negative_principal() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 1), "withdrawal", Decimal("100.00")),
            LedgerEvent(date(2026, 1, 2), "principal_repayment", Decimal("150.00")),
        ],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    assert result["principal"] == Decimal("0.00")
    assert result["overrun"] == Decimal("0.00")


def test_future_transaction_is_not_included_in_current_summary() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2099, 1, 1), "withdrawal", Decimal("100.00")),
        ],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00"))],
        end_date=date(2026, 1, 1),
    )

    assert result["principal"] == Decimal("0.00")
    assert result["as_of"] == date(2026, 1, 1)


def test_pre_drawdown_repayment_becomes_credit_for_later_withdrawal() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 1), "principal_repayment", Decimal("1.00")),
            LedgerEvent(date(2026, 1, 2), "withdrawal", Decimal("100.00")),
        ],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    assert result["principal"] == Decimal("99.00")
    assert result["accrued_interest"] == Decimal("0.03")
    assert result["credit_balance"] == Decimal("0.00")


def test_pre_drawdown_repayment_is_reported_as_credit() -> None:
    result = calculate_ledger(
        transactions=[LedgerEvent(date(2026, 1, 1), "principal_repayment", Decimal("1.00"))],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("8.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert result["principal"] == Decimal("0.00")
    assert result["credit_balance"] == Decimal("1.00")


def test_bank_charge_is_separate_from_penal_interest_total() -> None:
    result = calculate_ledger(
        transactions=[LedgerEvent(date(2026, 1, 1), "bank_penalty", Decimal("25.00"))],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("0.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert result["bank_charges"] == Decimal("0.00")
    assert result["total_penalties_charged"] == Decimal("25.00")
    assert result["principal"] == Decimal("0.00")
    assert result["penalty_balance"] == Decimal("25.00")
    assert result["bank_charge_balance"] == Decimal("0.00")


def test_incidental_charge_is_reported_as_bank_charge() -> None:
    result = calculate_ledger(
        transactions=[LedgerEvent(date(2026, 1, 1), "incidental_charge", Decimal("25.00"))],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("10.95"), Decimal("0.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
    )

    assert result["bank_charges"] == Decimal("25.00")
    assert result["incidental_charges"] == Decimal("25.00")
    assert result["penalty_balance"] == Decimal("0.00")


def test_penalty_can_be_waived() -> None:
    result = calculate_ledger(
        transactions=[
            LedgerEvent(date(2026, 1, 1), "bank_penalty", Decimal("25.00")),
            LedgerEvent(date(2026, 1, 2), "penalty_waiver", Decimal("25.00")),
        ],
        sanctioned_limit=Decimal("1000.00"),
        rate_history=[RatePoint(date(2026, 1, 1), Decimal("0.00"), Decimal("0.00"))],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    assert result["penalty_balance"] == Decimal("0.00")
    assert result["total_penalties_charged"] == Decimal("0.00")
