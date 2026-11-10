"""Out-of-sample certification of the chance constraint (directive 5.5, council C1).

SAA is optimistic: a plan that protects all but K of N = 200 sampled scenarios breaches more often on fresh
ones. So we solve with K = 10, 8, 6, 4, 3, 2, 1, 0 (10 = EPSILON * N) and test each plan on 10,000 fresh
seed-B scenarios, stopping at the first pass. The test uses a one-sided Wilson upper bound with a
Bonferroni-adjusted z (0.05 split over the 9 possible steps, z = 2.539), because the ladder tests several plans. If K = 0 still fails, one fallback
solve with N = 1,000 and K = 5. If that fails too, the plan with the lowest seed-B bound ships with the miss shown in red.
Seed C is never used here.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from tempo.assumptions import EPSILON, FALLBACK_K, FALLBACK_N, K_LADDER, N_OPT_SCENARIOS, WILSON_Z_CERTIFY
from tempo.models import PaymentOption
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.options import PlannableBill
from tempo.optimize.stats import wilson_upper


@dataclass(frozen=True)
class CertStep:
    n: int
    k: int
    in_sample_breaches: int
    cert_breaches: int
    cert_n: int
    cert_rate: float
    cert_upper: float
    passed: bool
    solve_seconds: float
    value_cents: int


@dataclass(frozen=True)
class Certification:
    epsilon: float
    z: float
    steps: tuple[CertStep, ...]
    passed: bool
    shipped_index: int = -1  # which step's plan ships: the passing one, else the one with the lowest bound

    @property
    def final(self) -> CertStep:
        return self.steps[self.shipped_index]


def certify(
    bills: tuple[PlannableBill, ...],
    options: tuple[tuple[PaymentOption, ...], ...],
    headroom_a: np.ndarray,
    headroom_b: np.ndarray,
    as_of: date,
    headroom_a_fallback: np.ndarray | None = None,
    epsilon: float = EPSILON,
    z: float = WILSON_Z_CERTIFY,
    ladder: tuple[int, ...] = K_LADDER,
) -> tuple[Plan, Certification]:
    """Walk the K ladder (then the fallback) until a plan passes on seed B; return it with the record."""
    steps: list[CertStep] = []
    tried: list[Plan] = []
    attempts = [(headroom_a[:N_OPT_SCENARIOS], k) for k in ladder]
    if headroom_a_fallback is not None:
        attempts.append((headroom_a_fallback[:FALLBACK_N], FALLBACK_K))
    if not attempts:
        raise ValueError("the K ladder is empty")
    for headroom, k in attempts:
        plan = solve_plan(bills, options, headroom, as_of, k)
        step = _step(plan, headroom, headroom_b, as_of, k, epsilon, z)
        steps.append(step)
        tried.append(plan)
        if step.passed:
            return plan, Certification(epsilon, z, tuple(steps), True)
    safest = min(range(len(steps)), key=lambda i: (steps[i].cert_upper, -steps[i].value_cents))
    return tried[safest], Certification(epsilon, z, tuple(steps), False, safest)


def _step(
    plan: Plan, headroom_a: np.ndarray, headroom_b: np.ndarray, as_of: date, k: int, eps: float, z: float
) -> CertStep:
    in_sample = int(plan.breaches(headroom_a, as_of).sum())
    cert = int(plan.breaches(headroom_b, as_of).sum())
    n_b = headroom_b.shape[0]
    upper = wilson_upper(cert, n_b, z)
    return CertStep(
        n=headroom_a.shape[0],
        k=k,
        in_sample_breaches=in_sample,
        cert_breaches=cert,
        cert_n=n_b,
        cert_rate=cert / n_b,
        cert_upper=upper,
        passed=upper <= eps,
        solve_seconds=plan.stats.solve_seconds if plan.stats else 0.0,
        value_cents=plan.value_cents(),
    )
