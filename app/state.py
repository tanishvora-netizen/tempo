"""Application state: committed data and precomputed results loaded once at startup.

The server never recomputes at startup. It replays the committed model cache and runs the deterministic
parser (fast), loads data/precomputed/*.json, and rebuilds the base plan lazily from the stored choices only
when a live re-solve needs it.
"""

import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from tempo.data.store import load_dataset
from tempo.forecast.simulate import WhatIf
from tempo.live import LiveResult, live_solve
from tempo.llm.cached_provider import CachedProvider
from tempo.llm.provider import LLMProvider, ProviderError, get_provider
from tempo.models import Dataset, TermsRecord
from tempo.optimize.cash_value import CashValue
from tempo.optimize.engine import Plan, option_sets
from tempo.optimize.options import RailContext
from tempo.pipeline import IngestResult, ingest, plannable_bills
from tempo.precompute import OUT_DIR, input_hash

REPO = Path(__file__).resolve().parents[1]
DEFAULT_AUTONOMY = {"mode": "suggest", "threshold_cents": 2_500_000}
IDLE_RESET_S = 30 * 60  # a public demo forgets one visitor's clicks after 30 idle minutes
LIVE_CACHE_SIZE = 64


@dataclass
class AppState:
    dataset: Dataset
    ingest: IngestResult
    bundle: dict
    proof: dict
    whatifs: dict
    review_effects: dict
    current_hash: str
    provider_label: str
    offers: dict = field(default_factory=dict)
    overrides: dict[str, TermsRecord] = field(default_factory=dict)
    negotiated: dict[str, dict] = field(default_factory=dict)
    autonomy: dict = field(default_factory=lambda: dict(DEFAULT_AUTONOMY))
    lock: threading.Lock = field(default_factory=threading.Lock)
    touched_at: float = field(default_factory=time.monotonic)
    _live_cache: OrderedDict = field(default_factory=OrderedDict)

    def reset(self) -> None:
        with self.lock:
            self.overrides = {}
            self.negotiated = {}
            self.autonomy = dict(DEFAULT_AUTONOMY)
            self.touched_at = time.monotonic()

    def reset_if_idle(self) -> None:
        if (self.overrides or self.negotiated) and time.monotonic() - self.touched_at > IDLE_RESET_S:
            self.reset()

    def _key(self, what_if: WhatIf | None, overrides: dict[str, TermsRecord]) -> tuple:
        return (what_if, tuple(sorted(overrides.items())))

    def is_cached(self, what_if: WhatIf | None, overrides: dict[str, TermsRecord]) -> bool:
        return self._key(what_if, overrides) in self._live_cache

    def solve_live(self, what_if: WhatIf | None, overrides: dict[str, TermsRecord]) -> LiveResult:
        """Live re-solve with a small LRU cache (identical requests are answered instantly)."""
        key = self._key(what_if, overrides)
        if key in self._live_cache:
            self._live_cache.move_to_end(key)
            return self._live_cache[key]
        result = live_solve(self.dataset, self.ingest, self.base_plan, self.cash_value, what_if, overrides)
        self._live_cache[key] = result
        if len(self._live_cache) > LIVE_CACHE_SIZE:
            self._live_cache.popitem(last=False)
        self.touched_at = time.monotonic()
        return result

    @property
    def hash_ok(self) -> bool:
        return self.bundle.get("input_hash") == self.current_hash

    @cached_property
    def base_plan(self) -> Plan:
        """Rebuild the precomputed default plan from its stored choices (no solve)."""
        bills = plannable_bills(self.dataset, self.ingest)
        options = option_sets(
            bills, RailContext(self.dataset.company.as_of, self.dataset.company.funding_account)
        )
        rows = {r["bill_id"]: r["chosen_index"] for r in self.bundle["bills"]}
        choice = tuple(rows[b.id] for b in bills)
        cert = self.bundle["certification"]
        horizon = self.dataset.company.horizon_days
        credit = np.array(self.bundle.get("credit_cum_cents", [0] * horizon), dtype=np.int64)
        return Plan("tempo", bills, options, choice, credit, cert["k"], cert["n"], None)

    @cached_property
    def cash_value(self) -> CashValue:
        return CashValue(**self.bundle["cash_value"])

    @property
    def audit_path(self) -> Path:
        return Path(os.environ.get("TEMPO_AUDIT_PATH", str(REPO / "data" / "audit" / "audit.jsonl")))

    def live_provider(self) -> LLMProvider:
        """Provider for live calls (drafting, reply parsing): the local model if reachable, else the cache."""
        try:
            return get_provider()
        except ProviderError:
            return CachedProvider()


def _read(name: str) -> dict:
    path = OUT_DIR / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_state() -> AppState:
    dataset = load_dataset("demo")
    result = ingest(dataset, CachedProvider())
    mode = os.environ.get("TEMPO_PROVIDER", "").strip().lower() or "auto"
    label = "cached" if mode == "cached" else f"{mode} (extractions replayed from the local-model cache)"
    return AppState(
        dataset=dataset,
        ingest=result,
        bundle=_read("bundle"),
        proof=_read("proof"),
        whatifs=_read("whatifs"),
        review_effects=_read("review_effects"),
        offers=_read("offers"),
        current_hash=input_hash("demo"),
        provider_label=label,
    )
