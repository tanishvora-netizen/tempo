"""Final fix pass, items 3 and 4: financing before late, FLEX_LIMIT, monotone stress, and the tradeoff box."""

from datetime import date, timedelta
from functools import cache

import numpy as np
import pytest

from tempo.assumptions import (
    FINANCE_FEE_PER_30_DAYS,
    FINANCE_TERM_DAYS,
    LATE_RELATIONSHIP_PENALTY,
    SEED_C,
)
from tempo.data.store import load_dataset
from tempo.forecast.simulate import WhatIf
from tempo.llm.cached_provider import CachedProvider
from tempo.models import PaymentOption
from tempo.optimize.capacity import capacity_groups, flat_options, within_capacity
from tempo.optimize.engine import solve_plan
from tempo.optimize.evaluate import evaluate
from tempo.optimize.options import RailContext, build_options
from tempo.optimize.run import prepare
from tempo.pipeline import ingest, plannable_bills
from tempo.precompute import top_customers
from tempo.whatif import FINANCE_KINDS, drop_kinds, tradeoff

DELAYS = (0, 7, 14, 30)
N_CHECK = 2_000


@cache
def _demo():
    ds = load_dataset("demo")
    return ds, ingest(ds, CachedProvider())


def test_late_costs_more_than_financing_by_assumption() -> None:
    assert LATE_RELATIONSHIP_PENALTY > FINANCE_FEE_PER_30_DAYS * FINANCE_TERM_DAYS / 30


def test_finance_on_due_date_beats_late_for_every_bill() -> None:
    ds, ing = _demo()
    ctx = RailContext(ds.company.as_of, ds.company.funding_account, finance_enabled=True)
    for bill in plannable_bills(ds, ing):
        opts = {o.kind: o for o in build_options(bill, ctx)}
        fin, late = opts["FINANCE_DUE"], opts["LATE"]
        assert fin.value_cents > late.value_cents
        assert fin.cash_out_date >= late.cash_out_date  # financing also moves cash at least as late
        assert fin.arrival_date <= bill.due_date or fin.arrival_date <= late.arrival_date


def test_no_finance_options_when_financing_is_off() -> None:
    ds, ing = _demo()
    ctx = RailContext(ds.company.as_of, ds.company.funding_account, finance_enabled=False)
    for bill in plannable_bills(ds, ing):
        assert all(o.kind not in FINANCE_KINDS for o in build_options(bill, ctx))


def _outstanding_by_day(chosen: list[PaymentOption]) -> dict[date, int]:
    days: dict[date, int] = {}
    for o in chosen:
        for i in range(FINANCE_TERM_DAYS):
            d = o.send_date + timedelta(days=i)
            days[d] = days.get(d, 0) + o.cash_out_cents
    return days


def test_flex_limit_caps_outstanding_on_every_day() -> None:
    ds, ing = _demo()
    ctx = RailContext(ds.company.as_of, ds.company.funding_account, finance_enabled=True)
    options = tuple(build_options(b, ctx) for b in plannable_bills(ds, ing))
    flat = flat_options(options)
    finance = [j for j, o in enumerate(flat) if o.rail == "FINANCE"]
    rng = np.random.default_rng(7)
    cap = 40_000_000
    groups = tuple(g for g in capacity_groups(options, finance_limit_cents=cap) if g[1] == cap)
    for _ in range(200):
        chosen = set(rng.choice(finance, size=rng.integers(1, 12), replace=False).tolist())
        peak = max(_outstanding_by_day([flat[j] for j in chosen]).values())
        assert within_capacity(chosen, flat, groups) == (peak <= cap)


@pytest.mark.slow
def test_delaying_a_customer_never_lowers_the_breach_rate_of_a_fixed_plan() -> None:
    ds, ing = _demo()
    base = prepare(ds, ing)
    plan = solve_plan(base.bills, base.options, base.headroom_a, base.as_of, 10)
    buffer = ds.company.buffer_cents
    for cid, _ in top_customers(ds):
        prev = None
        for days in DELAYS:
            fc = prepare(ds, ing, WhatIf(cid, days) if days else None).forecast
            head = fc.headroom(fc.scenarios(N_CHECK, SEED_C))
            breached = plan.breaches(head, base.as_of)
            if prev is not None:
                assert np.all(breached >= prev), (cid, days)  # scenario by scenario, not just on average
            prev = breached
        assert evaluate(plan, head, base.as_of, buffer).breach_rate >= 0


@pytest.mark.slow
def test_tradeoff_variants_use_only_their_lever() -> None:
    ds, ing = _demo()
    cid, _ = top_customers(ds)[0]
    inputs = prepare(ds, ing, WhatIf(cid, 30), finance_enabled=True)
    base = prepare(ds, ing)
    current = solve_plan(base.bills, base.options, base.headroom_a, base.as_of, 10)
    plan = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 10)
    head_eval = inputs.headroom_b[:N_CHECK]
    res = evaluate(plan, head_eval, inputs.as_of, ds.company.buffer_cents)

    box = tradeoff(plan, res, current, inputs.headroom_a, head_eval, inputs.as_of, ds.company.buffer_cents)

    assert box["financing"]["late_count"] == 0
    assert box["late_only"]["financed_count"] == 0
    assert 0 <= box["accept_risk"]["breach_rate"] <= 1
    assert box["accept_risk"]["breach_rate"] >= res.breach_rate - 0.02  # re-planning should not be much worse
    assert all(o.kind != "LATE" for opts in drop_kinds(inputs.options, ("LATE",)) for o in opts)
