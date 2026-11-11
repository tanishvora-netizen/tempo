"""Precompute everything the UI shows, keyed by an input hash, so the hosted demo never waits on a solve.

Writes data/precomputed/{bundle,proof,whatifs,review_effects}.json. The host only loads these files; on a
hash mismatch it serves them anyway with a visible "results from build <hash>" banner.
"""

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

from tempo.agent.negotiation import plan_offers
from tempo.assumptions import EPSILON, N_EVAL_SCENARIOS, N_FAN_SCENARIOS, SEED, SEED_C, SEED_FAN
from tempo.extract.eval import evaluate_extraction
from tempo.extract.reconcile import Reconciled, sanity_problem
from tempo.forecast.simulate import WhatIf
from tempo.models import Dataset, Decision, TermsRecord
from tempo.optimize import baselines as bl
from tempo.optimize.cash import slack
from tempo.optimize.cash_value import CashValue, marginal_value_of_cash
from tempo.optimize.certify import Certification, certify, ladder_for, z_for
from tempo.optimize.engine import Plan, true_params
from tempo.optimize.evaluate import balance_fan, evaluate
from tempo.optimize.explain import ExplainContext, explain_all
from tempo.optimize.run import (
    POLICY_ORDER,
    RunInputs,
    ablation_plans,
    baseline_plans,
    evaluate_all,
    prepare,
    run_tempo,
)
from tempo.pipeline import IngestResult
from tempo.report import (
    bill_rows,
    cash_value_view,
    certification_view,
    diff_plans,
    kpis,
    policy_view,
)
from tempo.whatif import tradeoff

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "data" / "precomputed"
DELAY_PRESETS = (7, 14, 30)
SHOCK_PRESETS_CENTS = (10_000_000, 25_000_000)
TOP_CUSTOMERS = 3
MARKER_COUNT = 8
# Offline solves get far more time than the 10 s live safety net, so every committed preset is solved to the
# 0.01% gap (the solver status is in each preset's "solver" block and a test checks it).
PRECOMPUTE_TIME_LIMIT_S = 120.0
LOW_PATHS = 5  # seed-C scenarios drawn on the fan: the ones whose lowest balance is lowest
FRONTIER_EPSILONS = (0.01, 0.025, 0.05, 0.075, 0.10)
FRONTIER_BASELINES = ("weekly_run", "greedy_discount", "greedy_p05", "pay_on_due")


def input_hash(regime: str = "demo") -> str:
    """sha256 over the committed dataset, assumptions.py, the extraction cache entry names (each name is the hash
    of its prompt, schema, and document), and the seed. Offer drafts and reply parses do not change the plan, so
    they are not part of the hash."""
    h = hashlib.sha256()
    for path in (REPO / "data" / regime / "dataset.json", REPO / "tempo" / "assumptions.py"):
        h.update(path.read_bytes())
    for path in sorted((REPO / "data" / "cache" / "extract").glob("*.json")):
        h.update(path.name.encode())
    h.update(str(SEED).encode())
    return h.hexdigest()[:16]


def pay_on_due_plan(inputs: RunInputs) -> Plan:
    return bl.pay_on_due(inputs.bills, inputs.options, inputs.horizon)


STRESS_SIGMA_MACRO = 0.30  # twice the assumed common factor (council C4, quant)


def macro_stress(base: "Solved", plans: dict[str, Plan]) -> dict:
    """Every policy on seed C with the common timing factor doubled: tests the SIGMA_MACRO assumption."""
    scen = base.inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C, sigma_macro=STRESS_SIGMA_MACRO)
    res = evaluate_all(plans, base.inputs.forecast.headroom(scen), base.inputs)
    return {"sigma_macro": STRESS_SIGMA_MACRO, "policies": [policy_view(res[p]) for p in POLICY_ORDER]}


_FINANCING_CASES: dict[int, "Solved"] = {}


def financing_case(dataset: Dataset, ingest_result: IngestResult) -> "Solved":
    """Tempo with the Flex-style options on (assumed fee, FLEX_LIMIT), certified exactly like the headline.
    Solved once per run and shared by the Overview toggle (bundle) and the Proof sensitivity row."""
    key = id(dataset)
    if key not in _FINANCING_CASES:
        _FINANCING_CASES[key] = solve_case(dataset, ingest_result, finance_enabled=True)
    return _FINANCING_CASES[key]


