"""End-of-day cash arithmetic shared by the optimizer, baselines, and evaluation.

All balances are end-of-day. For scenario s and day t (integer cents):
    headroom R[s, t] = B0 + inflow_cum[s, t] - fixed_cum[t] - BUFFER
    slack[s, t]      = R[s, t] - plan_cum[t] + credit_cum[t]
The balance stays at or above the buffer on day t exactly when slack[s, t] >= 0. A scenario breaches if
slack is negative on any day of the horizon.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from tempo.forecast.simulate import WhatIf
from tempo.models import FixedOutflow, PaymentOption


@dataclass(frozen=True)
class CashPosition:
    as_of: date
    horizon_days: int
    starting_cash_cents: int
    buffer_cents: int
    fixed_daily: np.ndarray = field(repr=False)  # (T,) int64 cents of deterministic outflows per day

    def fixed_cum(self) -> np.ndarray:
        return np.cumsum(self.fixed_daily)

    def headroom(self, inflow_cum: np.ndarray) -> np.ndarray:
        """R[s, t] = B0 + inflow_cum[s, t] - fixed_cum[t] - BUFFER, int64 cents."""
        return self.starting_cash_cents + inflow_cum - self.fixed_cum()[None, :] - self.buffer_cents

    def with_cash(self, delta_cents: int) -> "CashPosition":
        """Same position with more (or less) starting cash; used for the marginal value of cash."""
        return CashPosition(
            self.as_of,
            self.horizon_days,
            self.starting_cash_cents + delta_cents,
            self.buffer_cents,
            self.fixed_daily,
        )


def day_index(d: date, as_of: date, horizon_days: int) -> int:
    """Day offset from the as-of date, clamped into the horizon.

    Cash that leaves after the horizon counts on the last day (conservative; see DECISIONS.md).
    """
    return min(max((d - as_of).days, 0), horizon_days - 1)


def cash_position(
    as_of: date,
    horizon_days: int,
    starting_cash_cents: int,
    buffer_cents: int,
    fixed: tuple[FixedOutflow, ...],
    what_if: WhatIf | None = None,
) -> CashPosition:
    """Build the deterministic part of the cash position (fixed outflows plus any cash shock)."""
    daily = np.zeros(horizon_days, dtype=np.int64)
    for f in fixed:
        daily[day_index(f.on, as_of, horizon_days)] += f.amount_cents
    if what_if is not None and what_if.shock_cents:
        daily[min(max(what_if.shock_day, 0), horizon_days - 1)] += what_if.shock_cents
    return CashPosition(as_of, horizon_days, starting_cash_cents, buffer_cents, daily)


def plan_outflow_cum(options: tuple[PaymentOption, ...], as_of: date, horizon_days: int) -> np.ndarray:
    """Cumulative plan cash-out through each end of day, (T,) int64 cents."""
    daily = np.zeros(horizon_days, dtype=np.int64)
    for o in options:
        daily[day_index(o.cash_out_date, as_of, horizon_days)] += o.cash_out_cents
    return np.cumsum(daily)


def slack(headroom: np.ndarray, plan_cum: np.ndarray, credit_cum: np.ndarray | None = None) -> np.ndarray:
    """slack[s, t] = R[s, t] - plan_cum[t] + credit_cum[t] (int64 cents)."""
    credit = np.zeros_like(plan_cum) if credit_cum is None else credit_cum
    return headroom - plan_cum[None, :] + credit[None, :]


def breached(headroom: np.ndarray, plan_cum: np.ndarray, credit_cum: np.ndarray | None = None) -> np.ndarray:
    """Per scenario: True if the end-of-day balance falls below the buffer on any day."""
    return (slack(headroom, plan_cum, credit_cum) < 0).any(axis=1)


def first_breach_day(
    headroom: np.ndarray, plan_cum: np.ndarray, credit_cum: np.ndarray | None = None
) -> np.ndarray:
    """Per scenario: first day index with a breach, or -1."""
    neg = slack(headroom, plan_cum, credit_cum) < 0
    first = neg.argmax(axis=1)
    return np.where(neg.any(axis=1), first, -1)
