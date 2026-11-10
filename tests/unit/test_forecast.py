import math
from datetime import date, timedelta

import numpy as np
import pytest

from tempo.forecast.fit import fit_days_to_pay
from tempo.forecast.simulate import Receipt, WhatIf, simulate
from tempo.models import Customer, PaymentRecord, Receivable

HORIZON = 91


def _customer(cid: str, days: list[int]) -> Customer:
    start = date(2026, 1, 5)
    history = tuple(
        PaymentRecord(start + timedelta(days=7 * i), start + timedelta(days=7 * i + d), 100_00)
        for i, d in enumerate(days)
    )
    return Customer(
        id=cid, name=cid, segment="prompt", history=history, open_receivables=(), scheduled_billings=()
    )


def _receipts(n: int = 40, offset: int = 0) -> tuple[Receipt, ...]:
    return tuple(Receipt(f"r{i}", "c1", offset - (i % 5), 1_000_000) for i in range(n))


def test_pooling_weight_and_formula() -> None:
    a = _customer("a", [30, 32, 28, 31, 29, 30])
    b = _customer("b", [60, 70])

    fit = fit_days_to_pay((a, b), kappa=5.0)

    fb = next(c for c in fit.customers if c.customer_id == "b")
    assert fb.weight == pytest.approx(2 / 7)
    assert fb.mu == pytest.approx(fb.weight * fb.mu_hat + (1 - fb.weight) * fit.mu_pool)
    assert fb.sigma == pytest.approx(fb.weight * fb.sigma_hat + (1 - fb.weight) * fit.sigma_pool)


def test_sigma_pool_uses_within_customer_spread_only() -> None:
    # Two perfectly consistent customers far apart: within spread is zero, between spread is large.
    a = _customer("a", [20] * 8)
    b = _customer("b", [80] * 8)

    fit = fit_days_to_pay((a, b))

    assert fit.sigma_pool == pytest.approx(0.0, abs=1e-2)
    assert fit.mu_pool == pytest.approx((math.log(20) + math.log(80)) / 2)


def test_simulation_is_deterministic_for_a_seed() -> None:
    params = {"c1": (math.log(30), 0.3)}

    s1 = simulate(_receipts(), params, HORIZON, n=50, seed=7)
    s2 = simulate(_receipts(), params, HORIZON, n=50, seed=7)

    assert np.array_equal(s1.inflows, s2.inflows)


def test_forecast_quantiles_are_ordered() -> None:
    params = {"c1": (math.log(30), 0.4)}
    cum = simulate(_receipts(), params, HORIZON, n=500, seed=1).inflow_cum()

    p10, p50, p90 = np.percentile(cum, [10, 50, 90], axis=0)

    assert np.all(p10 <= p50) and np.all(p50 <= p90)
    assert np.any(p10 < p90)


def test_common_factor_widens_the_fan() -> None:
    params = {"c1": (math.log(30), 0.3)}
    receipts = _receipts(n=60)

    with_factor = simulate(receipts, params, HORIZON, n=2000, seed=3, sigma_macro=0.25).inflow_cum()
    independent = simulate(receipts, params, HORIZON, n=2000, seed=3, sigma_macro=0.0).inflow_cum()

    day = 35
    spread = lambda cum: np.percentile(cum[:, day], 90) - np.percentile(cum[:, day], 10)  # noqa: E731
    assert spread(with_factor) > 1.5 * spread(independent)


def test_truncated_sampling_respects_elapsed_days() -> None:
    # Invoices outstanding 40 days for a customer that usually pays in ~20 days: every simulated payment
    # must land on or after the as-of date (day >= 0), none in the past.
    params = {"c1": (math.log(20), 0.3)}
    receipts = tuple(Receipt(f"r{i}", "c1", -40, 1_000_00) for i in range(30))

    sims = simulate(receipts, params, HORIZON, n=400, seed=5, p_no_pay=0.0)

    paid = sims.inflows.sum(axis=1)
    assert np.all(paid == 30 * 1_000_00)  # every invoice paid inside the horizon, none dropped as "past"


def test_customer_delay_shifts_inflows_later() -> None:
    params = {"c1": (math.log(30), 0.2)}
    base = simulate(_receipts(), params, HORIZON, n=200, seed=9)
    delayed = simulate(_receipts(), params, HORIZON, n=200, seed=9, what_if=WhatIf("c1", 14))

    assert delayed.inflow_cum()[:, 40].mean() < base.inflow_cum()[:, 40].mean()


def _censored_customer(rng: np.random.Generator, mu: float, sigma: float, as_of: date) -> Customer:
    history, open_items = [], []
    for k in range(40):
        issued = as_of - timedelta(days=5 + 3 * k)
        days = max(1, round(math.exp(mu + sigma * rng.standard_normal())))
        if issued + timedelta(days=days) < as_of:
            history.append(PaymentRecord(issued, issued + timedelta(days=days), 100_00))
        else:
            open_items.append(Receivable(f"r{k}", "c", issued, 100_00))
    return Customer("c", "c", "slow", tuple(history), tuple(open_items), ())


def test_censored_fit_corrects_the_early_bias_of_paid_only_history() -> None:
    """Invoices still open at the as-of date are slow payers; dropping them biases mu low. Averaged over
    replicates so the test measures bias, not one draw's noise."""
    rng = np.random.default_rng(0)
    true_mu, true_sigma = math.log(45), 0.4
    as_of = date(2026, 11, 10)
    naive, censored = [], []
    for _ in range(100):
        c = _censored_customer(rng, true_mu, true_sigma, as_of)
        naive.append(fit_days_to_pay((c,), None, kappa=0.0).customers[0].mu)
        censored.append(fit_days_to_pay((c,), as_of, kappa=0.0).customers[0].mu)

    naive_bias = float(np.mean(naive)) - true_mu
    censored_bias = float(np.mean(censored)) - true_mu
    assert naive_bias < -0.03
    assert abs(censored_bias) < abs(naive_bias) / 2