def financed_totals(plan: Plan) -> dict:
    financed = [o for o in plan.chosen() if o.rail == "FINANCE"]
    return {"financed_count": len(financed), "financed_cents": sum(o.cash_out_cents for o in financed)}


def financing_sensitivity(dataset: Dataset, ingest_result: IngestResult) -> dict:
    """The financing plan on seed C, as a row beside the headline policies."""
    s = financing_case(dataset, ingest_result)
    res = evaluate(s.plan, s.headroom_c, s.inputs.as_of, dataset.company.buffer_cents)
    return {
        **policy_view(res),
        "policy": "tempo_with_financing",
        "certified": s.cert.passed,
        **financed_totals(s.plan),
    }


def financing_view(dataset: Dataset, ingest_result: IngestResult) -> dict:
    """What the Overview toggle "With Flex-style financing" switches to: KPIs, certification, and fan."""
    s = financing_case(dataset, ingest_result)
    return {
        **plan_summary(s, pay_on_due_plan(s.inputs)),
        **financed_totals(s.plan),
        "markers": markers(s.plan),
        "label": "With Flex-style financing (fee is an assumption)",
    }


@dataclass(frozen=True)
class Solved:
    """A certified Tempo plan with everything needed to show it."""

    inputs: RunInputs
    plan: Plan
    cert: Certification
    cash_value: CashValue
    headroom_c: np.ndarray
    fan_headroom: np.ndarray
    seconds: float


def solve_case(
    dataset: Dataset,
    ingest_result: IngestResult,
    what_if: WhatIf | None = None,
    overrides: dict[str, TermsRecord] | None = None,
    finance_enabled: bool = False,
) -> Solved:
    """Prepare, certify, value cash, and draw the reporting (C) and fan scenarios for one case."""
    started = time.perf_counter()
    inputs = prepare(dataset, ingest_result, what_if, overrides, finance_enabled=finance_enabled)
    plan, cert = run_tempo(inputs, time_limit=PRECOMPUTE_TIME_LIMIT_S)
    cv = marginal_value_of_cash(inputs, plan)
    head_c = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C))
    fan = inputs.forecast.headroom(inputs.forecast.scenarios(N_FAN_SCENARIOS, SEED_FAN))
    return Solved(inputs, plan, cert, cv, head_c, fan, time.perf_counter() - started)


def low_paths(plan: Plan, headroom: np.ndarray, as_of, buffer_cents: int, n: int = LOW_PATHS) -> list[dict]:
    """End-of-day balance of the n scenarios whose lowest balance is lowest (risk made visible on the fan)."""
    s = slack(headroom, plan.outflow_cum(as_of, headroom.shape[1]), plan.credit_cum_cents) + buffer_cents
    lows = s.min(axis=1)
    order = np.argsort(lows, kind="stable")[:n]
    return [
        {
            "scenario": int(i),
            "min_cents": round(float(lows[i])),
            "min_date": (as_of + timedelta(days=int(np.argmin(s[i])))).isoformat(),
            "path": [round(float(x)) for x in s[i]],
        }
        for i in order
    ]


def decisions_for(s: Solved) -> tuple[Decision, ...]:
    ds = s.inputs.dataset
    n = s.plan.n_scenarios or s.inputs.headroom_a.shape[0]
    ctx = ExplainContext(
        s.plan,
        s.inputs.headroom_a_fallback[:n],
        ds.company.as_of,
        ds.company.buffer_cents,
        EPSILON,
        s.cash_value.cost_of_cash,
        ds.fixed_outflows,
    )
    return explain_all(ctx)


