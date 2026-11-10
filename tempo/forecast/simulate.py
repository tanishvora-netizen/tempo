"""Monte Carlo scenarios of daily cash inflows over the horizon.

Model for receivable j of customer c in scenario s (days-to-pay D counted from the invoice date):
    log D_sj = mu_c + SIGMA_MACRO * Z_s + sigma_c * eps_sj,   Z_s ~ N(0, 1) shared by every invoice in s.
The common factor Z_s moves every customer together ("multiply every delay by exp(SIGMA_MACRO * Z_s)");
without it, independent draws average out and the fan and the risk bound are too narrow.

An invoice already outstanding for e days is drawn conditional on D > e (truncated lognormal):
    x   = (ln e - mu_c - SIGMA_MACRO * Z_s) / sigma_c
    eps = isf( u * sf(x) ),  u ~ U(0, 1)   (sf = standard normal survival function, isf its inverse)
i.e. `norm.isf(u * norm.sf(x))`, which stays accurate when e is deep in the tail (council C1, quant).
The payment lands on day floor(issue_offset + D) relative to the as-of date. Each invoice independently
fails to pay within the horizon with probability P_NO_PAY. Amounts are known; only timing is random.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.stats import norm

from tempo.assumptions import P_NO_PAY, SIGMA_MACRO
from tempo.models import Customer

NEVER = np.iinfo(np.int64).max // 4


@dataclass(frozen=True)
class Receipt:
    """One expected customer payment: an open receivable or a scheduled billing."""

    id: str
    customer_id: str
    issue_offset: int  # (issued_at - as_of) in days; negative for invoices already outstanding
    amount_cents: int


@dataclass(frozen=True)
class WhatIf:
    """A stress applied before simulation: delay one customer, and/or a one-off cash shock."""

    delay_customer_id: str | None = None
    delay_days: int = 0
    shock_cents: int = 0  # unexpected outflow
    shock_day: int = 0  # day index of the shock

    def is_empty(self) -> bool:
        return (self.delay_customer_id is None or self.delay_days == 0) and self.shock_cents == 0


@dataclass(frozen=True)
class ScenarioSet:
    """Daily inflows per scenario, in integer cents."""

    seed: int
    inflows: np.ndarray = field(repr=False)  # shape (n, horizon_days), int64 cents
    z: np.ndarray = field(repr=False)  # common factor per scenario, shape (n,)

    @property
    def n(self) -> int:
        return int(self.inflows.shape[0])

    def inflow_cum(self) -> np.ndarray:
        """Cumulative inflows through each end of day, shape (n, horizon_days), int64 cents."""
        return np.cumsum(self.inflows, axis=1)


def receipts_from(customers: tuple[Customer, ...], as_of: date) -> tuple[Receipt, ...]:
    """Open receivables and scheduled billings as forecast inputs."""
    items = []
    for c in customers:
        for r in (*c.open_receivables, *c.scheduled_billings):
            items.append(Receipt(r.id, c.id, (r.issued_at - as_of).days, r.amount_cents))
    return tuple(items)


def simulate(
    receipts: tuple[Receipt, ...],
    params: dict[str, tuple[float, float]],
    horizon_days: int,
    n: int,
    seed: int,
    sigma_macro: float = SIGMA_MACRO,
    p_no_pay: float = P_NO_PAY,
    what_if: WhatIf | None = None,
) -> ScenarioSet:
    """Draw `n` scenarios of daily inflows (see module docstring for the model)."""
    rng = np.random.default_rng(seed)
    mu = np.array([params[r.customer_id][0] for r in receipts])
    sigma = np.array([params[r.customer_id][1] for r in receipts])
    offset = np.array([r.issue_offset for r in receipts])
    amount = np.array([r.amount_cents for r in receipts], dtype=np.int64)
    z = rng.standard_normal(n)
    days = _days_to_pay(rng, mu, sigma, offset, z, sigma_macro)
    pay_day = np.floor(offset[None, :] + days)
    pay_day = np.where(rng.random(pay_day.shape) < p_no_pay, NEVER, pay_day)
    pay_day = _apply_delay(pay_day, receipts, what_if)
    return ScenarioSet(seed=seed, inflows=_bucket(pay_day, amount, horizon_days), z=z)


def _days_to_pay(
    rng: np.random.Generator,
    mu: np.ndarray,
    sigma: np.ndarray,
    offset: np.ndarray,
    z: np.ndarray,
    sigma_macro: float,
) -> np.ndarray:
    """Days-to-pay draws, shape (n, J); outstanding invoices are truncated at their elapsed days."""
    loc = mu[None, :] + sigma_macro * z[:, None]
    elapsed = np.maximum(-offset, 0).astype(float)
    with np.errstate(divide="ignore"):
        x = (np.log(elapsed)[None, :] - loc) / sigma[None, :]
    tail = norm.sf(x)  # P(D > elapsed); 1 when nothing has elapsed
    u = rng.random(loc.shape)
    eps = norm.isf(np.maximum(u * tail, np.finfo(float).tiny))
    return np.exp(loc + sigma[None, :] * eps)


def _apply_delay(pay_day: np.ndarray, receipts: tuple[Receipt, ...], what_if: WhatIf | None) -> np.ndarray:
    if what_if is None or what_if.delay_customer_id is None or what_if.delay_days == 0:
        return pay_day
    mask = np.array([r.customer_id == what_if.delay_customer_id for r in receipts])
    return np.where(mask[None, :] & (pay_day < NEVER), pay_day + what_if.delay_days, pay_day)


def _bucket(pay_day: np.ndarray, amount: np.ndarray, horizon_days: int) -> np.ndarray:
    """Sum payment amounts into (scenario, day) cells; payments outside the horizon are dropped."""
    n = pay_day.shape[0]
    inside = (pay_day >= 0) & (pay_day < horizon_days)
    rows = np.broadcast_to(np.arange(n)[:, None], pay_day.shape)[inside]
    cols = pay_day[inside].astype(np.int64)
    weights = np.broadcast_to(amount[None, :], pay_day.shape)[inside]
    flat = np.bincount(rows * horizon_days + cols, weights=weights, minlength=n * horizon_days)
    return np.rint(flat).astype(np.int64).reshape(n, horizon_days)
