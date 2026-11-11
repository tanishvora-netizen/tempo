"""Live re-solves for custom what-ifs and review edits (the UI shows progress and solve time).

A live re-solve keeps the base plan's certified K and N, then recounts breaches on the 10,000 seed-B
scenarios and shows that estimate with its bound. Re-running the full certification ladder is reserved for
the precomputed presets; a live plan whose seed-B bound exceeds EPSILON is labeled "not re-certified"
(council C1, judge).
"""

import time
from dataclasses import dataclass

from tempo.assumptions import EPSILON, N_FAN_SCENARIOS, SEED_FAN, SOLVER_TIME_LIMIT_S, WILSON_Z_REPORT
from tempo.forecast.simulate import WhatIf
from tempo.models import Dataset, TermsRecord
from tempo.optimize.cash_value import CashValue
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.evaluate import balance_fan, evaluate
from tempo.optimize.explain import ExplainContext, explain_all
from tempo.optimize.run import baseline_plans, prepare
from tempo.pipeline import IngestResult
from tempo.report import bill_rows, diff_plans, kpis
from tempo.whatif import tradeoff


@dataclass(frozen=True)
class LiveResult:
    plan: Plan
    payload: dict
    seconds: float


def live_solve(
    dataset: Dataset,
    ingest_result: IngestResult,
    base_plan: Plan,
    cash_value: CashValue,
    what_if: WhatIf | None = None,
    overrides: dict[str, TermsRecord] | None = None,
    time_limit: float = SOLVER_TIME_LIMIT_S,
) -> LiveResult:
    """Re-solve at the base plan's K and N; report the seed-B estimate (not a fresh certification).

    What-ifs allow Flex-style financing (within FLEX_LIMIT) before any late payment, exactly as the presets do;
    review edits change the headline plan, so they keep financing off."""
    started = time.perf_counter()
    stressed = what_if is not None and not what_if.is_empty()
    inputs = prepare(dataset, ingest_result, what_if, overrides, finance_enabled=stressed)
    k = base_plan.k if base_plan.k is not None else 0
    n = base_plan.n_scenarios or inputs.headroom_a.shape[0]
    head_a = inputs.headroom_a_fallback[:n]
    plan = solve_plan(inputs.bills, inputs.options, head_a, inputs.as_of, k, time_limit=time_limit)
    c = dataset.company
    head_b = inputs.headroom_b  # integer cents (ADR-14); float32 would round cents and save only ~4 MB
    est = evaluate(plan, head_b, c.as_of, c.buffer_cents, WILSON_Z_REPORT)
    box = (
        tradeoff(plan, est, base_plan, head_a, head_b, c.as_of, c.buffer_cents, time_limit=time_limit / 2)
        if stressed
        else None
    )
    timed_out = plan.stats is not None and plan.stats.status == "time_limit"
    fan_head = inputs.forecast.headroom(inputs.forecast.scenarios(N_FAN_SCENARIOS, SEED_FAN))
    pay_on_due = baseline_plans(inputs)["pay_on_due"]
    ctx = ExplainContext(
        plan, head_a, c.as_of, c.buffer_cents, EPSILON, cash_value.cost_of_cash, dataset.fixed_outflows
    )
    decisions = explain_all(ctx)
    seconds = time.perf_counter() - started
    payload = {
        "kpis": kpis(plan, est, cash_value, c.buffer_cents, c.as_of),
        "estimate": {
            "seed": "B",
            "n": est.n_scenarios,
            "breaches": est.breaches,
            "rate": est.breach_rate,
            "upper": est.breach_upper,
            "within_target": est.breach_upper <= EPSILON,
            "label": "out-of-sample estimate on seed B at the base plan's K; not re-certified",
        },
        "k": k,
        "n": n,
        "fan_after": balance_fan(plan, fan_head, c.as_of, c.buffer_cents),
        "fan_before": balance_fan(pay_on_due, fan_head, c.as_of, c.buffer_cents),
        "diff": diff_plans(base_plan, plan, decisions),
        "bills": bill_rows(plan, decisions, ingest_result.reconciled, c.as_of),
        "tradeoff": box,
        "time_limit_reached": timed_out,
        "solver_status": "time limit reached, best plan found" if timed_out else "optimal",
        "solve_seconds": plan.stats.solve_seconds if plan.stats else None,
        "total_seconds": seconds,
        "plan_hash": plan.plan_hash(),
    }
    return LiveResult(plan, payload, seconds)