def plan_summary(s: Solved, pay_on_due: Plan) -> dict:
    """KPIs, certification, cash value, solver stats, and the fan for one solved case."""
    ds = s.inputs.dataset
    c = ds.company
    oos = evaluate(s.plan, s.headroom_c, c.as_of, c.buffer_cents)
    stats = s.plan.stats
    return {
        "kpis": kpis(s.plan, oos, s.cash_value, c.buffer_cents, c.as_of),
        "certification": certification_view(s.cert, oos),
        "cash_value": cash_value_view(s.cash_value),
        "solver": {
            "status": stats.status if stats else None,
            "mip_gap": stats.mip_gap if stats else None,
            "solve_seconds": stats.solve_seconds if stats else None,
            "rows": stats.rows if stats else None,
            "rows_naive": stats.rows_naive if stats else None,
            "nonzeros": stats.nonzeros if stats else None,
            "cols": stats.cols if stats else None,
            "check_days": stats.check_days if stats else None,
            "scenario_rows": stats.scenario_rows if stats else None,
            "case_seconds": s.seconds,
        },
        "fan": {
            "dates": [(c.as_of + timedelta(days=i)).isoformat() for i in range(c.horizon_days)],
            "before": balance_fan(pay_on_due, s.fan_headroom, c.as_of, c.buffer_cents),
            "after": balance_fan(s.plan, s.fan_headroom, c.as_of, c.buffer_cents),
            "buffer_cents": c.buffer_cents,
            "n": s.fan_headroom.shape[0],
            "low_paths": low_paths(s.plan, s.headroom_c, c.as_of, c.buffer_cents),
            "low_paths_n": int(s.headroom_c.shape[0]),
        },
        "plan_hash": s.plan.plan_hash(),
    }


def seed_b_kpis(s: Solved) -> dict:
    """The current plan scored on seed B, so live what-ifs (scored on seed B) compare like with like."""
    c = s.inputs.dataset.company
    est = evaluate(s.plan, s.inputs.headroom_b, c.as_of, c.buffer_cents)
    return kpis(s.plan, est, s.cash_value, c.buffer_cents, c.as_of)


def markers(plan: Plan) -> list[dict]:
    """The largest cash-outs, for markers on the fan chart."""
    rows = sorted(zip(plan.bills, plan.chosen(), strict=True), key=lambda bo: -bo[1].cash_out_cents)[
        :MARKER_COUNT
    ]
    return [
        {
            "date": o.cash_out_date.isoformat(),
            "amount_cents": o.cash_out_cents,
            "vendor": b.vendor_name,
            "option": o.kind,
        }
        for b, o in rows
    ]


def build_bundle(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    pay_on_due = pay_on_due_plan(base.inputs)
    decisions = decisions_for(base)
    c = dataset.company
    return {
        "input_hash": input_hash(dataset.regime),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": {
            "name": ingest_result.provider_name,
            "model": ingest_result.provider_model,
            "errors": ingest_result.provider_errors,
        },
        "company": {
            "name": c.name,
            "as_of": c.as_of.isoformat(),
            "horizon_days": c.horizon_days,
            "starting_cash_cents": c.starting_cash_cents,
            "buffer_cents": c.buffer_cents,
            "funding_account": c.funding_account,
        },
        **plan_summary(base, pay_on_due),
        "markers": markers(base.plan),
        "credit_cum_cents": [int(x) for x in base.plan.credit_cum_cents],
        "financing": financing_view(dataset, ingest_result),
        "kpis_seed_b": seed_b_kpis(base),
        "bills": bill_rows(base.plan, decisions, ingest_result.reconciled, c.as_of),
        "fixed_outflows": [
            {
                "date": f.on.isoformat(),
                "amount_cents": f.amount_cents,
                "category": f.category,
                "description": f.description,
            }
            for f in dataset.fixed_outflows
        ],
    }


def _interp_value(points: list[dict], rate: float) -> float | None:
    """Tempo's frontier value at a given seed-C breach rate (linear between certified points), if inside it."""
    pts = sorted((p["breach_rate"], p["value_cents"]) for p in points)
    for (r0, v0), (r1, v1) in pairwise(pts):
        if r0 <= rate <= r1:
            return v0 if r1 == r0 else v0 + (v1 - v0) * (rate - r0) / (r1 - r0)
    return None


