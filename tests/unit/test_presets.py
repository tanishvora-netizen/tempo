"""Section B of the final fix pass: the committed precomputed presets must be internally consistent and honest.

These read data/precomputed/*.json (what the hosted demo serves) and fail on any NaN, missing section, or
disagreement between the diff table, the tradeoff box, the KPIs, and the fan.
"""

import json
import math
import re
from datetime import date
from itertools import pairwise

import pytest

from tempo.precompute import DELAY_PRESETS, OUT_DIR

MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
DATE_IN_TEXT = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2})\b")
SOLVER_GAP = 1e-4
COUNT_KEYS = (
    "late_count",
    "arrive_after_due_count",
    "discounts_captured_count",
    "card_count",
    "financed_count",
)


def _load(name: str) -> dict:
    return json.loads((OUT_DIR / f"{name}.json").read_text())


BUNDLE = _load("bundle")
WHATIFS = _load("whatifs")
PRESETS = WHATIFS["presets"]


def _walk(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, x


NULLABLE = (
    "credit_first_date",
    "worst_shortfall_date",
    "mip_gap",
    "binding_day",
    "customer_id",
    "discount_deadline",
)


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_preset_has_no_nan_none_or_negative_counts(preset: dict) -> None:
    for path, v in _walk({k: preset[k] for k in ("kpis", "certification", "fan", "tradeoff", "solver")}):
        if isinstance(v, float):
            assert math.isfinite(v), path
        if v is None:
            assert path.split(".")[-1] in NULLABLE, path
    for key in COUNT_KEYS:
        assert preset["kpis"][key] >= 0, key


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_preset_sections_are_present_and_nonempty(preset: dict) -> None:
    for key in ("kpis", "certification", "fan", "tradeoff", "plan_hash", "label", "what_if"):
        assert preset.get(key), key
    assert isinstance(preset["diff"], list)
    assert len(preset["fan"]["after"]["p50"]) == BUNDLE["company"]["horizon_days"]
    assert len(preset["fan"]["low_paths"]) == 5


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_preset_is_certified_and_reports_seed_c(preset: dict) -> None:
    c = preset["certification"]
    assert isinstance(c["passed"], bool)
    assert c["reported"]["n"] == 10_000
    assert 0 <= c["reported"]["rate"] <= c["reported"]["upper"] <= 1
    assert preset["kpis"]["breach_rate"] == c["reported"]["rate"]


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_diff_tradeoff_kpis_and_fan_agree(preset: dict) -> None:
    k, t = preset["kpis"], preset["tradeoff"]
    base_late = BUNDLE["kpis"]["late_count"]
    late_in_diff = sum(d["after"]["option"] == "LATE" for d in preset["diff"])
    left_late = sum(d["before"] and d["before"]["option"] == "LATE" for d in preset["diff"])
    assert k["late_count"] == base_late - left_late + late_in_diff
    if k["late_count"] == 0:  # the what-if plan is itself the financing-only variant
        assert t["financing"]["value_cents"] == k["value_vs_pay_on_due_cents"]
        assert t["financing"]["breach_rate"] == k["breach_rate"]
    if k["financed_count"] == 0:  # ... or the late-only variant
        assert t["late_only"]["value_cents"] == k["value_vs_pay_on_due_cents"]
    assert t["n"] == preset["certification"]["reported"]["n"]
    lowest = min(p["min_cents"] for p in preset["fan"]["low_paths"])
    assert lowest <= k["worst_p10_balance_cents"]
    for p in preset["fan"]["low_paths"]:
        assert min(p["path"]) == p["min_cents"]


def _month_days(text: str) -> set[tuple[int, int]]:
    """Dates mentioned in a reason sentence, as (month, day): reasons print "Nov 27" without a year."""
    return {(MONTHS[mon], int(day)) for mon, day in DATE_IN_TEXT.findall(text)}


def test_every_reason_uses_the_dates_of_its_row() -> None:
    for b in BUNDLE["bills"]:
        fields = (
            b["send_date"],
            b["arrival_date"],
            b["cash_out_date"],
            b["due_date"],
            b["discount_deadline"],
            b["binding_day"],
        )
        allowed = {(date.fromisoformat(d).month, date.fromisoformat(d).day) for d in fields if d}
        allowed |= {
            (date.fromisoformat(f["date"]).month, date.fromisoformat(f["date"]).day)
            for f in BUNDLE["fixed_outflows"]
        }
        assert _month_days(b["reason"]) <= allowed, (b["bill_id"], b["reason"])


def _by_customer() -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {}
    for p in PRESETS:
        w = p["what_if"]
        if w["customer_id"]:
            out.setdefault(w["customer_id"], {})[w["delay_days"]] = p
    return out


@pytest.mark.parametrize("customer", sorted(_by_customer()))
def test_fixed_current_plan_never_gets_safer_when_a_customer_pays_later(customer: str) -> None:
    by_delay = _by_customer()[customer]
    rates = [BUNDLE["kpis"]["breach_rate"]] + [
        by_delay[d]["tradeoff"]["accept_risk"]["breach_rate"] for d in DELAY_PRESETS
    ]
    assert rates == sorted(rates), rates


@pytest.mark.parametrize("customer", sorted(_by_customer()))
def test_value_does_not_rise_as_the_delay_grows(customer: str) -> None:
    by_delay = _by_customer()[customer]
    values = [by_delay[d]["kpis"]["value_vs_pay_on_due_cents"] for d in DELAY_PRESETS]
    for a, b in pairwise(values):
        assert b <= a + abs(a) * SOLVER_GAP + 100, (
            values
        )  # tolerance: the solver gap, plus one dollar of rounding


@pytest.mark.slow
def test_a_preset_rerun_live_gives_the_committed_plan_hash() -> None:
    from app.state import load_state
    from tempo.forecast.simulate import WhatIf

    k_base = BUNDLE["certification"]["k"]
    preset = next(
        p
        for p in PRESETS
        if p["what_if"]["customer_id"] and p["certification"]["k"] == k_base and p["certification"]["passed"]
    )
    w = preset["what_if"]
    s = load_state()

    live = s.solve_live(WhatIf(w["customer_id"], w["delay_days"], w["shock_cents"]), {})

    assert live.payload["plan_hash"] == preset["plan_hash"]


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_every_preset_is_solved_to_the_gap(preset: dict) -> None:
    assert preset["solver"]["status"] == "optimal", preset["solver"]
