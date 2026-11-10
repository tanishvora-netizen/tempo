"""Fit each customer's days-to-pay law: lognormal, censored, with partial pooling across customers.

Invoices still open at the as-of date are right-censored: they have taken longer than their elapsed days so
far. Fitting on paid invoices alone would bias every customer toward paying early (council C2, quant). For
customer i, with log days-to-pay y_ij of paid invoices and log elapsed days l_ik of open invoices:

    (mu_hat_i, sigma_hat_i) = argmax  sum_j [log phi((y_ij - mu) / s) - log s]  +  sum_k log Phi_sf((l_ik - mu) / s)
    mu_pool     = mean_i mu_hat_i                                              (between-customer center)
    sigma_pool  = sqrt( sum_i (n_i - 1) sigma_hat_i^2 / sum_i (n_i - 1) )      (within-customer spread)
    w_i         = n_i / (n_i + KAPPA),   n_i = paid + open invoices
    mu_i        = w_i * mu_hat_i    + (1 - w_i) * mu_pool
    sigma_i     = w_i * sigma_hat_i + (1 - w_i) * sigma_pool

sigma_pool uses within-customer spread only; the total spread would add between-customer differences and
overstate each customer's timing noise (council C1, quant). With no open invoices the MLE is the ordinary
lognormal fit.
"""

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from tempo.assumptions import KAPPA
from tempo.models import Customer

SIGMA_FLOOR = 1e-3  # keeps the likelihood finite for a customer who always pays on the same day


@dataclass(frozen=True)
class CustomerFit:
    customer_id: str
    n: int
    n_open: int
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


def log_elapsed(customer: Customer, as_of: date | None) -> np.ndarray:
    """Log elapsed days of invoices still open at `as_of` (censored observations); empty if as_of is None."""
    if as_of is None:
        return np.zeros(0)
    elapsed = [(as_of - r.issued_at).days for r in customer.open_receivables]
    return np.log(np.asarray([e for e in elapsed if e >= 1], dtype=float))


def censored_mle(paid: np.ndarray, censored: np.ndarray) -> tuple[float, float]:
    """Maximum-likelihood (mu, sigma) for log days with right-censored observations (formula in the docstring)."""
    if paid.size == 0:
        raise ValueError("a customer needs at least one paid invoice to fit")
    mu0 = float(paid.mean())
    s0 = max(float(paid.std()), 0.05)

    def nll(theta: np.ndarray) -> float:
        mu, s = theta[0], max(math.exp(theta[1]), SIGMA_FLOOR)
        ll = norm.logpdf((paid - mu) / s).sum() - paid.size * math.log(s)
        ll += norm.logsf((censored - mu) / s).sum()
        return -float(ll)

    res = minimize(
        nll,
        np.array([mu0, math.log(s0)]),
        method="Nelder-Mead",
        options={"xatol": 1e-6, "fatol": 1e-9, "maxiter": 2000},
    )
    return float(res.x[0]), max(math.exp(float(res.x[1])), SIGMA_FLOOR)


def fit_days_to_pay(
    customers: tuple[Customer, ...], as_of: date | None = None, kappa: float = KAPPA
) -> PoolFit:
    """Censored, partially pooled lognormal fit (formulas in the module docstring)."""
    paid = [log_days(c) for c in customers]
    opened = [log_elapsed(c, as_of) for c in customers]
    if not any(y.size for y in paid):
        raise ValueError("no payment history to fit")
    hats = [censored_mle(y, cens) if y.size else None for y, cens in zip(paid, opened, strict=True)]
    mu_pool = float(np.mean([h[0] for h in hats if h is not None]))
    dof = [y.size + cens.size - 1 for y, cens in zip(paid, opened, strict=True)]
    weighted = sum(d * h[1] ** 2 for d, h in zip(dof, hats, strict=True) if h is not None and d > 0)
    total = sum(d for d, h in zip(dof, hats, strict=True) if h is not None and d > 0)
    sigma_pool = math.sqrt(weighted / total) if total else SIGMA_FLOOR
    fits = tuple(
        _pool_one(c.id, y.size + cens.size, cens.size, h, mu_pool, sigma_pool, kappa)
        for c, y, cens, h in zip(customers, paid, opened, hats, strict=True)
    )
    return PoolFit(kappa=kappa, mu_pool=mu_pool, sigma_pool=sigma_pool, customers=fits)


def _pool_one(
    customer_id: str,
    n: int,
    n_open: int,
    hat: tuple[float, float] | None,
    mu_pool: float,
    sigma_pool: float,
    kappa: float,
) -> CustomerFit:
    mu_hat, sigma_hat = hat if hat is not None else (mu_pool, sigma_pool)
    w = n / (n + kappa) if hat is not None else 0.0
    return CustomerFit(
        customer_id=customer_id,
        n=n,
        n_open=n_open,
        mu_hat=mu_hat,
        sigma_hat=sigma_hat,
        weight=w,
        mu=w * mu_hat + (1 - w) * mu_pool,
        sigma=max(w * sigma_hat + (1 - w) * sigma_pool, SIGMA_FLOOR),
    )
