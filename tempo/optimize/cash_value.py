"""Marginal value of cash by forward difference (directive 5.5).

A MILP has no meaningful duals (fixing the binaries and reading LP duals gives zero on every buffer row), so
we re-solve with $25,000 more starting cash:
    lambda       = (obj(B0 + step) - obj(B0)) / step          dollars of value per extra dollar over the horizon
    annual_rate  = lambda * 365 / horizon_days
    cost_of_cash = YIELD_ON_CASH + annual_rate                 (yield is already inside the objective)
An upward step is used because a downward one can force the backstop credit on and inflate the number. If
either solve draws backstop credit, the number is labeled "credit-bound".
"""

from dataclasses import dataclass

from tempo.assumptions import CASH_VALUE_STEP_CENTS, DAYS_IN_YEAR, YIELD_ON_CASH
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.run import RunInputs


@dataclass(frozen=True)
class CashValue:
    step_cents: int
    base_objective_cents: int
    bumped_objective_cents: int
    lam: float  # dollars per extra dollar over the horizon
    annual_rate: float
    cost_of_cash: float
    credit_bound: bool
    k: int
    n_scenarios: int


def marginal_value_of_cash(
    inputs: RunInputs, plan: Plan, step_cents: int = CASH_VALUE_STEP_CENTS
) -> CashValue:
    """Forward difference of the optimal objective in starting cash, at the certified K and N."""
    k = plan.k if plan.k is not None else 0
    n = plan.n_scenarios or inputs.headroom_a.shape[0]
    headroom = inputs.headroom_a_fallback[:n]
    base = solve_plan(inputs.bills, inputs.options, headroom, inputs.as_of, k)
    bumped = solve_plan(inputs.bills, inputs.options, headroom + step_cents, inputs.as_of, k)
    lam = max(0.0, (bumped.objective_cents() - base.objective_cents()) / step_cents)
    annual = lam * DAYS_IN_YEAR / inputs.horizon
    return CashValue(
        step_cents=step_cents,
        base_objective_cents=base.objective_cents(),
        bumped_objective_cents=bumped.objective_cents(),
        lam=lam,
        annual_rate=annual,
        cost_of_cash=YIELD_ON_CASH + annual,
        credit_bound=base.credit_drawn_cents() > 0 or bumped.credit_drawn_cents() > 0,
        k=k,
        n_scenarios=n,
    )
