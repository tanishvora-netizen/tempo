"""Precompute the default plan, proof panel, what-if presets, and review effects (run with `make precompute`).

Always replays the committed model cache (CachedProvider), so local and hosted results are identical.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.data.store import load_dataset
from tempo.llm.cached_provider import CachedProvider
from tempo.pipeline import ingest
from tempo.precompute import (
    OUT_DIR,
    build_bundle,
    build_offers,
    build_proof,
    build_review_effects,
    build_whatifs,
    solve_case,
)
from tempo.serde import to_jsonable


def write(name: str, payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(to_jsonable(payload), indent=1, sort_keys=True) + "\n")


def main() -> None:
    dataset = load_dataset("demo")
    started = time.perf_counter()
    ingest_result = ingest(dataset, CachedProvider())
    base = solve_case(dataset, ingest_result)
    print(
        f"base solved in {base.seconds:.1f}s; certified={base.cert.passed} k={base.cert.final.k}", flush=True
    )
    for name, build in (
        ("bundle", build_bundle),
        ("proof", build_proof),
        ("whatifs", build_whatifs),
        ("review_effects", build_review_effects),
        ("offers", build_offers),
    ):
        t = time.perf_counter()
        write(name, build(dataset, ingest_result, base))
        print(f"{name}: {time.perf_counter() - t:.1f}s", flush=True)
    print(f"total {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
