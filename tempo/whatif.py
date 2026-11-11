"""What-if tradeoffs (final fix pass, item 4): what it costs to stay under the risk target, three ways.

For one stressed scenario set, given the what-if plan (financing allowed, then late payments as a last resort):
  (i)   stay under target with financing only (no late payments): the financing fees it costs;
  (ii)  stay under target with late payments only (no financing): the late fees and how many bills go late;
  (iii) accept the risk: keep the current plan unchanged and report its breach rate under the stress.
Variants (i) and (ii) are solved at the what-if plan's K and N and scored on the same scenarios as the plan
(seed C for presets, seed B for live runs). They are estimates, not separately certified.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from tempo.assumptions import EPSILON, SOLVER_TIME_LIMIT_S, WILSON_Z_REPORT
from tempo.models import PaymentOption
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.evaluate import PolicyResult, evaluate
from tempo.optimize.options import PlannableBill

FINANCE_KINDS = ("FINANCE_DUE", "FINANCE_EARLY")


@dataclass(frozen=True)
class Variant:
    plan: Plan
    result: PolicyResult


def drop_kinds(
    options: tuple[tuple[PaymentOption, ...], ...], kinds: tuple[str, ...]
) -> tuple[tuple[PaymentOption, ...], ...]:
    """The same option sets without the given kinds (BANK_DUE always stays, so no bill is left empty)."""
    return tuple(tuple(o for o in opts if o.kind not in kinds) for opts in options)


def finance_fees_cents(plan: Plan) -> int:
    return sum(o.fee_cents for o in plan.chosen() if o.rail == "FINANCE")


def late_fees_cents(plan: Plan) -> int:
    return sum(o.fee_cents for o in plan.chosen() if o.kind == "LATE")


def late_count(plan: Plan) -> int:
    return sum(o.kind == "LATE" for o in plan.chosen())


def uses(plan: Plan, kinds: tuple[str, ...]) -> bool:
    return any(o.kind in kinds for o in plan.chosen())


def _variant(
    bills: tuple[PlannableBill, ...],
    options: tuple[tuple[PaymentOption, ...], ...],
    head_opt: np.ndarray,
    head_eval: np.ndarray,
    as_of: date,
    buffer_cents: int,
    k: int,
    drop: tuple[str, ...],
    time_limit: float,
) -> Variant:
    plan = solve_plan(bills, drop_kinds(options, drop), head_opt, as_of, k, time_limit=time_limit)
    return Variant(plan, evaluate(plan, head_eval, as_of, buffer_cents, WILSON_Z_REPORT))


def _side(v: Variant, fee_cents: int, epsilon: float, certified: bool = False) -> dict:
    """One option of the box. `certified` marks the option that IS the certified what-if plan: it is under the
    target by certification on seed B, even when its seed-C check lands a little above it."""
    r = v.result
    return {
        "fees_cents": fee_cents,
        "value_cents": v.plan.value_cents(),
        "late_count": late_count(v.plan),
        "financed_count": sum(o.rail == "FINANCE" for o in v.plan.chosen()),
        "breach_rate": r.breach_rate,
        "breach_upper": r.breach_upper,
        "credit_drawn_cents": v.plan.credit_drawn_cents(),
        # measured rate on the shared scenarios (the bound is shown too): the what-if plan itself is certified on
        # seed B, and its seed-C bound can sit just above 5% while its rate is under it
        "under_target": (certified or r.breach_rate <= epsilon) and v.plan.credit_drawn_cents() == 0,
        "certified": certified,
    }


def tradeoff(
    main: Plan,
    main_result: PolicyResult,
    current: Plan,
    head_opt: np.ndarray,
    head_eval: np.ndarray,
    as_of: date,
    buffer_cents: int,
    epsilon: float = EPSILON,
    time_limit: float = SOLVER_TIME_LIMIT_S,
    main_certified: bool = False,
) -> dict:
    """The three-way tradeoff box. Re-uses the what-if plan wherever it already is that variant."""
    k = main.k if main.k is not None else 0
    main_v = Variant(main, main_result)
    fin = (
        main_v
        if not uses(main, ("LATE",))
        else _variant(
            main.bills, main.options, head_opt, head_eval, as_of, buffer_cents, k, ("LATE",), time_limit
        )
    )
    late = (
        main_v
        if not uses(main, FINANCE_KINDS)
        else _variant(
            main.bills, main.options, head_opt, head_eval, as_of, buffer_cents, k, FINANCE_KINDS, time_limit
        )
    )
    keep = evaluate(current, head_eval, as_of, buffer_cents, WILSON_Z_REPORT)
    return {
        "financing": _side(fin, finance_fees_cents(fin.plan), epsilon, main_certified and fin is main_v),
        "late_only": _side(late, late_fees_cents(late.plan), epsilon, main_certified and late is main_v),
        "accept_risk": {
            "breach_rate": keep.breach_rate,
            "breach_upper": keep.breach_upper,
            "worst_shortfall_cents": keep.worst_shortfall_cents,
            "worst_shortfall_date": keep.worst_shortfall_date.isoformat()
            if keep.worst_shortfall_date
            else None,
            "value_cents": current.value_cents(),
        },
        "n": int(head_eval.shape[0]),
        "label": "variants solved at the what-if plan's K; estimates on the same scenarios, not certified",
    }
