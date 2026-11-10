import itertools
from datetime import date, timedelta

import numpy as np
import pytest

from tempo.models import PaymentOption
from tempo.optimize.cash import breached, plan_outflow_cum
from tempo.optimize.milp import check_days, solve

AS_OF = date(2026, 11, 10)


def _opt(bill: str, kind: str, day: int, cents: int, value: int) -> PaymentOption:
    d = AS_OF + timedelta(days=day)
    return PaymentOption(bill, kind, "RTP", d, d, d, cents, value, False, 0, 0, 0, 0, 0, 0)


def _instance(seed: int, n_bills: int = 4, n_scen: int = 30, horizon: int = 20, cash: int = 9_000_000):
    """Random small instance: each bill has a due-date option (value 0) and earlier/later options."""
    rng = np.random.default_rng(seed)
    bills = []
    for i in range(n_bills):
        due = int(rng.integers(6, horizon - 2))
        amount = int(rng.integers(2_000_000, 6_000_000))
        opts = [_opt(f"b{i}", "BANK_DUE", due, amount, 0)]
        early = due - int(rng.integers(3, 6))
        opts.append(_opt(f"b{i}", "BANK_EARLY", early, int(amount * 0.98), int(amount * 0.015)))
        if rng.random() < 0.6:
            opts.append(_opt(f"b{i}", "CARD", min(horizon - 1, due + 8), amount, int(amount * 0.012)))
        bills.append(tuple(opts))
    inflow = rng.integers(0, 1_200_000, size=(n_scen, horizon)).cumsum(axis=1)
    fixed = np.zeros(horizon, dtype=np.int64)
    fixed[[5, 12]] = 3_000_000
    headroom = cash + inflow - fixed.cumsum()[None, :] - 1_000_000
    return tuple(bills), headroom.astype(np.int64)


def _breach_count(bills, choice, headroom) -> int:
    chosen = tuple(b[c] for b, c in zip(bills, choice, strict=True))
    return int(breached(headroom, plan_outflow_cum(chosen, AS_OF, headroom.shape[1])).sum())


def _brute_force(bills, headroom, k: int) -> float:
    best = -np.inf
    for choice in itertools.product(*[range(len(b)) for b in bills]):
        if _breach_count(bills, choice, headroom) <= k:
            best = max(best, sum(b[c].value_cents for b, c in zip(bills, choice, strict=True)) / 100)
    return best


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("k", [0, 3])
def test_optimizer_equals_brute_force_on_tiny_instances(seed: int, k: int) -> None:
    bills, headroom = _instance(seed, cash=15_000_000)  # the cash constraint binds at this level
    expected = _brute_force(bills, headroom, k)
    if expected == -np.inf:
        pytest.skip("instance infeasible without credit")

    result = solve(bills, headroom, AS_OF, k, credit_cost=1e6)

    assert result.objective_dollars == pytest.approx(expected, abs=0.01)
    assert result.credit_cum_cents.max() == 0


@pytest.mark.parametrize("seed", [10, 11, 12, 13, 14])
@pytest.mark.parametrize("k", [0, 2, 5])
def test_reduced_model_matches_full_model(seed: int, k: int) -> None:
    bills, headroom = _instance(seed, n_bills=6, n_scen=40, horizon=24, cash=20_000_000)

    full = solve(bills, headroom, AS_OF, k, reduced=False)
    reduced = solve(bills, headroom, AS_OF, k, reduced=True)

    assert reduced.objective_dollars == pytest.approx(full.objective_dollars, abs=0.02)
    assert reduced.stats.rows < full.stats.rows


@pytest.mark.parametrize("seed", range(20, 26))
def test_recounted_breaches_never_exceed_k(seed: int) -> None:
    bills, headroom = _instance(seed, n_bills=6, n_scen=60, horizon=24, cash=19_000_000)
    k = 4

    result = solve(bills, headroom, AS_OF, k)

    chosen = tuple(b[c] for b, c in zip(bills, result.choice, strict=True))
    plan_cum = plan_outflow_cum(chosen, AS_OF, headroom.shape[1])
    assert int(breached(headroom, plan_cum, result.credit_cum_cents).sum()) <= k


def test_backstop_credit_is_zero_when_cash_is_ample() -> None:
    bills, headroom = _instance(30, cash=500_000_000)

    result = solve(bills, headroom, AS_OF, 2)

    assert result.credit_cum_cents.max() == 0


def test_backstop_credit_is_positive_when_cash_is_impossible() -> None:
    bills, headroom = _instance(31, cash=-20_000_000)

    result = solve(bills, headroom, AS_OF, 2)

    assert result.credit_cum_cents.max() > 0
    chosen = tuple(b[c] for b, c in zip(bills, result.choice, strict=True))
    plan_cum = plan_outflow_cum(chosen, AS_OF, headroom.shape[1])
    assert int(breached(headroom, plan_cum, result.credit_cum_cents).sum()) <= 2


def test_ample_cash_takes_every_best_option() -> None:
    bills, headroom = _instance(32, cash=500_000_000)

    result = solve(bills, headroom, AS_OF, 0)

    best = tuple(int(np.argmax([o.value_cents for o in b])) for b in bills)
    assert result.choice == best


def test_check_days_include_drops_and_option_days() -> None:
    headroom = np.array([[5, 6, 4, 4, 7], [5, 5, 5, 3, 9]])

    days = check_days(headroom, np.array([1]))

    assert days.tolist() == [0, 1, 2, 3]


def test_backstop_credit_is_never_used_to_buy_value() -> None:
    # Paying early needs $1 more than the cash allows; it would earn $500. Paying on the due date fits.
    # A priced backstop alone would draw $1 of credit to take the discount; the lexicographic solve must not.
    bill = (_opt("b0", "BANK_DUE", 10, 1_000_000, 0), _opt("b0", "BANK_EARLY", 3, 980_000, 50_000))
    headroom = np.full((3, 20), 5_000_000, dtype=np.int64)
    headroom[:, 3:10] = 979_900

    result = solve((bill,), headroom, AS_OF, 0, credit_cost=0.5)

    assert result.credit_cum_cents.max() == 0
    assert result.choice == (0,)
