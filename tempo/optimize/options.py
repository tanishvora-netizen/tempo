"""Candidate payment options for each bill (directive 5.3).

Every option is valued against the baseline "pay by bank so it arrives on the due date" (BANK_DUE), with one
formula:
    v = (A_base - c) + rewards + YIELD_ON_CASH * c * (t - t_base) / 365 - fees - penalty
where A_base is the bill's full amount, c the cash that leaves the company, t the day it leaves, and
t_base the day BANK_DUE's cash leaves. Paying later than the baseline earns yield; paying earlier loses it.

Rails: from Ramp Checking, RTP-eligible vendors are paid by RTP on the arrival date (free, 24/7); everyone
else by standard ACH sent `lead` business days before arrival (cash leaves on the send date). From an
external bank there is no RTP and ACH costs a fee.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from tempo.assumptions import (
    ACH_FEE_CENTS,
    ACH_LEAD_BUSINESS_DAYS,
    ACH_LEAD_DISCOUNT_BUSINESS_DAYS,
    ACH_LEAD_NEW_VENDOR_BUSINESS_DAYS,
    CARD_CASHBACK,
    CARD_STATEMENT_DAYS_AFTER_CLOSE,
    DAYS_IN_YEAR,
    DEFAULT_LATE_FEE_BPS_PER_MONTH,
    FINANCE_ENABLED,
    FINANCE_FEE_PER_30_DAYS,
    FINANCE_TERM_DAYS,
    LATE_DAYS,
    LATE_RELATIONSHIP_PENALTY,
    RTP_FEE_CENTS,
    YIELD_ON_CASH,
)
from tempo.business_days import (
    add_business_days,
    next_business_day,
    previous_business_day,
    subtract_business_days,
)
from tempo.models import LateFeeRecord, PaymentOption, TermsRecord
from tempo.money import apply_rate, bps_to_rate


@dataclass(frozen=True)
class PlannableBill:
    """A bill with resolved terms, ready for option generation."""

    id: str
    vendor_id: str
    vendor_name: str
    invoice_number: str
    issued_at: date
    subtotal_cents: int
    tax_cents: int
    freight_cents: int
    total_cents: int
    terms: TermsRecord
    due_date: date
    discount_deadline: date | None
    late_fee: LateFeeRecord | None
    accepts_card: bool
    surcharge_bps: int
    card_discount_allowed: bool
    rtp_eligible: bool
    is_new_vendor: bool
    discount_usable: bool  # False while terms are in Needs review: never take an unverified discount
    status: str  # reconciliation status chip


@dataclass(frozen=True)
class RailContext:
    as_of: date
    funding_account: str = "ramp_checking"
    finance_enabled: bool = FINANCE_ENABLED


@dataclass(frozen=True)
class _BankLeg:
    rail: str
    send: date  # a business day: Ramp rolls unavailable payment dates forward, which could miss a deadline
    arrival: date
    fee_cents: int


def statement_payment_date(charge: date) -> date:
    """Card statement closes on the last day of the charge month; it is paid N days after close.

    N = CARD_STATEMENT_DAYS_AFTER_CLOSE (ASSUMPTION).
    """
    next_month = date(charge.year + charge.month // 12, charge.month % 12 + 1, 1)
    close = next_month - timedelta(days=1)
    return close + timedelta(days=CARD_STATEMENT_DAYS_AFTER_CLOSE)


def yield_cents(cash_out_cents: int, cash_out: date, baseline: date) -> int:
    """YIELD_ON_CASH * c * (t - t_base) / 365, in cents (negative when cash leaves earlier than baseline)."""
    return apply_rate(cash_out_cents, YIELD_ON_CASH * (cash_out - baseline).days / DAYS_IN_YEAR)


def discounted_amount(bill: PlannableBill) -> int:
    """Discount applies to the pre-tax subtotal only: subtotal * (1 - d) + tax + freight."""
    d = bps_to_rate(bill.terms.discount_bps or 0)
    return bill.subtotal_cents - apply_rate(bill.subtotal_cents, d) + bill.tax_cents + bill.freight_cents


def late_fee_cents(bill: PlannableBill) -> int:
    """One month's late charge on the full amount, or the flat fee.

    Uses DEFAULT_LATE_FEE_BPS_PER_MONTH when the invoice states no late fee.
    """
    fee = bill.late_fee
    if fee is not None and fee.kind == "flat":
        return fee.flat_cents or 0
    bps = fee.pct_month_bps if fee is not None and fee.pct_month_bps else DEFAULT_LATE_FEE_BPS_PER_MONTH
    return apply_rate(bill.total_cents, bps_to_rate(bps))


def earliest_send(bill: PlannableBill, ctx: RailContext) -> date:
    """No payment goes out before today or before the invoice exists (expected bills issue later)."""
    return next_business_day(max(ctx.as_of, bill.issued_at))


def _bank_leg(bill: PlannableBill, ctx: RailContext, target: date, discount_window: bool) -> _BankLeg:
    """Latest business-day send that arrives by `target`; if that is already past, send on the first business
    day from the as-of date and arrive when the rail allows (possibly after `target`)."""
    if ctx.funding_account == "ramp_checking" and bill.rtp_eligible:
        send = max(previous_business_day(target), earliest_send(bill, ctx))
        return _BankLeg("RTP", send, send, RTP_FEE_CENTS)
    lead = ACH_LEAD_DISCOUNT_BUSINESS_DAYS if discount_window else ACH_LEAD_BUSINESS_DAYS
    if bill.is_new_vendor:
        lead = ACH_LEAD_NEW_VENDOR_BUSINESS_DAYS
    fee = 0 if ctx.funding_account == "ramp_checking" else ACH_FEE_CENTS
    send = max(subtract_business_days(target, lead), earliest_send(bill, ctx))
    return _BankLeg("ACH", send, add_business_days(send, lead), fee)


def _on_time(leg: _BankLeg, target: date) -> bool:
    return leg.arrival <= target


def build_options(bill: PlannableBill, ctx: RailContext) -> tuple[PaymentOption, ...]:
    """All feasible options for one bill; BANK_DUE and LATE always exist.

    BANK_DUE's arrival can fall after the due date only when the as-of date leaves too little ACH lead time;
    the option keeps its true arrival date so the UI and explanations can say so.
    """
    due_leg = _bank_leg(bill, ctx, bill.due_date, discount_window=False)
    base_send = due_leg.send
    base = _option(
        bill,
        "BANK_DUE",
        due_leg.rail,
        due_leg.send,
        due_leg.arrival,
        due_leg.send,
        bill.total_cents,
        base_send,
        rail_fee=due_leg.fee_cents,
    )
    options = [base]
    if _discount_open(bill, ctx):
        options += _discount_options(bill, ctx, base_send)
    if bill.accepts_card:
        options.append(
            _card(bill, "CARD", _charge_day(bill, bill.due_date, ctx), bill.total_cents, base_send)
        )
    options.append(_late(bill, ctx, base_send))
    return tuple(options)


def _charge_day(bill: PlannableBill, target: date, ctx: RailContext) -> date:
    """Card charges are scheduled on business days too, never before today or the invoice date."""
    return max(previous_business_day(target), earliest_send(bill, ctx))


def _discount_open(bill: PlannableBill, ctx: RailContext) -> bool:
    return bool(
        bill.discount_usable
        and bill.terms.discount_bps
        and bill.discount_deadline
        and bill.discount_deadline >= ctx.as_of
    )


def _discount_options(bill: PlannableBill, ctx: RailContext, base_send: date) -> list[PaymentOption]:
    """Options that take the discount; each must reach the vendor by the discount deadline."""
    deadline = bill.discount_deadline
    if deadline is None:
        return []
    paid = discounted_amount(bill)
    discount = bill.total_cents - paid
    out: list[PaymentOption] = []
    leg = _bank_leg(bill, ctx, deadline, discount_window=True)
    if _on_time(leg, deadline):
        out.append(
            _option(
                bill,
                "BANK_EARLY",
                leg.rail,
                leg.send,
                leg.arrival,
                leg.send,
                paid,
                base_send,
                rail_fee=leg.fee_cents,
                discount=discount,
            )
        )
    charge = previous_business_day(deadline)
    if bill.accepts_card and bill.card_discount_allowed and charge >= earliest_send(bill, ctx):
        out.append(_card(bill, "CARD_EARLY", charge, paid, base_send))
    if ctx.finance_enabled and charge >= earliest_send(bill, ctx):
        repay = charge + timedelta(days=FINANCE_TERM_DAYS)
        fee = apply_rate(paid, FINANCE_FEE_PER_30_DAYS * FINANCE_TERM_DAYS / 30)
        out.append(
            _option(
                bill,
                "FINANCE_EARLY",
                "FINANCE",
                charge,
                charge,
                repay,
                paid + fee,
                base_send,
                fee_in_cash=fee,
                discount=discount,
            )
        )
    return out


def _card(bill: PlannableBill, kind: str, charge_day: date, amount: int, base_send: date) -> PaymentOption:
    surcharge = apply_rate(amount, bps_to_rate(bill.surcharge_bps))
    charge = amount + surcharge
    return _option(
        bill,
        kind,
        "CARD",
        charge_day,
        charge_day,
        statement_payment_date(charge_day),
        charge,
        base_send,
        discount=bill.total_cents - amount,
        surcharge=surcharge,
        rewards=apply_rate(charge, CARD_CASHBACK),
    )


def _late(bill: PlannableBill, ctx: RailContext, base_send: date) -> PaymentOption:
    leg = _bank_leg(bill, ctx, bill.due_date + timedelta(days=LATE_DAYS), discount_window=False)
    fee = late_fee_cents(bill)
    return _option(
        bill,
        "LATE",
        leg.rail,
        leg.send,
        leg.arrival,
        leg.send,
        bill.total_cents + fee,
        base_send,
        rail_fee=leg.fee_cents,
        fee_in_cash=fee,
        penalty=apply_rate(bill.total_cents, LATE_RELATIONSHIP_PENALTY),
    )


def _option(
    bill: PlannableBill,
    kind: str,
    rail: str,
    send: date,
    arrival: date,
    cash_out: date,
    cash_out_cents: int,
    base_send: date,
    *,
    rail_fee: int = 0,
    fee_in_cash: int = 0,
    discount: int = 0,
    surcharge: int = 0,
    rewards: int = 0,
    penalty: int = 0,
) -> PaymentOption:
    """Assemble an option and its value v = (A_base - c) + rewards + yield - rail_fee - penalty.

    (A_base - c) already nets discounts, surcharges, and fees carried inside the cash amount (`fee_in_cash`:
    the financing fee or the late fee); the rail fee is paid separately and subtracted explicitly.
    """
    y = yield_cents(cash_out_cents, cash_out, base_send)
    value = (bill.total_cents - cash_out_cents) + rewards + y - rail_fee - penalty
    return PaymentOption(
        bill_id=bill.id,
        kind=kind,
        rail=rail,
        send_date=send,
        arrival_date=arrival,
        cash_out_date=cash_out,
        cash_out_cents=cash_out_cents,
        value_cents=value,
        takes_discount=discount > 0,
        discount_cents=discount,
        rewards_cents=rewards,
        fee_cents=rail_fee + fee_in_cash,
        surcharge_cents=surcharge,
        yield_cents=y,
        penalty_cents=penalty,
    )
