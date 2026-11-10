from dataclasses import replace
from datetime import date

import numpy as np

from tempo.assumptions import EPSILON
from tempo.data.store import load_dataset
from tempo.llm.cached_provider import CachedProvider
from tempo.models import TermsRecord
from tempo.optimize.cash_value import marginal_value_of_cash
from tempo.optimize.engine import solve_plan
from tempo.optimize.explain import ExplainContext, explain_all, ordinal
from tempo.optimize.options import PlannableBill, RailContext, build_options
from tempo.optimize.run import prepare
from tempo.pipeline import ingest

AS_OF = date(2026, 11, 10)


def _bill(discount_bps: int, net: int = 30) -> PlannableBill:
    terms = TermsRecord(discount_bps, 10, net, "invoice_date")
    return PlannableBill(
        "b1",
        "v1",
        "Vendor",
        "INV-1",
        date(2026, 11, 9),
        1_000_000,
        0,
        0,
        1_000_000,
        terms,
        date(2026, 12, 9),
        date(2026, 11, 19),
        None,
        False,
        0,
        False,
        True,
        False,
        True,
        "verified",
    )


def test_tiny_discount_is_skipped_for_economic_reasons() -> None:
    # 0.1% for paying 20 days early returns about 1.8%/yr, less than the 4% yield on cash: never worth it.
    bill = _bill(10)
    options = (build_options(bill, RailContext(AS_OF)),)
    headroom = np.full((5, 91), 10_000_000_00, dtype=np.int64)
    plan = solve_plan((bill,), options, headroom, AS_OF, 0)

    (decision,) = explain_all(ExplainContext(plan, headroom, AS_OF, 50_000_00, EPSILON, 0.08, ()))

    assert decision.option_kind == "BANK_DUE"
    assert "worth less" in decision.reason
    assert decision.binding_day is None


def test_taken_discount_explains_dollars_and_return_on_cash() -> None:
    bill = _bill(200)
    options = (build_options(bill, RailContext(AS_OF)),)
    headroom = np.full((5, 91), 10_000_000_00, dtype=np.int64)
    plan = solve_plan((bill,), options, headroom, AS_OF, 0)

    (decision,) = explain_all(ExplainContext(plan, headroom, AS_OF, 50_000_00, EPSILON, 0.08, ()))

    assert decision.option_kind == "BANK_EARLY"
    assert "saves $200" in decision.reason
    assert "/yr return on the cash" in decision.reason


def test_demo_plan_reasons_name_the_binding_day_when_cash_binds() -> None:
    ds = load_dataset("demo")
    inputs = prepare(ds, ingest(ds, CachedProvider()))
    plan = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 4)
    ctx = ExplainContext(
        plan, inputs.headroom_a, inputs.as_of, ds.company.buffer_cents, EPSILON, 0.09, ds.fixed_outflows
    )

    decisions = explain_all(ctx)

    assert all(d.reason for d in decisions)
    bound = [d for d in decisions if d.binding_day is not None]
    assert bound, "a tight demo plan should skip at least one discount because cash binds"
    assert all("skipped because paying early" in d.reason for d in bound)


def test_cash_value_is_small_when_cash_is_ample_and_credit_bound_when_impossible() -> None:
    ds = load_dataset("demo")
    inputs = prepare(ds, ingest(ds, CachedProvider()))
    ample = replace(inputs, headroom_a_fallback=inputs.headroom_a_fallback + 50_000_000_00)
    broke = replace(inputs, headroom_a_fallback=inputs.headroom_a_fallback - 50_000_000_00)
    plan = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 4)

    rich = marginal_value_of_cash(ample, plan)
    poor = marginal_value_of_cash(broke, plan)

    assert rich.lam < 1e-3 and not rich.credit_bound
    assert poor.credit_bound


def test_ordinals() -> None:
    assert [ordinal(n) for n in (1, 2, 3, 4, 10, 11, 12, 13, 21, 22)] == [
        "1st",
        "2nd",
        "3rd",
        "4th",
        "10th",
        "11th",
        "12th",
        "13th",
        "21st",
        "22nd",
    ]


def test_no_option_is_sent_before_the_invoice_exists() -> None:
    from dataclasses import replace as dc_replace

    bill = dc_replace(
        _bill(200),
        issued_at=date(2026, 11, 20),
        due_date=date(2026, 12, 20),
        discount_deadline=date(2026, 11, 30),
    )

    options = build_options(bill, RailContext(AS_OF))

    assert all(o.send_date >= bill.issued_at for o in options)