def build_frontier(dataset: Dataset, base: Solved, fitted: dict) -> dict:
    """Tempo (no financing) certified at several targets with the same ladder shape; seed C reports each."""
    inputs = base.inputs
    buffer = dataset.company.buffer_cents
    points = []
    for eps in FRONTIER_EPSILONS:
        ladder = ladder_for(eps)
        if abs(eps - EPSILON) < 1e-12:
            plan, cert = base.plan, base.cert
        else:
            plan, cert = certify(
                inputs.bills,
                inputs.options,
                inputs.headroom_a,
                inputs.headroom_b,
                inputs.as_of,
                inputs.headroom_a_fallback,
                epsilon=eps,
                z=z_for(ladder),
                ladder=ladder,
                time_limit=PRECOMPUTE_TIME_LIMIT_S,
            )
        res = evaluate(plan, base.headroom_c, inputs.as_of, buffer)
        points.append(
            {
                "epsilon": eps,
                "certified": cert.passed,
                "k": cert.final.k,
                "n": cert.final.n,
                "value_cents": res.value_cents,
                "breach_rate": res.breach_rate,
                "breach_upper": res.breach_upper,
            }
        )
    baselines = []
    for name in FRONTIER_BASELINES:
        b = fitted[name]
        at = _interp_value(points, b.breach_rate)
        baselines.append(
            {
                "policy": name,
                "value_cents": b.value_cents,
                "breach_rate": b.breach_rate,
                "breach_upper": b.breach_upper,
                "tempo_value_at_same_risk_cents": None if at is None else round(at),
                "above_curve": at is not None and b.value_cents > at,
            }
        )
    return {"points": points, "baselines": baselines, "sentence": frontier_sentence(baselines)}


BASELINE_NAMES = {
    "weekly_run": "the weekly AP run",
    "greedy_discount": "greedy discount-taking",
    "greedy_p05": "the smart spreadsheet",
    "pay_on_due": "paying on due dates",
}


def frontier_sentence(baselines: list[dict]) -> str:
    """Computed from the data: Tempo's value at each baseline's own breach rate, versus that baseline."""
    parts = []
    for b in baselines:
        at = b["tempo_value_at_same_risk_cents"]
        if at is None:
            continue
        gap = round(at) - b["value_cents"]
        risk = f"{b['breach_rate'] * 100:.2f}%"
        name = BASELINE_NAMES[b["policy"]]
        if abs(gap) < 100:
            parts.append(f"at the risk of {name} ({risk}) it finds the same plan")
        elif gap > 0:
            parts.append(f"at the risk of {name} ({risk}) Tempo adds ${gap / 100:,.0f}")
        else:
            parts.append(
                f"at the risk of {name} ({risk}) Tempo earns ${-gap / 100:,.0f} less (docs/DECISIONS.md)"
            )
    outside = [BASELINE_NAMES[b["policy"]] for b in baselines if b["tempo_value_at_same_risk_cents"] is None]
    if not parts:
        return "No baseline's breach rate falls inside the range Tempo was certified at."
    text = "; ".join(parts)
    text = text[0].upper() + text[1:] + " over 13 weeks."
    if outside:
        names = ", ".join(outside)
        text += f" ({names[0].upper() + names[1:]}: riskier than any target certified here.)"
    return text


def build_proof(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    """Six policies on seed C (fitted model) and on the generator's true model, ablations, extraction eval."""
    plans = {**baseline_plans(base.inputs, base.cash_value.cost_of_cash), "tempo": base.plan}
    fitted = evaluate_all(plans, base.headroom_c, base.inputs)
    truth_scen = base.inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C, params=true_params(dataset))
    true_res = evaluate_all(plans, base.inputs.forecast.headroom(truth_scen), base.inputs)
    abl = {**ablation_plans(base.inputs), "tempo": base.plan}
    abl_res = evaluate_all(abl, base.headroom_c, base.inputs)
    hashes = {name: p.plan_hash() for name, p in {**plans, **abl}.items()}

    def tagged(rows: list[dict]) -> list[dict]:
        """Each row carries its plan hash so identical plans can be shown as one row with both names."""
        return [{**r, "plan_hash": hashes.get(r["policy"])} for r in rows]

    stress = macro_stress(base, plans)
    return {
        "input_hash": input_hash(dataset.regime),
        "seed_c": SEED_C,
        "policies": tagged([policy_view(fitted[p]) for p in POLICY_ORDER]),
        "policies_true_model": tagged([policy_view(true_res[p]) for p in POLICY_ORDER]),
        "policies_macro_stress": {**stress, "policies": tagged(stress["policies"])},
        "ablations": tagged(
            [
                policy_view(abl_res[p])
                for p in ("tempo", "per_day_5pct", "per_day_worst_case", "deterministic_p50")
            ]
        ),
        "financing_sensitivity": financing_sensitivity(dataset, ingest_result),
        "frontier": build_frontier(dataset, base, fitted),
        "extraction": evaluate_extraction(dataset, ingest_result.reconciled, ingest_result.extractions),
    }


