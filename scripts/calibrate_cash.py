"""Calibrate the demo's starting cash: the ONLY generator parameter tuned (directive section 6).

Pre-registered in docs/DECISIONS.md before the first run: sweep six values ($3.0M to $4.0M, $0.2M steps) on
seed D (never the reported seed C). Pick the first value meeting all three directive thresholds; if none
does, the first value with pay_on_due <= 2%, greedy_discount above EPSILON, and Tempo certified with at least
60% of greedy's value. Writes data/demo/calibration.json with every row of the sweep.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.assumptions import EPSILON, N_EVAL_SCENARIOS, SEED_D
from tempo.data.generator import GeneratorConfig, generate
from tempo.llm.provider import get_provider
from tempo.optimize.run import baseline_plans, evaluate_all, prepare, run_tempo
from tempo.pipeline import ingest

CANDIDATES_CENTS = (300_000_000, 320_000_000, 340_000_000, 360_000_000, 380_000_000, 400_000_000)
OUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "calibration.json"


def sweep_row(cash: int, provider) -> dict:
    dataset = generate(GeneratorConfig(starting_cash_cents=cash))
    inputs = prepare(dataset, ingest(dataset, provider))
    tempo, cert = run_tempo(inputs)
    plans = {**baseline_plans(inputs), "tempo": tempo}
    head_d = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_D))
    res = evaluate_all(plans, head_d, inputs)
    greedy, due, tem = res["greedy_discount"], res["pay_on_due"], res["tempo"]
    share = tem.value_cents / greedy.value_cents if greedy.value_cents else 0.0
    return {
        "starting_cash_cents": cash,
        "pay_on_due_breach": due.breach_rate,
        "greedy_breach": greedy.breach_rate,
        "tempo_certified": cert.passed,
        "tempo_value_share_of_greedy": share,
        "meets_directive": greedy.breach_rate >= 0.15
        and due.breach_rate <= 0.02
        and cert.passed
        and share >= 0.6,
        "meets_fallback": greedy.breach_rate > EPSILON
        and due.breach_rate <= 0.02
        and cert.passed
        and share >= 0.6,
    }


def main() -> None:
    provider = get_provider()
    rows = []
    for cash in CANDIDATES_CENTS:
        row = sweep_row(cash, provider)
        rows.append(row)
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    chosen = next((r for r in rows if r["meets_directive"]), None)
    rule = "directive"
    if chosen is None:
        chosen, rule = next((r for r in rows if r["meets_fallback"]), None), "fallback"
    if chosen is None:
        sys.exit("No candidate met even the fallback rule; see the rows above.")
    out = {
        "starting_cash_cents": chosen["starting_cash_cents"],
        "rule": rule,
        "seed": SEED_D,
        "provider": provider.name,
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"chosen ${chosen['starting_cash_cents'] / 100:,.0f} by the {rule} rule -> {OUT}")


if __name__ == "__main__":
    main()
