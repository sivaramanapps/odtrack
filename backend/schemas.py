from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")

    @field_validator("pin", mode="before")
    @classmethod
    def validate_pin_digits(cls, value: str) -> str:
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("Use numbers only for password")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    view_only: bool = False
    is_admin: bool = False


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sanctioned_limit: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    interest_rate: Decimal = Field(default=Decimal("0.1095"), ge=0, le=1, max_digits=8, decimal_places=6)
    penal_rate: Decimal = Field(default=Decimal("0.08"), ge=0, le=1, max_digits=8, decimal_places=6)


class AccountResponse(AccountCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    view_only: bool = False


class PasswordChange(BaseModel):
    current_pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")
    new_pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class ViewerCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class ViewerPassword(BaseModel):
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class ViewerResponse(BaseModel):
    username: str
    account_id: UUID | None = None


class ViewerAccountsUpdate(BaseModel):
    account_ids: list[UUID]


class AdminSettings(BaseModel):
    registration_enabled: bool


class AdminUserResponse(BaseModel):
    id: UUID
    username: str
    is_admin: bool
    is_approved: bool
    is_view_only: bool
    account_limit: int | None
    account_count: int


class UserPolicyUpdate(BaseModel):
    is_approved: bool | None = None
    account_limit: int | None = Field(default=None, ge=0)


class AdminPasswordReset(BaseModel):
    new_pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class TransactionCreate(BaseModel):
    effective_date: date
    type: str = Field(pattern=r"^(withdrawal|principal_repayment|interest_payment|penalty_payment|bank_penalty|penalty_waiver|incidental_charge|debit|credit)$")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class TransactionResponse(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID


class SummaryResponse(BaseModel):
    principal: Decimal
    accrued_interest: Decimal
    penalty_balance: Decimal
    bank_charge_balance: Decimal
    credit_balance: Decimal
    overrun: Decimal
    net_cost: Decimal
    total_outstanding: Decimal
    total_interest_accrued: Decimal
    total_penalties_charged: Decimal
    bank_charges: Decimal
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