def top_customers(dataset: Dataset, n: int = TOP_CUSTOMERS) -> list[tuple[str, str]]:
    totals = [
        (sum(r.amount_cents for r in (*c.open_receivables, *c.scheduled_billings)), c.id, c.name)
        for c in dataset.customers
    ]
    return [(cid, name) for _, cid, name in sorted(totals, reverse=True)[:n]]


def what_if_presets(dataset: Dataset) -> list[tuple[str, str, WhatIf]]:
    presets = []
    for cid, name in top_customers(dataset):
        for days in DELAY_PRESETS:
            presets.append((f"delay-{cid}-{days}", f"{name} pays {days} days late", WhatIf(cid, days)))
    for shock in SHOCK_PRESETS_CENTS:
        presets.append(
            (
                f"shock-{shock // 100}",
                f"Unexpected ${shock // 100:,} payment today",
                WhatIf(shock_cents=shock),
            )
        )
    return presets


def whatif_tradeoff(s: Solved, current: Plan) -> dict:
    """Tradeoff box for one solved what-if, scored on the case's own seed-C scenarios."""
    c = s.inputs.dataset.company
    oos = evaluate(s.plan, s.headroom_c, c.as_of, c.buffer_cents)
    n = s.plan.n_scenarios or s.inputs.headroom_a.shape[0]
    return tradeoff(
        s.plan,
        oos,
        current,
        s.inputs.headroom_a_fallback[:n],
        s.headroom_c,
        c.as_of,
        c.buffer_cents,
        time_limit=PRECOMPUTE_TIME_LIMIT_S,
    )


def build_whatifs(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    """Every preset re-solves with financing allowed (before any late payment), through the live code path's
    option builder, and is certified like the headline. The current plan is scored on the same seed-C
    scenarios in the tradeoff box ("accept the risk")."""
    out = []
    for preset_id, label, wi in what_if_presets(dataset):
        s = solve_case(dataset, ingest_result, wi, finance_enabled=True)
        pay_on_due = pay_on_due_plan(s.inputs)
        decisions = decisions_for(s)
        out.append(
            {
                "id": preset_id,
                "label": label,
                "what_if": {
                    "customer_id": wi.delay_customer_id,
                    "delay_days": wi.delay_days,
                    "shock_cents": wi.shock_cents,
                },
                **plan_summary(s, pay_on_due),
                "diff": diff_plans(base.plan, s.plan, decisions),
                "tradeoff": whatif_tradeoff(s, base.plan),
            }
        )
    return {"input_hash": input_hash(dataset.regime), "customers": top_customers(dataset), "presets": out}


def suggested_terms(r: Reconciled, prior: TermsRecord | None) -> TermsRecord | None:
    """What the reviewer is offered by default: the vendor's terms on file if a reading matches them, else the
    value the table proposed before the sanity/history check, else the first sane parser reading."""
    candidates = list(r.terms.regex_values)
    if r.terms.model_value is not None:
        candidates.append(r.terms.model_value)
    if prior is not None and prior in candidates:
        return prior
    if r.terms.proposed is not None and sanity_problem(r.terms.proposed) is None:
        return r.terms.proposed
    return next((c for c in candidates if sanity_problem(c) is None), prior)


def build_review_effects(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    vendors = {v.id: v for v in dataset.vendors}
    out = []
    for inv in dataset.invoices:
        r = ingest_result.reconciled[inv.id]
        if not r.terms.needs_review:
            continue
        suggestion = suggested_terms(r, vendors[inv.vendor_id].prior_terms)
        if suggestion is None:
            continue
        s = solve_case(dataset, ingest_result, overrides={inv.id: suggestion})
        out.append(
            {
                "bill_id": inv.id,
                "suggested": asdict(suggestion),
                "value_delta_cents": s.plan.value_cents() - base.plan.value_cents(),
                "diff": diff_plans(base.plan, s.plan, decisions_for(s)),
                "plan_hash": s.plan.plan_hash(),
            }
        )
    return {"input_hash": input_hash(dataset.regime), "effects": out}


def build_offers(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    """Priced and optimizer-verified early-payment offers for vendors with no discount terms."""
    offers = plan_offers(base.inputs, base.plan, base.cash_value.cost_of_cash)
    return {
        "input_hash": input_hash(dataset.regime),
        "cost_of_cash": base.cash_value.cost_of_cash,
        "offers": [asdict(o) for o in offers],
    }
