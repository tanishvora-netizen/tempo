"""Planning engine: forecast inputs, scenario sets, option sets, and solved plans.

Seeds: A builds the optimizer's scenarios, B certifies, C is used only for reported numbers, D only for the
starting-cash calibration (assumptions.py). The fan chart uses its own seed.
"""

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np

from tempo.assumptions import CREDIT_COST, N_OPT_SCENARIOS
from tempo.forecast.fit import PoolFit, fit_days_to_pay
from tempo.forecast.simulate import Receipt, ScenarioSet, WhatIf, receipts_from, simulate
from tempo.models import Dataset, PaymentOption
from tempo.optimize.cash import CashPosition, breached, cash_position, plan_outflow_cum
from tempo.optimize.milp import MilpStats, solve
from tempo.optimize.options import PlannableBill, RailContext, build_options


@dataclass(frozen=True)
class Forecast:
    """Everything needed to draw scenarios for one dataset and what-if."""

    fit: PoolFit
    receipts: tuple[Receipt, ...]
    cash: CashPosition
    horizon_days: int
    what_if: WhatIf | None

    def scenarios(
        self, n: int, seed: int, params: dict[str, tuple[float, float]] | None = None
    ) -> ScenarioSet:
        return simulate(
            self.receipts, params or self.fit.params(), self.horizon_days, n, seed, what_if=self.what_if
        )

    def headroom(self, scen: ScenarioSet) -> np.ndarray:
        return self.cash.headroom(scen.inflow_cum())


def build_forecast(dataset: Dataset, what_if: WhatIf | None = None, cash_delta_cents: int = 0) -> Forecast:
    c = dataset.company
    cash = cash_position(
        c.as_of,
        c.horizon_days,
        c.starting_cash_cents + cash_delta_cents,
        c.buffer_cents,
        dataset.fixed_outflows,
        what_if,
    )
    return Forecast(
        fit_days_to_pay(dataset.customers),
        receipts_from(dataset.customers, c.as_of),
        cash,
        c.horizon_days,
        what_if,
    )


def true_params(dataset: Dataset) -> dict[str, tuple[float, float]]:
    """The generator's true days-to-pay laws (robustness evaluation only)."""
    return {t.customer_id: (t.mu, t.sigma) for t in dataset.customer_truth}


def option_sets(bills: tuple[PlannableBill, ...], ctx: RailContext) -> tuple[tuple[PaymentOption, ...], ...]:
    return tuple(build_options(b, ctx) for b in bills)


@dataclass(frozen=True)
class Plan:
    """One option per bill, plus any backstop credit."""

    policy: str
    bills: tuple[PlannableBill, ...]
    options: tuple[tuple[PaymentOption, ...], ...]
    choice: tuple[int, ...]
    credit_cum_cents: np.ndarray = field(repr=False)
    k: int | None = None
    n_scenarios: int | None = None
    stats: MilpStats | None = None

    def chosen(self) -> tuple[PaymentOption, ...]:
        return tuple(opts[c] for opts, c in zip(self.options, self.choice, strict=True))

    def value_cents(self) -> int:
        return sum(o.value_cents for o in self.chosen())

    def credit_drawn_cents(self) -> int:
        return int(self.credit_cum_cents[-1]) if self.credit_cum_cents.size else 0

    def objective_cents(self) -> int:
        """Value net of the backstop credit cost (what the optimizer maximizes)."""
        return self.value_cents() - round(CREDIT_COST * self.credit_drawn_cents())

    def outflow_cum(self, as_of, horizon_days: int) -> np.ndarray:
        return plan_outflow_cum(self.chosen(), as_of, horizon_days)

    def breaches(self, headroom: np.ndarray, as_of) -> np.ndarray:
        return breached(headroom, self.outflow_cum(as_of, headroom.shape[1]), self.credit_cum_cents)

    def plan_hash(self) -> str:
        """sha256 of canonical, float-free JSON: (bill id, option kind, send date, cash-out date, cents)."""
        rows = sorted(
            (o.bill_id, o.kind, o.send_date.isoformat(), o.cash_out_date.isoformat(), o.cash_out_cents)
            for o in self.chosen()
        )
        payload = {"rows": rows, "credit_cents": [int(x) for x in self.credit_cum_cents]}
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def solve_plan(
    bills: tuple[PlannableBill, ...],
    options: tuple[tuple[PaymentOption, ...], ...],
    headroom: np.ndarray,
    as_of,
    k: int,
    policy: str = "tempo",
) -> Plan:
    """Solve the chance-constrained MILP on the given optimizer scenarios."""
    result = solve(options, headroom, as_of, k)
    return Plan(
        policy, bills, options, result.choice, result.credit_cum_cents, k, headroom.shape[0], result.stats
    )


def default_optimizer_scenarios(forecast: Forecast, seed: int, n: int = N_OPT_SCENARIOS) -> np.ndarray:
    return forecast.headroom(forecast.scenarios(n, seed))
