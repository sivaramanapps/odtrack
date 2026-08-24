from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sanctioned_limit: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    interest_rate: Decimal = Field(default=Decimal("0.1095"), ge=0, max_digits=8, decimal_places=6)
    penal_rate: Decimal = Field(default=Decimal("0.08"), ge=0, max_digits=8, decimal_places=6)


class AccountResponse(AccountCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class TransactionCreate(BaseModel):
    effective_date: date
    type: str = Field(pattern=r"^(withdrawal|principal_repayment|interest_payment|penalty_payment|bank_penalty|incidental_charge|debit|credit)$")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class TransactionResponse(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID


class SummaryResponse(BaseModel):
    principal: Decimal
    accrued_interest: Decimal
    penalty_balance: Decimal
    overrun: Decimal
    net_cost: Decimal
    total_outstanding: Decimal
    total_interest_accrued: Decimal
    total_penalties_charged: Decimal
    incidental_charges: Decimal
    as_of: date


class RateHistoryCreate(BaseModel):
    effective_date: date
    interest_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    penal_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class RateHistoryResponse(RateHistoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
