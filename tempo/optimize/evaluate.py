"""Evaluate any plan on a scenario set (directive 5.6): value, breach rate with its bound, worst P10."""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from tempo.assumptions import WILSON_Z_REPORT
from tempo.optimize.cash import slack
from tempo.optimize.engine import Plan
from tempo.optimize.stats import wilson_upper


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    value_cents: int  # vs pay_on_due (every option is valued against paying by bank on the due date)
    discounts_cents: int
    rewards_cents: int
    n_scenarios: int
    breaches: int
    breach_rate: float
    breach_upper: float  # one-sided Wilson 95%
    worst_p10_balance_cents: int
    worst_p10_date: date
    late_count: int
    arrive_after_due_count: int
    credit_drawn_cents: int
    discount_count: int
    card_count: int
    worst_shortfall_cents: int = (
        0  # how far the worst scenario's lowest balance falls below the buffer (0 if none)
    )
    worst_shortfall_date: date | None = None  # the day it happens


def evaluate(
    plan: Plan, headroom: np.ndarray, as_of: date, buffer_cents: int, z: float = WILSON_Z_REPORT
) -> PolicyResult:
    """Realized breach probability (any end-of-day balance below the buffer) and balance quantiles."""
    plan_cum = plan.outflow_cum(as_of, headroom.shape[1])
    s = slack(headroom, plan_cum, plan.credit_cum_cents)
    breached = (s < 0).any(axis=1)
    lowest = float(s.min()) if s.size else 0.0
    worst_day = int(np.unravel_index(int(np.argmin(s)), s.shape)[1]) if lowest < 0 else None
    p10 = np.percentile(s, 10, axis=0) + buffer_cents  # P10 of end-of-day balance per day
    worst = int(np.argmin(p10))
    chosen = plan.chosen()
    n = headroom.shape[0]
    return PolicyResult(
        policy=plan.policy,
        value_cents=plan.value_cents(),
        discounts_cents=sum(o.discount_cents for o in chosen if o.takes_discount),
        rewards_cents=sum(o.rewards_cents for o in chosen),
        n_scenarios=n,
        breaches=int(breached.sum()),
        breach_rate=float(breached.mean()),
        breach_upper=wilson_upper(int(breached.sum()), n, z),
        worst_p10_balance_cents=round(p10[worst]),
        worst_p10_date=as_of + timedelta(days=worst),
        late_count=sum(o.kind == "LATE" for o in chosen),
        arrive_after_due_count=sum(
            o.kind != "LATE" and o.arrival_date > b.due_date for b, o in zip(plan.bills, chosen, strict=True)
        ),
        credit_drawn_cents=plan.credit_drawn_cents(),
        discount_count=sum(o.takes_discount for o in chosen),
        card_count=sum(o.rail == "CARD" for o in chosen),
        worst_shortfall_cents=round(-lowest) if lowest < 0 else 0,
        worst_shortfall_date=as_of + timedelta(days=worst_day) if worst_day is not None else None,
    )


def balance_fan(
    plan: Plan | None, headroom: np.ndarray, as_of: date, buffer_cents: int
) -> dict[str, list[int]]:
    """Pointwise P10 / P50 / P90 of end-of-day balance (cents), before (plan=None: no bills paid) or after."""
    if plan is None:
        s = headroom
    else:
        s = slack(headroom, plan.outflow_cum(as_of, headroom.shape[1]), plan.credit_cum_cents)
    bal = s + buffer_cents
    p1, p10, p50, p90, p99 = np.percentile(bal, [1, 10, 50, 90, 99], axis=0)
    return {"p1": _ints(p1), "p10": _ints(p10), "p50": _ints(p50), "p90": _ints(p90), "p99": _ints(p99)}


def _ints(a: np.ndarray) -> list[int]:
    return [round(x) for x in a]
