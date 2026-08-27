from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, NamedTuple

MONEY = Decimal("0.01")
PERCENT = Decimal("100")
DAYS_PER_YEAR = Decimal("365")


class LedgerEvent(NamedTuple):
    effective_date: date
    type: str
    amount: Decimal


class RatePoint(NamedTuple):
    effective_date: date
    interest_rate: Decimal
    penal_rate: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _apply_payment(principal: Decimal, balance: Decimal, amount: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    applied = min(balance, amount)
    remaining = amount - applied
    applied_to_principal = min(principal, remaining)
    return principal - applied_to_principal, balance - applied, remaining - applied_to_principal


def _apply_debit(principal: Decimal, credit: Decimal, amount: Decimal) -> tuple[Decimal, Decimal]:
    applied = min(credit, amount)
    return principal + amount - applied, credit - applied


def calculate_ledger(transactions: Iterable[LedgerEvent], sanctioned_limit: Decimal, rate_history: Iterable[RatePoint], start_date: date | None = None, end_date: date | None = None) -> dict[str, Decimal | date]:
    """Accrue an account using the latest rate row effective on each calendar day."""
    events: dict[date, list[LedgerEvent]] = defaultdict(list)
    for event in transactions:
        events[event.effective_date].append(event)
    rates = sorted(rate_history, key=lambda item: item.effective_date)
    if not rates:
        raise ValueError("rate_history must contain a baseline rate")
    if not events and start_date is None:
        today = end_date or date.today()
        return {"principal": Decimal("0.00"), "accrued_interest": Decimal("0.00"), "penalty_balance": Decimal("0.00"), "bank_charge_balance": Decimal("0.00"), "credit_balance": Decimal("0.00"), "overrun": Decimal("0.00"), "total_interest_accrued": Decimal("0.00"), "total_penalties_charged": Decimal("0.00"), "bank_charges": Decimal("0.00"), "incidental_charges": Decimal("0.00"), "as_of": today}

    final_date = end_date or date.today()
    event_dates = [event_date for event_date in events if event_date <= final_date]
    first_date = start_date or (min(event_dates) if event_dates else final_date)
    if first_date > final_date:
        raise ValueError("start_date cannot be after end_date")

    principal = Decimal("0")
    credit_balance = Decimal("0")
    accrued_interest = Decimal("0")
    penalty_balance = Decimal("0")
    bank_charge_balance = Decimal("0")
    total_interest = Decimal("0")
    total_penalties = Decimal("0")
    bank_charges = Decimal("0")
    incidental_charges = Decimal("0")
    rate_index = 0
    active_rate = rates[0]
    day = first_date
    while day <= final_date:
        while rate_index + 1 < len(rates) and rates[rate_index + 1].effective_date <= day:
            rate_index += 1
            active_rate = rates[rate_index]
        for event in events.get(day, []):
            if event.type in ("withdrawal", "debit"):
                principal, credit_balance = _apply_debit(principal, credit_balance, event.amount)
            elif event.type in ("principal_repayment", "credit"):
                principal, _, excess = _apply_payment(principal, Decimal("0"), event.amount)
                credit_balance += excess
            elif event.type == "interest_payment":
                principal, accrued_interest, excess = _apply_payment(principal, accrued_interest, event.amount)
                credit_balance += excess
            elif event.type == "penalty_payment":
                principal, penalty_balance, excess = _apply_payment(principal, penalty_balance, event.amount)
                credit_balance += excess
            elif event.type == "bank_penalty":
                penalty_balance += event.amount
                total_penalties += event.amount
            elif event.type == "penalty_waiver":
                waived = min(penalty_balance, event.amount)
                penalty_balance -= waived
                total_penalties -= waived
            elif event.type == "incidental_charge":
                principal, credit_balance = _apply_debit(principal, credit_balance, event.amount)
                bank_charges += event.amount
                incidental_charges += event.amount

        positive_principal = max(principal, Decimal("0"))
        overrun = max(positive_principal - sanctioned_limit, Decimal("0"))
        base_daily = positive_principal * (active_rate.interest_rate / PERCENT) / DAYS_PER_YEAR
        penal_daily = (overrun + penalty_balance) * (active_rate.penal_rate / PERCENT) / DAYS_PER_YEAR
        accrued_interest += base_daily
        penalty_balance += penal_daily
        total_interest += base_daily
        total_penalties += penal_daily

        next_day = day + timedelta(days=1)
        if next_day.month != day.month:
            principal, credit_balance = _apply_debit(principal, credit_balance, accrued_interest + penalty_balance + bank_charge_balance)
            accrued_interest = Decimal("0")
            penalty_balance = Decimal("0")
            bank_charge_balance = Decimal("0")
        day = next_day

    current_overrun = max(max(principal, Decimal("0")) - sanctioned_limit, Decimal("0"))
    return {"principal": _money(principal), "accrued_interest": _money(accrued_interest), "penalty_balance": _money(penalty_balance), "bank_charge_balance": _money(bank_charge_balance), "credit_balance": _money(credit_balance), "overrun": _money(current_overrun), "total_interest_accrued": _money(total_interest), "total_penalties_charged": _money(total_penalties), "bank_charges": _money(bank_charges), "incidental_charges": _money(incidental_charges), "as_of": final_date}
