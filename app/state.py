"""Application state: committed data and precomputed results loaded once at startup.

The server never recomputes at startup. It replays the committed model cache and runs the deterministic
parser (fast), loads data/precomputed/*.json, and rebuilds the base plan lazily from the stored choices only
when a live re-solve needs it.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from tempo.data.store import load_dataset
from tempo.llm.cached_provider import CachedProvider
from tempo.llm.provider import LLMProvider, get_provider
from tempo.models import Dataset, TermsRecord
from tempo.optimize.cash_value import CashValue
from tempo.optimize.engine import Plan, option_sets
from tempo.optimize.options import RailContext
from tempo.pipeline import IngestResult, ingest, plannable_bills
from tempo.precompute import OUT_DIR, input_hash

REPO = Path(__file__).resolve().parents[1]


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
    overrides: dict[str, TermsRecord] = field(default_factory=dict)
    autonomy: dict = field(default_factory=lambda: {"mode": "suggest", "threshold_cents": 2_500_000})
    lock: threading.Lock = field(default_factory=threading.Lock)

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

    def live_provider(self) -> LLMProvider:
        """Provider for live calls (drafting, reply parsing): the local model if reachable, else the cache."""
        return get_provider()


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
        current_hash=input_hash("demo"),
        provider_label=label,
    )
