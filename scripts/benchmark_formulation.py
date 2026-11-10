"""Measure the naive vs reduced chance-constrained MILP on the demo data (rows, nonzeros, time, peak memory).

Each formulation runs in its own process so peak memory is measured separately. Writes
data/precomputed/benchmark.json, which docs/DECISIONS.md cites.
"""

import json
import resource
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "data" / "precomputed" / "benchmark.json"
NAIVE_TIME_LIMIT_S = 60.0
K = 4


def run_one(reduced: bool) -> dict:
    from tempo.data.store import load_dataset
    from tempo.llm.cached_provider import CachedProvider
    from tempo.optimize.capacity import capacity_groups
    from tempo.optimize.milp import solve
    from tempo.optimize.run import prepare
    from tempo.pipeline import ingest

    ds = load_dataset("demo")
    inputs = prepare(ds, ingest(ds, CachedProvider()))
    started = time.perf_counter()
    res = solve(
        inputs.options,
        inputs.headroom_a,
        inputs.as_of,
        K,
        reduced=reduced,
        capacity=capacity_groups(inputs.options),
        time_limit=NAIVE_TIME_LIMIT_S,
    )
    elapsed = time.perf_counter() - started
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # bytes on macOS
    if sys.platform.startswith("linux"):
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {
        "reduced": reduced,
        "rows": res.stats.rows,
        "cols": res.stats.cols,
        "nonzeros": res.stats.nonzeros,
        "status": res.stats.status,
        "mip_gap": res.stats.mip_gap,
        "seconds": round(elapsed, 2),
        "objective_dollars": round(res.objective_dollars, 2),
        "peak_rss_mb": round(peak_mb, 1),
        "options": sum(len(o) for o in inputs.options),
        "bills": len(inputs.bills),
        "scenarios": int(inputs.headroom_a.shape[0]),
        "check_days": res.stats.check_days,
    }


def main() -> None:
    if len(sys.argv) == 2:
        print(json.dumps(run_one(sys.argv[1] == "reduced")))
        return
    rows = []
    for mode in ("reduced", "naive"):
        out = subprocess.run([sys.executable, __file__, mode], capture_output=True, text=True, check=True)
        rows.append(json.loads(out.stdout.strip().splitlines()[-1]))
        print(rows[-1], flush=True)
    OUT.write_text(
        json.dumps({"k": K, "naive_time_limit_s": NAIVE_TIME_LIMIT_S, "runs": rows}, indent=1) + "\n"
    )


if __name__ == "__main__":
    main()
