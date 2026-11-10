import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tempo.audit import append, read_entries, verify_chain
from tempo.precompute import OUT_DIR
from tempo.ramp.payloads import PATCH_FIELDS, REQUEST_PAYMENT_METHODS, payment_run

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "ramp_api_snapshot.md"


def _approve(path: Path, n: int) -> None:
    for i in range(n):
        append(
            path,
            f"cfo-{i}",
            {"mode": "suggest"},
            f"plan{i}",
            "inputs",
            {"value_cents": i},
            now=datetime(2026, 11, 10, 9, i, tzinfo=UTC),
        )


def test_chain_verifies_after_appends(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _approve(log, 3)

    status = verify_chain(log)

    assert status.ok and status.entries == 3
    assert read_entries(log)[1]["prev_hash"] == read_entries(log)[0]["hash"]


def test_tampering_with_an_entry_breaks_the_chain(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _approve(log, 3)
    lines = log.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["metrics"]["value_cents"] = 999_999
    lines[1] = json.dumps(entry, sort_keys=True)
    log.write_text("\n".join(lines) + "\n")

    status = verify_chain(log)

    assert not status.ok and status.first_bad == 1
    with pytest.raises(ValueError):
        append(log, "cfo", {"mode": "suggest"}, "p", "i", {})


def test_deleting_an_entry_breaks_the_chain(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _approve(log, 3)
    lines = log.read_text().splitlines()
    log.write_text("\n".join([lines[0], lines[2]]) + "\n")

    assert verify_chain(log).first_bad == 1


def _preview() -> dict:
    bundle = json.loads((OUT_DIR / "bundle.json").read_text())
    review_id = next(r["bill_id"] for r in bundle["bills"] if r["needs_review"])
    return payment_run(bundle["bills"], {review_id}, {"mode": "auto", "threshold_cents": 2_500_000}, "hash")


def test_payload_preview_uses_only_ramp_request_enums_and_fields() -> None:
    preview = _preview()
    snapshot = SNAPSHOT.read_text()

    assert preview["sent"] is False
    for action in preview["bills"]:
        for req in action["requests"]:
            assert req["path"].startswith("/developer/v1/bills/")
            if req["method"] == "PATCH":
                assert set(req["body"]) <= PATCH_FIELDS
                assert req["body"]["payment_method"] in REQUEST_PAYMENT_METHODS
                assert f"`{req['body']['payment_method']}`" in snapshot
    for field in PATCH_FIELDS:
        assert f"`{field}" in snapshot
    assert "/hold" in snapshot and "/release" in snapshot


def test_payload_preview_holds_review_bills_and_releases_accepted_ones() -> None:
    preview = _preview()

    assert preview["counts"]["hold"] >= 1
    assert preview["counts"]["release"] == 1


def test_rtp_dependent_bills_get_no_patch_and_rtp_patches_use_an_ach_safe_date() -> None:
    bundle = json.loads((OUT_DIR / "bundle.json").read_text())
    rows = bundle["bills"]

    preview = payment_run(rows, set(), {"mode": "suggest"}, "hash")

    by_id = {r["bill_id"]: r for r in rows}
    for action in preview["bills"]:
        row = by_id[action["bill_id"]]
        if row["rail"] == "RTP" and row["rtp_dependent"] and not row["needs_review"]:
            assert action["bucket"] == "manual_rtp" and action["requests"] == []
        for req in action["requests"]:
            if req["method"] == "PATCH":
                assert req["body"]["payment_date"] <= row["send_date"]
    assert preview["counts"]["manual_rtp"] >= 1


def test_auto_threshold_sums_a_vendors_bills_in_the_same_week() -> None:
    from tempo.ramp.payloads import auto_scheduled_ids

    base = {"chip": "Verified", "needs_review": False, "vendor_id": "v1", "send_date": "2026-11-16"}
    rows = [
        {**base, "bill_id": "a", "amount_cents": 1_500_000},
        {**base, "bill_id": "b", "amount_cents": 1_500_000},
    ]

    split = auto_scheduled_ids(rows, {"mode": "auto", "threshold_cents": 2_500_000})
    single = auto_scheduled_ids(rows[:1], {"mode": "auto", "threshold_cents": 2_500_000})

    assert split == set()  # $15K + $15K from one vendor in one week is $30K, over the $25K threshold
    assert single == {"a"}


def test_audit_entry_records_the_plan_as_of_date(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"

    entry = append(log, "cfo", {"mode": "suggest"}, "p", "i", {}, plan_as_of="2026-11-10")

    assert entry["plan_as_of"] == "2026-11-10" and verify_chain(log).ok
