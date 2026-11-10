from functools import cache

import pytest

from tempo.agent.negotiation import (
    candidate_bills,
    draft_email,
    parse_reply,
    plan_offers,
    price,
    verify_offer,
)
from tempo.agent.number_guard import numbers_in
from tempo.data.store import load_dataset
from tempo.economics import break_even_discount
from tempo.llm.cached_provider import CachedProvider
from tempo.optimize.engine import solve_plan
from tempo.optimize.run import prepare
from tempo.pipeline import ingest


@cache
def _setup():
    ds = load_dataset("demo")
    inputs = prepare(ds, ingest(ds, CachedProvider()))
    base = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 4)
    return inputs, base


def test_offer_is_break_even_plus_margin_rounded_up_to_a_quarter_point() -> None:
    d_star, offer_bps = price(0.08, 30)

    assert d_star == pytest.approx(break_even_discount(0.08, 30))
    assert offer_bps == 100  # 0.6532% + 0.25% = 0.9032% -> 1.00%
    assert offer_bps % 25 == 0


@pytest.mark.slow
def test_offer_verification_resolve_takes_a_generous_offer_and_refuses_a_token_one() -> None:
    inputs, base = _setup()
    top = plan_offers(inputs, base, 0.10)[0]
    index = next(i for i, b in enumerate(inputs.bills) if b.id == top.bill_id)
    assert index in candidate_bills(inputs.bills, inputs.as_of).values()

    takes_big, delta_big, _ = verify_offer(inputs, base, index, 400)
    takes_tiny, delta_tiny, _ = verify_offer(inputs, base, index, 1)

    assert takes_big and delta_big > 0
    gap_tolerance = max(1_000, abs(base.objective_cents()) * 2e-4)  # the solver stops within a 0.01% gap
    assert not takes_tiny and abs(delta_tiny) <= gap_tolerance


@pytest.mark.slow
def test_ranked_offers_put_verified_takers_first_and_emails_carry_only_code_numbers() -> None:
    inputs, base = _setup()

    offers = plan_offers(inputs, base, 0.10)

    takers = [o.tempo_takes_it for o in offers]
    assert takers == sorted(takers, reverse=True)
    text, _ = draft_email(None, offers[0])
    assert str(offers[0].offer_bps / 100).rstrip("0").rstrip(".") + "%" in text.body
    supplied = {n for v in (offers[0].invoice_number, str(offers[0].offer_bps / 100)) for n in numbers_in(v)}
    assert supplied & numbers_in(text.body)


def test_vendor_replies_are_parsed_but_never_auto_applied() -> None:
    inputs, base = _setup()
    offer = plan_offers(inputs, base, 0.10)[0]

    accept = parse_reply(None, offer, "accept")
    counter = parse_reply(None, offer, "counter")
    unclear = parse_reply(None, offer, "ambiguous")

    assert accept["terms"]["discount_bps"] == offer.offer_bps and accept["needs_human_accept"]
    assert counter["terms"]["discount_bps"] == 50
    assert unclear["terms"] is None
