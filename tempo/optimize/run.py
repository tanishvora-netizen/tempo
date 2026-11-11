"""One full planning run: inputs, Tempo with certification, the baselines, and their evaluation.

Shared by scripts/calibrate_cash.py, scripts/precompute.py, and scripts/make_results.py so every number in
docs/RESULTS.md and the UI comes from the same code path.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from tempo.assumptions import (
    EPSILON,
    FALLBACK_N,
    FINANCE_ENABLED,
    N_CERT_SCENARIOS,
    N_OPT_SCENARIOS,
    SEED_A,
    SEED_B,
    SOLVER_TIME_LIMIT_S,
    YIELD_ON_CASH,
)
from tempo.forecast.simulate import WhatIf
from tempo.models import Dataset, PaymentOption, TermsRecord
from tempo.optimize import baselines as bl
from tempo.optimize.certify import Certification, certify
from tempo.optimize.engine import Forecast, Plan, build_forecast, option_sets
from tempo.optimize.evaluate import PolicyResult, evaluate
from tempo.optimize.options import FINANCE_KINDS_ALL, PlannableBill, RailContext
from tempo.pipeline import IngestResult, plannable_bills

POLICY_ORDER = ("pay_on_due", "weekly_run", "greedy_discount", "greedy_p05", "deterministic_p50", "tempo")


@dataclass(frozen=True)
class RunInputs:
    dataset: Dataset
    bills: tuple[PlannableBill, ...]
    options: tuple[tuple[PaymentOption, ...], ...]
    forecast: Forecast
    headroom_a: np.ndarray = field(repr=False)  # seed A, N_OPT_SCENARIOS
    headroom_a_fallback: np.ndarray = field(repr=False)  # seed A, FALLBACK_N (first rows equal headroom_a)
    headroom_b: np.ndarray = field(repr=False)  # seed B, N_CERT_SCENARIOS

    @property
    def as_of(self) -> date:
        return self.dataset.company.as_of

    @property
    def horizon(self) -> int:
        return self.dataset.company.horizon_days


def prepare(
    dataset: Dataset,
    ingest_result: IngestResult,
    what_if: WhatIf | None = None,
    overrides: dict[str, TermsRecord] | None = None,
    cash_delta_cents: int = 0,
    finance_enabled: bool = FINANCE_ENABLED,
    finance_kinds: tuple[str, ...] = FINANCE_KINDS_ALL,
    n_opt: int = N_OPT_SCENARIOS,
    n_fallback: int = FALLBACK_N,
    n_cert: int = N_CERT_SCENARIOS,
) -> RunInputs:
    """Resolve bills and options and draw the optimizer (A) and certification (B) scenarios.

    The sizes default to the certified ones; only the live path on the small host passes smaller ones."""
    bills = plannable_bills(dataset, ingest_result, overrides)
    ctx = RailContext(dataset.company.as_of, dataset.company.funding_account, finance_enabled, finance_kinds)
    options = option_sets(bills, ctx)
    forecast = build_forecast(dataset, what_if, cash_delta_cents)
    fallback = forecast.headroom(forecast.scenarios(n_fallback, SEED_A))
    head_a = fallback[:n_opt]
    head_b = forecast.headroom(forecast.scenarios(n_cert, SEED_B))
    return RunInputs(dataset, bills, options, forecast, head_a, fallback, head_b)


def run_tempo(inputs: RunInputs, time_limit: float = SOLVER_TIME_LIMIT_S) -> tuple[Plan, Certification]:
    return certify(
        inputs.bills,
        inputs.options,
        inputs.headroom_a,
        inputs.headroom_b,
        inputs.as_of,
        inputs.headroom_a_fallback,
        time_limit=time_limit,
    )


def baseline_plans(inputs: RunInputs, cost_of_cash: float = YIELD_ON_CASH) -> dict[str, Plan]:
    """Every comparison policy, planned on seed-A information only."""
    p50 = bl.quantile_path(inputs.headroom_a, 0.5)
    p05 = bl.quantile_path(inputs.headroom_a, 0.05)
    b, o, a, h = inputs.bills, inputs.options, inputs.as_of, inputs.horizon
    return {
        "pay_on_due": bl.pay_on_due(b, o, h),
        "weekly_run": bl.weekly_run(b, o, a, h),
        "greedy_discount": bl.greedy(b, o, p50, a, "greedy_discount"),
        "greedy_p05": bl.greedy(b, o, p05, a, "greedy_p05", min_annual_return=cost_of_cash),
        "deterministic_p50": bl.path_plan(b, o, p50, a, "deterministic_p50"),
    }


def ablation_plans(inputs: RunInputs) -> dict[str, Plan]:
    """Per-day chance constraints instead of Tempo's joint one, planned on the 1,000 seed-A scenarios.

    "per_day_worst_case" is Bonferroni at 0.05 / 91 days per day, which at 1,000 scenarios reduces to the
    pointwise minimum (council C2, quant).
    """
    head = inputs.headroom_a_fallback
    b, o, a = inputs.bills, inputs.options, inputs.as_of
    return {
        "per_day_5pct": bl.path_plan(b, o, bl.quantile_path(head, EPSILON), a, "per_day_5pct"),
        "per_day_worst_case": bl.path_plan(
            b, o, bl.quantile_path(head, EPSILON / inputs.horizon), a, "per_day_worst_case"
        ),
        "deterministic_p50": bl.path_plan(b, o, bl.quantile_path(head, 0.5), a, "deterministic_p50"),
    }


def evaluate_all(plans: dict[str, Plan], headroom: np.ndarray, inputs: RunInputs) -> dict[str, PolicyResult]:
    buffer = inputs.dataset.company.buffer_cents
    return {name: evaluate(p, headroom, inputs.as_of, buffer) for name, p in plans.items()}
