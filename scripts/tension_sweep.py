"""Final-pass demo-tension sweep (Nov 10 fix pass, item 1). Run once; the output is committed.

Sweeps starting cash only, six values, highest first, and picks the HIGHEST value where, on seed C:
greedy_discount breach >= 15%, pay_on_due breach <= 2%, and Tempo certifies on seed B. If no value meets all
three, the current starting cash is kept. Every row is written to data/demo/tension_sweep.json and the
outcome is recorded in docs/DECISIONS.md. Nothing else in the generator changes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.assumptions import N_EVAL_SCENARIOS, SEED_C
from tempo.data.generator import GeneratorConfig, generate
from tempo.llm.cached_provider import CachedProvider
from tempo.optimize.run import baseline_plans, evaluate_all, prepare, run_tempo
from tempo.pipeline import ingest

CANDIDATES_CENTS = (400_000_000, 380_000_000, 360_000_000, 340_000_000, 320_000_000, 300_000_000)
GREEDY_MIN = 0.15
PAY_ON_DUE_MAX = 0.02
OUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "tension_sweep.json"


def row(cash: int) -> dict:
    dataset = generate(GeneratorConfig(starting_cash_cents=cash))
    inputs = prepare(dataset, ingest(dataset, CachedProvider()))
    tempo, cert = run_tempo(inputs)
    plans = {**baseline_plans(inputs), "tempo": tempo}
    head_c = inputs.forecast.headroom(inputs.forecast.scenarios(N_EVAL_SCENARIOS, SEED_C))
    res = evaluate_all(plans, head_c, inputs)
    greedy, due = res["greedy_discount"].breach_rate, res["pay_on_due"].breach_rate
    return {
        "starting_cash_cents": cash,
        "greedy_breach_seed_c": greedy,
        "pay_on_due_breach_seed_c": due,
        "tempo_certified": cert.passed,
        "tempo_breach_seed_c": res["tempo"].breach_rate,
        "meets_all": greedy >= GREEDY_MIN and due <= PAY_ON_DUE_MAX and cert.passed,
    }


def main() -> None:
    rows = []
    for cash in CANDIDATES_CENTS:
        r = row(cash)
        rows.append(r)
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
    chosen = next((r for r in rows if r["meets_all"]), None)
    out = {
        "rule": f"highest cash with greedy >= {GREEDY_MIN:.0%}, pay_on_due <= {PAY_ON_DUE_MAX:.0%}, Tempo certified",
        "seed": SEED_C,
        "chosen_cents": chosen["starting_cash_cents"] if chosen else None,
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print("chosen:", out["chosen_cents"])


if __name__ == "__main__":
    main()
