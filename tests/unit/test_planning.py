"""Planning-level tests on the committed demo and ample datasets (no Ollama, no network)."""

import json
from functools import cache

import numpy as np
import pytest

from tempo.assumptions import EPSILON, N_EVAL_SCENARIOS, SEED_C
from tempo.data.store import load_dataset
from tempo.llm.cached_provider import CachedProvider
from tempo.optimize import certify as certify_mod
from tempo.optimize.certify import certify
from tempo.optimize.engine import solve_plan
from tempo.optimize.run import baseline_plans, evaluate_all, prepare, run_tempo
from tempo.pipeline import ingest
from tempo.precompute import OUT_DIR, input_hash


@cache
def _demo_inputs():
    ds = load_dataset("demo")
    return prepare(ds, ingest(ds, CachedProvider()))


@pytest.mark.slow
def test_tension_on_the_demo_seed() -> None:
    """Directive section 6, with the thresholds actually used (docs/DECISIONS.md: the final sweep found no
    starting cash with greedy >= 15% and pay_on_due <= 2%, so the pre-registered fallback stands): on seed C,
    pay_on_due <= 2%, greedy_discount is unsafe (> EPSILON), and Tempo passes certification while keeping
    at least 60% of greedy's value."""
    inputs = _demo_inputs()
    tempo, cert = run_tempo(inputs)
    plans = {**baseline_plans(inputs), "tempo": tempo}
    head_c = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C))

    res = evaluate_all(plans, head_c, inputs)

    assert res["pay_on_due"].breach_rate <= 0.02
    assert res["greedy_discount"].breach_rate > EPSILON
    assert cert.passed
    assert res["tempo"].breach_upper <= EPSILON
    assert res["tempo"].value_cents >= 0.6 * res["greedy_discount"].value_cents


@pytest.mark.slow
def test_same_inputs_give_the_same_plan_hash() -> None:
    inputs = _demo_inputs()

    a = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 4)
    b = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, 4)

    assert a.plan_hash() == b.plan_hash()


@pytest.mark.slow
def test_ample_regime_takes_every_positive_value_option() -> None:
    ds = load_dataset("ample")
    inputs = prepare(ds, ingest(ds, CachedProvider()))

    plan, _ = run_tempo(inputs)

    for opts, c in zip(plan.options, plan.choice, strict=True):
        best = max(o.value_cents for o in opts)
        assert opts[c].value_cents == best


@pytest.mark.slow
def test_in_sample_breaches_recounted_from_payments_never_exceed_k() -> None:
    inputs = _demo_inputs()
    for k in (4, 2, 0):
        plan = solve_plan(inputs.bills, inputs.options, inputs.headroom_a, inputs.as_of, k)

        assert int(plan.breaches(inputs.headroom_a, inputs.as_of).sum()) <= k


def test_certification_lowers_k_when_the_out_of_sample_bound_fails() -> None:
    """Make seed B so harsh that every plan fails: the ladder must walk K all the way down, then fall back."""
    inputs = _demo_inputs()
    harsh_b = inputs.headroom_b - 2_000_000_00  # $2M less cash in every certification scenario

    plan, cert = certify(
        inputs.bills, inputs.options, inputs.headroom_a, harsh_b, inputs.as_of, inputs.headroom_a_fallback
    )

    assert [s.k for s in cert.steps] == [*certify_mod.K_LADDER, certify_mod.FALLBACK_K]
    assert not cert.passed
    assert plan is not None


def test_certification_stops_at_the_first_pass() -> None:
    inputs = _demo_inputs()
    easy_b = inputs.headroom_b + 5_000_000_00

    _, cert = certify(inputs.bills, inputs.options, inputs.headroom_a, easy_b, inputs.as_of)

    assert len(cert.steps) == 1 and cert.passed


def test_committed_precomputed_hash_matches_current_inputs() -> None:
    bundle = json.loads((OUT_DIR / "bundle.json").read_text())

    assert bundle["input_hash"] == input_hash("demo"), "inputs changed: run `make precompute` and commit"


def test_backstop_fan_is_ordered() -> None:
    bundle = json.loads((OUT_DIR / "bundle.json").read_text())
    after = bundle["fan"]["after"]

    assert np.all(np.array(after["p10"]) <= np.array(after["p50"]))
    assert np.all(np.array(after["p50"]) <= np.array(after["p90"]))
