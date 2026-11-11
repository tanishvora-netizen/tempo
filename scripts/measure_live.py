"""Measure a custom what-if's time and peak memory the way the host runs it (one solve, in a fresh process).

Usage: python scripts/measure_live.py delay <customer_id> <days> | shock <dollars>
Prints one JSON line: seconds, solver status, and peak resident memory (MB) of this process. Run each case in
its own process so peaks do not mix. Used for the DECISIONS.md memory ruling (section C of the fix pass).
"""

import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import LIVE_SOLVE_LIMIT_S
from app.state import load_state
from tempo.forecast.simulate import WhatIf


def peak_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # bytes on macOS, KB on Linux


def main() -> None:
    kind = sys.argv[1]
    what_if = (
        WhatIf(sys.argv[2], int(sys.argv[3]))
        if kind == "delay"
        else WhatIf(shock_cents=int(sys.argv[2]) * 100)
    )
    s = load_state()
    _ = s.base_plan
    before = peak_mb()
    started = time.perf_counter()
    result = s.solve_live(what_if, {}, time_limit=LIVE_SOLVE_LIMIT_S)
    print(
        json.dumps(
            {
                "case": sys.argv[1:],
                "seconds": round(time.perf_counter() - started, 2),
                "status": result.payload["solver_status"],
                "peak_mb_after_startup": round(before, 1),
                "peak_mb": round(peak_mb(), 1),
                "late": result.payload["kpis"]["late_count"],
                "financed": result.payload["kpis"]["financed_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
