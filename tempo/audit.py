"""Append-only, hash-chained (tamper-evident, not tamper-proof) audit log of plan approvals (JSONL).

Each entry stores: timestamp, approver, autonomy mode, plan hash, input hash, metrics, and the hash of the
previous entry. Its own hash is sha256 over its canonical JSON (without the hash field). `verify_chain`
recomputes every link, so editing, deleting, or reordering any entry breaks the chain from that point on.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

GENESIS = "0" * 64
MAX_ENTRIES = 1_000  # a public demo log is capped so it cannot be spammed without bound


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    entries: int
    first_bad: int | None  # index of the first entry whose link or hash fails
    head: str  # hash of the last entry (GENESIS when empty)


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_chain(path: Path) -> ChainStatus:
    """Recompute every hash and every prev link."""
    entries = read_entries(path)
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("prev_hash") != prev or e.get("hash") != _digest(e):
            return ChainStatus(False, len(entries), i, prev)
        prev = e["hash"]
    return ChainStatus(True, len(entries), None, prev)


def append(
    path: Path,
    approver: str,
    autonomy: dict,
    plan_hash: str,
    input_hash: str,
    metrics: dict,
    now: datetime | None = None,
) -> dict:
    """Append one approval entry, linked to the current head. Refuses to append to a broken chain."""
    status = verify_chain(path)
    if not status.ok:
        raise ValueError(f"audit chain is broken at entry {status.first_bad}; refusing to append")
    if status.entries >= MAX_ENTRIES:
        raise ValueError(f"audit log is full ({MAX_ENTRIES} entries)")
    entry = {
        "timestamp": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "approver": approver,
        "autonomy": autonomy,
        "plan_hash": plan_hash,
        "input_hash": input_hash,
        "metrics": metrics,
        "prev_hash": status.head,
    }
    entry["hash"] = _digest(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry
