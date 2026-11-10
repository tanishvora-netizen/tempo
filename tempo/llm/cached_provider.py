"""Replay committed model outputs. Used on the hosted demo and in tests; never touches the network.

Entries live at data/cache/<task>/<key>.json, keyed by sha256(prompt_version | schema_version | document),
so any provider's output is found regardless of who produced it. Failed calls are cached too and replay as
failures, so the host shows exactly what the local run saw.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from tempo.llm.provider import (
    PROMPT_VERSION,
    REPO_ROOT,
    CacheMiss,
    Completion,
    ExtractionFailed,
    LLMProvider,
    ModelCall,
)
from tempo.llm.schemas import SCHEMA_VERSION

CACHE_DIR = REPO_ROOT / "data" / "cache"


@dataclass(frozen=True)
class CacheEntry:
    key: str
    task: str
    provider: str
    model: str
    created_at: str
    raw: str | None
    error: str | None


def entry_path(cache_dir: Path, call: ModelCall) -> Path:
    return cache_dir / call.task / f"{call.key()}.json"


def write_entry(
    cache_dir: Path, call: ModelCall, provider: str, model: str, raw: str | None, error: str | None
) -> None:
    """Persist one model output (or failure) for replay."""
    path = entry_path(cache_dir, call)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "key": call.key(),
        "task": call.task,
        "provider": provider,
        "model": model,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "raw": raw,
        "error": error,
    }
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")


def read_entry(cache_dir: Path, call: ModelCall) -> CacheEntry | None:
    path = entry_path(cache_dir, call)
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    return CacheEntry(
        d["key"], d["task"], d["provider"], d["model"], d["created_at"], d.get("raw"), d.get("error")
    )


class CachedProvider(LLMProvider):
    name = "cached"

    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self.cache_dir = cache_dir
        self.model = _manifest_model(cache_dir)

    def complete(self, call: ModelCall, schema: type[BaseModel]) -> Completion:
        del schema
        entry = read_entry(self.cache_dir, call)
        if entry is None:
            raise CacheMiss(f"no cached {call.task} output for key {call.key()[:12]}")
        if entry.error is not None or entry.raw is None:
            raise ExtractionFailed(f"cached failure from {entry.model}: {entry.error}")
        return Completion(entry.raw, f"cached:{entry.provider}", entry.model)


def _manifest_model(cache_dir: Path) -> str:
    manifest = cache_dir / "manifest.json"
    if not manifest.exists():
        return "none"
    return ", ".join(sorted(json.loads(manifest.read_text()).get("models", {}))) or "none"
