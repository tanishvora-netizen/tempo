"""Fit each customer's days-to-pay law: lognormal with partial pooling across customers.

For customer i with log days-to-pay y_ij (j = 1..n_i):
    mu_hat_i    = mean_j y_ij
    sigma_hat_i = std_j y_ij (ddof = 1)
    mu_pool     = mean_i mu_hat_i                                   (between-customer center)
    sigma_pool  = sqrt( sum_i sum_j (y_ij - mu_hat_i)^2 / sum_i (n_i - 1) )   (within-customer spread)
    w_i         = n_i / (n_i + KAPPA)
    mu_i        = w_i * mu_hat_i    + (1 - w_i) * mu_pool
    sigma_i     = w_i * sigma_hat_i + (1 - w_i) * sigma_pool

sigma_pool uses within-customer residuals only; the total spread would add between-customer differences
and overstate each customer's timing noise (council C1, quant).
"""

import math
from dataclasses import dataclass

import numpy as np

from tempo.assumptions import KAPPA
from tempo.models import Customer


@dataclass(frozen=True)
class CustomerFit:
    customer_id: str
    n: int
    mu_hat: float
    sigma_hat: float
    weight: float
    mu: float
    sigma: float

    @property
    def median_days(self) -> float:
        """Median days-to-pay under the pooled law: exp(mu)."""
        return math.exp(self.mu)


@dataclass(frozen=True)
class PoolFit:
    kappa: float
    mu_pool: float
    sigma_pool: float
    customers: tuple[CustomerFit, ...]

    def params(self) -> dict[str, tuple[float, float]]:
        """customer id -> (mu, sigma) for the simulator."""
        return {c.customer_id: (c.mu, c.sigma) for c in self.customers}


def log_days(customer: Customer) -> np.ndarray:
    """Log days-to-pay for each historical payment (days are at least 1)."""
    days = [max(1, (p.paid_date - p.invoice_date).days) for p in customer.history]
    return np.log(np.asarray(days, dtype=float))


def fit_days_to_pay(customers: tuple[Customer, ...], kappa: float = KAPPA) -> PoolFit:
    """Partially pooled lognormal fit (formulas in the module docstring)."""
    logs = [log_days(c) for c in customers]
    means = [float(y.mean()) for y in logs if y.size]
    mu_pool = float(np.mean(means))
    sse = sum(float(((y - y.mean()) ** 2).sum()) for y in logs if y.size > 1)
    dof = sum(y.size - 1 for y in logs if y.size > 1)
    sigma_pool = math.sqrt(sse / dof)
    fits = tuple(_fit_one(c.id, y, mu_pool, sigma_pool, kappa) for c, y in zip(customers, logs, strict=True))
    return PoolFit(kappa=kappa, mu_pool=mu_pool, sigma_pool=sigma_pool, customers=fits)


def _fit_one(customer_id: str, y: np.ndarray, mu_pool: float, sigma_pool: float, kappa: float) -> CustomerFit:
    n = int(y.size)
    mu_hat = float(y.mean()) if n else mu_pool
    sigma_hat = float(y.std(ddof=1)) if n > 1 else sigma_pool
    w = n / (n + kappa)
    return CustomerFit(
        customer_id=customer_id,
        n=n,
        mu_hat=mu_hat,
        sigma_hat=sigma_hat,
        weight=w,
        mu=w * mu_hat + (1 - w) * mu_pool,
        sigma=w * sigma_hat + (1 - w) * sigma_pool,
    )
