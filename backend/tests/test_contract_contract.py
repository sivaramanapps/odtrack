from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.models import Account
from backend.schemas import AccountCreate, TransactionCreate


def test_account_decimal_contract_round_trips_exactly() -> None:
    account = AccountCreate.model_validate(
        {
            "label": "Primary",
            "sanctioned_limit": "1250.50",
            "interest_rate": "0.1095",
            "penal_rate": "0.08",
        }
    )

    assert account.sanctioned_limit == Decimal("1250.50")
    assert account.interest_rate == Decimal("0.1095")
    assert account.penal_rate == Decimal("0.08")


@pytest.mark.parametrize(
    ("percent_value", "expected_decimal"),
    [
        ("10.95", "0.1095"),
        ("8.00", "0.08"),
        ("0.01", "0.0001"),
    ],
)
def test_percent_values_convert_to_exact_decimal_fraction(percent_value: str, expected_decimal: str) -> None:
    account = AccountCreate.model_validate(
        {
            "label": "Primary",
            "sanctioned_limit": "1250.50",
            "interest_rate": expected_decimal,
            "penal_rate": expected_decimal,
        }
    )

    assert account.interest_rate == Decimal(expected_decimal)
    assert account.penal_rate == Decimal(expected_decimal)


def test_account_precision_is_rejected_when_too_many_decimal_places() -> None:
    with pytest.raises(ValidationError):
        AccountCreate.model_validate(
            {
                "label": "Primary",
                "sanctioned_limit": "1250.50",
                "interest_rate": "0.1095001",
                "penal_rate": "0.08",
            }
        )


def test_transaction_amount_accepts_cents() -> None:
    tx = TransactionCreate.model_validate(
        {
            "effective_date": "2026-01-15",
            "type": "withdrawal",
            "amount": "250.75",
        }
    )

    assert tx.amount == Decimal("250.75")


def test_created_at_default_is_timezone_aware() -> None:
    default = Account.__table__.c.created_at.default
    assert default is not None
    assert callable(default.arg)

    created_at = default.arg(None)

    assert isinstance(created_at, datetime)
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
