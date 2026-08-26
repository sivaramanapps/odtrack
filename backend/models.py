import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from backend.database import Base
except ModuleNotFoundError:
    from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    accounts: Mapped[list["Account"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("sanctioned_limit >= 0", name="ck_account_limit_nonnegative"),
        CheckConstraint("interest_rate >= 0", name="ck_account_interest_rate_nonnegative"),
        CheckConstraint("penal_rate >= 0", name="ck_account_penal_rate_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        )
    sanctioned_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.109500"), nullable=False)
    penal_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.080000"), nullable=False)
    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    rate_history: Mapped[list["AccountRateHistory"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        CheckConstraint("type IN ('withdrawal', 'principal_repayment', 'interest_payment', 'penalty_payment', 'bank_penalty', 'incidental_charge', 'debit', 'credit')", name="ck_transaction_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    account: Mapped[Account] = relationship(back_populates="transactions")


class AccountRateHistory(Base):
    __tablename__ = "account_rate_history"
    __table_args__ = (UniqueConstraint("account_id", "effective_date", name="uq_account_rate_effective_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    penal_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    account: Mapped[Account] = relationship(back_populates="rate_history")
