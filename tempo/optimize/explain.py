"""One templated sentence per decision, from solver output only (the model never writes these).

Binding reason for a skipped discount (council C1, quant): first the economics. If the best discount option
is worth no more than the chosen option, the reason is economic. Only when the discount is worth more do we
switch this one bill to it, keep everything else (including any credit) fixed, and recount breaches on the
optimizer's scenarios: if they exceed K, the cash constraint binds and we name the first day with a new
breach. Otherwise the solve stopped within its optimality gap.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np

from tempo.assumptions import CARD_CASHBACK
from tempo.models import Decision, FixedOutflow, PaymentOption
from tempo.money import format_usd
from tempo.optimize.baselines import annualized_discount_return
from tempo.optimize.cash import plan_outflow_cum, slack
from tempo.optimize.engine import Plan
from tempo.optimize.options import PlannableBill

EARLY_KINDS = ("BANK_EARLY", "CARD_EARLY", "FINANCE_EARLY")
METHOD_FOR_RAIL = {"RTP": "ACH", "ACH": "ACH", "CARD": "CARD", "FINANCE": "FINANCE"}


@dataclass(frozen=True)
class ExplainContext:
    plan: Plan
    headroom_a: np.ndarray  # optimizer scenarios used for the certified plan
    as_of: date
    buffer_cents: int
    epsilon: float
    cost_of_cash: float
    fixed_outflows: tuple[FixedOutflow, ...]


def fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}"


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%".replace(".0%", "%")


def terms_label(bill: PlannableBill) -> str:
    t = bill.terms
    if t.anchor == "prox":
        return f"Net {t.prox_day}th prox"
    base = f"net {t.net_days}" if t.net_days is not None else "net"
    eom = " EOM" if t.anchor == "eom" else ""
    if t.discount_bps:
        d = f"{t.discount_bps / 100:g}"
        return f"{d}/{t.discount_days} {base}{eom}"
    if t.anchor == "receipt":
        return "due on receipt"
    return f"{base}{eom}".capitalize()


def explain_all(ctx: ExplainContext) -> tuple[Decision, ...]:
    """A Decision with its reason for every bill in the plan."""
    base_cum = plan_outflow_cum(ctx.plan.chosen(), ctx.as_of, ctx.headroom_a.shape[1])
    base_breaches = int((slack(ctx.headroom_a, base_cum, ctx.plan.credit_cum_cents) < 0).any(axis=1).sum())
    out = []
    for bill, opts, c in zip(ctx.plan.bills, ctx.plan.options, ctx.plan.choice, strict=True):
        reason, binding = _reason(ctx, bill, opts, opts[c], base_cum, base_breaches)
        out.append(_decision(bill, opts[c], reason, binding))
    return tuple(out)


def _decision(bill: PlannableBill, o: PaymentOption, reason: str, binding: date | None) -> Decision:
    method = "LATE" if o.kind == "LATE" else METHOD_FOR_RAIL[o.rail]
    annual = annualized_discount_return(bill) if o.takes_discount else None
    return Decision(
        bill.id,
        o.send_date,
        method,
        o.kind,
        o.rail,
        o.cash_out_date,
        o.cash_out_cents,
        o.value_cents,
        annual,
        reason,
        binding,
    )


def _reason(
    ctx: ExplainContext, bill, opts, o: PaymentOption, base_cum, base_breaches
) -> tuple[str, date | None]:
    if o.kind == "LATE":
        return (
            f"Paid late on {fmt_date(o.arrival_date)}: paying on time would push the chance of dropping below the "
            f"{format_usd(ctx.buffer_cents)} buffer past {pct(ctx.epsilon, 0)}; costs a "
            f"{format_usd(o.fee_cents)} late fee. Review this one."
        ), None
    if o.kind in EARLY_KINDS:
        return _early_reason(ctx, bill, o), None
    if o.kind == "CARD":
        return _card_reason(o), None
    return _due_reason(ctx, bill, opts, o, base_cum, base_breaches)


def _early_reason(ctx: ExplainContext, bill: PlannableBill, o: PaymentOption) -> str:
    t = bill.terms
    early_days = (bill.due_date - o.arrival_date).days
    r = annualized_discount_return(bill)
    head = f"{t.discount_bps / 100:g}% for paying {early_days} days early, about {pct(r, 0)}/yr"
    if o.kind == "FINANCE_EARLY":
        return (
            f"Financed at the discount deadline {fmt_date(o.send_date)}: {head}; a Flex-style fee of "
            f"{format_usd(o.fee_cents)} and you repay {fmt_date(o.cash_out_date)}, so cash stays in the account."
        )
    if o.kind == "CARD_EARLY":
        return (
            f"Paid early by card {fmt_date(o.send_date)}: {head}, plus {pct(CARD_CASHBACK)} cashback; cash leaves "
            f"{fmt_date(o.cash_out_date)} with the statement."
        )
    return (
        f"Paid early {fmt_date(o.send_date)} by {o.rail}: {head}, beats your {pct(ctx.cost_of_cash, 0)}/yr "
        f"cost of cash."
    )


def _card_reason(o: PaymentOption) -> str:
    float_days = (o.cash_out_date - o.send_date).days
    surcharge = f", minus a {format_usd(o.surcharge_cents)} surcharge" if o.surcharge_cents else ""
    return (
        f"Paid by card {fmt_date(o.send_date)}: {pct(CARD_CASHBACK)} cashback{surcharge}; cash leaves "
        f"{fmt_date(o.cash_out_date)} with the statement (+{float_days} days)."
    )


def _due_reason(ctx: ExplainContext, bill, opts, o, base_cum, base_breaches) -> tuple[str, date | None]:
    head = f"Paid on the due date {fmt_date(bill.due_date)} by {o.rail}"
    if bill.terms.discount_bps and not bill.discount_usable:
        return (
            f"{head}: the discount terms are in Needs review, so no discount is taken until someone confirms them.",
            None,
        )
    early = max((x for x in opts if x.kind in EARLY_KINDS), key=lambda x: x.value_cents, default=None)
    if early is None:
        return _no_discount_reason(head, bill, opts, o), None
    r = annualized_discount_return(bill)
    if early.value_cents <= o.value_cents:
        return (
            f"{head}: the {terms_label(bill)} discount ({pct(r, 1)}/yr) is worth less than paying on the due date "
            f"after yield on cash."
        ), None
    return _binding_reason(ctx, bill, o, early, head, r, base_cum, base_breaches)


def _no_discount_reason(head: str, bill: PlannableBill, opts, o: PaymentOption) -> str:
    card = next((x for x in opts if x.kind == "CARD"), None)
    if card is not None and card.value_cents <= o.value_cents:
        return f"{head}: the card surcharge outweighs the cashback, and no discount is offered."
    if card is not None:
        return f"{head}: card would earn more but would push the risk of a buffer breach past the limit."
    return f"{head}: no discount is offered, so paying on the due date keeps the cash longest."


def _binding_reason(
    ctx: ExplainContext, bill, o, early, head, r, base_cum, base_breaches
) -> tuple[str, date | None]:
    horizon = ctx.headroom_a.shape[1]
    trial = base_cum.copy()
    trial -= _cum_of(o, ctx.as_of, horizon)
    trial += _cum_of(early, ctx.as_of, horizon)
    neg_new = slack(ctx.headroom_a, trial, ctx.plan.credit_cum_cents) < 0
    neg_old = slack(ctx.headroom_a, base_cum, ctx.plan.credit_cum_cents) < 0
    k = ctx.plan.k or 0
    if int(neg_new.any(axis=1).sum()) <= max(k, base_breaches):
        gain = format_usd(early.value_cents - o.value_cents)
        return (
            f"{head}: the {terms_label(bill)} discount (+{gain}) was left within the solver's optimality gap.",
            None,
        )
    newly = neg_new & ~neg_old
    day = int(np.argmax(newly.any(axis=0)))
    when = ctx.as_of + timedelta(days=day)
    label = _day_label(when, ctx.fixed_outflows)
    return (
        f"{head}: the {terms_label(bill)} discount ({pct(r, 1)}/yr) was skipped because paying early pushes the "
        f"chance of dropping below the {format_usd(ctx.buffer_cents)} buffer past {pct(ctx.epsilon, 0)}; the first "
        f"new shortfall is {label}{fmt_date(when)}."
    ), when


def _cum_of(o: PaymentOption, as_of: date, horizon: int) -> np.ndarray:
    return plan_outflow_cum((replace(o),), as_of, horizon)


def _day_label(d: date, fixed: tuple[FixedOutflow, ...]) -> str:
    kinds = {f.category for f in fixed if f.on == d}
    if "payroll" in kinds:
        return "payroll day, "
    if kinds:
        return f"{sorted(kinds)[0].replace('_', ' ')} day, "
    return ""
