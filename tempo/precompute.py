"""Precompute everything the UI shows, keyed by an input hash, so the hosted demo never waits on a solve.

Writes data/precomputed/{bundle,proof,whatifs,review_effects}.json. The host only loads these files; on a
hash mismatch it serves them anyway with a visible "results from build <hash>" banner.
"""

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np

from tempo.agent.negotiation import plan_offers
from tempo.assumptions import EPSILON, N_EVAL_SCENARIOS, N_FAN_SCENARIOS, SEED, SEED_C, SEED_FAN
from tempo.extract.eval import evaluate_extraction
from tempo.extract.reconcile import Reconciled, sanity_problem
from tempo.forecast.simulate import WhatIf
from tempo.models import Dataset, Decision, TermsRecord
from tempo.optimize import baselines as bl
from tempo.optimize.cash_value import CashValue, marginal_value_of_cash
from tempo.optimize.certify import Certification, certify
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

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "data" / "precomputed"
DELAY_PRESETS = (7, 14, 30)
SHOCK_PRESETS_CENTS = (10_000_000, 25_000_000)
TOP_CUSTOMERS = 3
MARKER_COUNT = 8


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


SENSITIVITY_LADDER = (10, 8, 6, 4, 3, 2, 1, 0)  # starts at K = EPSILON * N for N = 200


def ladder_sensitivity(dataset: Dataset, base: "Solved") -> dict:
    """Certification ladder starting at K = EPSILON * N (not the pre-registered 4..0), Bonferroni over its rungs.

    Added after the headline results were seen (disclosed in DECISIONS.md); reported beside, never instead of,
    the headline. Seed B still decides; seed C and the true model only report."""
    inputs = base.inputs
    z = NormalDist().inv_cdf(1 - EPSILON / (len(SENSITIVITY_LADDER) + 1))
    plan, cert = certify(
        inputs.bills,
        inputs.options,
        inputs.headroom_a,
        inputs.headroom_b,
        inputs.as_of,
        inputs.headroom_a_fallback,
        z=z,
        ladder=SENSITIVITY_LADDER,
    )
    fitted = evaluate(plan, base.headroom_c, inputs.as_of, dataset.company.buffer_cents)
    truth = inputs.forecast.headroom(
        inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C, params=true_params(dataset))
    )
    true_res = evaluate(plan, truth, inputs.as_of, dataset.company.buffer_cents)
    return {
        **policy_view(fitted),
        "policy": "tempo_ladder_from_eps_n",
        "certified": cert.passed,
        "k": cert.final.k,
        "z": z,
        "cert_upper": cert.final.cert_upper,
        "true_breach_rate": true_res.breach_rate,
        "true_breach_upper": true_res.breach_upper,
    }


def financing_sensitivity(dataset: Dataset, ingest_result: IngestResult) -> dict:
    """Tempo with the Flex-style option on (assumed fee, capped line), evaluated on seed C like the headline."""
    inputs = prepare(dataset, ingest_result, finance_enabled=True)
    plan, cert = run_tempo(inputs)
    head_c = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C))
    res = evaluate(plan, head_c, inputs.as_of, dataset.company.buffer_cents)
    financed = [o for o in plan.chosen() if o.rail == "FINANCE"]
    return {
        **policy_view(res),
        "policy": "tempo_with_financing",
        "certified": cert.passed,
        "financed_count": len(financed),
        "financed_cents": sum(o.cash_out_cents for o in financed),
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
) -> Solved:
    """Prepare, certify, value cash, and draw the reporting (C) and fan scenarios for one case."""
    started = time.perf_counter()
    inputs = prepare(dataset, ingest_result, what_if, overrides)
    plan, cert = run_tempo(inputs)
    cv = marginal_value_of_cash(inputs, plan)
    head_c = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C))
    fan = inputs.forecast.headroom(inputs.forecast.scenarios(N_FAN_SCENARIOS, SEED_FAN))
    return Solved(inputs, plan, cert, cv, head_c, fan, time.perf_counter() - started)


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
        },
        "plan_hash": s.plan.plan_hash(),
    }


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
        "bills": bill_rows(base.plan, decisions, ingest_result.reconciled),
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


def build_proof(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    """Six policies on seed C (fitted model) and on the generator's true model, ablations, extraction eval."""
    plans = {**baseline_plans(base.inputs, base.cash_value.cost_of_cash), "tempo": base.plan}
    fitted = evaluate_all(plans, base.headroom_c, base.inputs)
    truth_scen = base.inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C, params=true_params(dataset))
    true_res = evaluate_all(plans, base.inputs.forecast.headroom(truth_scen), base.inputs)
    abl = {**ablation_plans(base.inputs), "tempo": base.plan}
    abl_res = evaluate_all(abl, base.headroom_c, base.inputs)
    return {
        "input_hash": input_hash(dataset.regime),
        "seed_c": SEED_C,
        "policies": [policy_view(fitted[p]) for p in POLICY_ORDER],
        "policies_true_model": [policy_view(true_res[p]) for p in POLICY_ORDER],
        "ablations": [
            policy_view(abl_res[p])
            for p in ("tempo", "per_day_5pct", "per_day_worst_case", "deterministic_p50")
        ],
        "financing_sensitivity": financing_sensitivity(dataset, ingest_result),
        "ladder_sensitivity": ladder_sensitivity(dataset, base),
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


def build_whatifs(dataset: Dataset, ingest_result: IngestResult, base: Solved) -> dict:
    out = []
    for preset_id, label, wi in what_if_presets(dataset):
        s = solve_case(dataset, ingest_result, wi)
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
