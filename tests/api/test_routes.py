"""API smoke tests for every route (no Ollama, no network: TEMPO_PROVIDER=cached)."""

import os
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TEMPO_PROVIDER", "cached")

from app.main import app


@pytest.fixture(autouse=True)
def _fresh_throttle() -> None:
    """Each test starts with an empty per-IP solve budget (the job tests would otherwise use it up)."""
    import app.main as main

    main.THROTTLE.hits.clear()
    main.THROTTLE.all_hits.clear()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    os.environ["TEMPO_AUDIT_PATH"] = str(tmp_path_factory.mktemp("audit") / "audit.jsonl")
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/",
        "/api/state",
        "/api/bills",
        "/api/review",
        "/api/forecast",
        "/api/whatif/presets",
        "/api/evaluate",
        "/api/cash-value",
        "/api/negotiate",
        "/api/plan/financing",
        "/api/audit",
        "/api/ramp/payload-preview",
    ],
)
def test_get_routes_answer(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_state_carries_kpis_certification_and_assumptions(client: TestClient) -> None:
    data = client.get("/api/state").json()["data"]

    assert data["synthetic"] is True
    assert data["certification"]["reported"]["n"] == 10_000
    assert any(a["label"] == "SOURCED" for a in data["assumptions"])
    assert any(a["label"] == "ASSUMPTION" for a in data["assumptions"])


def test_bill_detail_has_document_and_evidence(client: TestClient) -> None:
    bill_id = client.get("/api/bills").json()["data"]["bills"][0]["bill_id"]

    data = client.get(f"/api/bills/{bill_id}").json()["data"]

    assert data["document"]["blocks"]
    assert "reconciliation" in data


def test_unknown_bill_is_404(client: TestClient) -> None:
    assert client.get("/api/bills/../../etc/passwd").status_code == 404
    assert client.get("/api/bills/nope").status_code == 404


def test_preset_what_if_is_instant_and_precomputed(client: TestClient) -> None:
    preset = client.get("/api/whatif/presets").json()["data"]["presets"][0]["id"]

    data = client.post("/api/optimize", json={"what_if": {"preset_id": preset}}).json()["data"]

    assert data["source"] == "precomputed"
    assert "diff" in data


def _wait(client: TestClient, job: dict, timeout_s: float = 120.0) -> dict:
    """Poll a job the way the page does, until it is done or failed."""
    deadline = time.monotonic() + timeout_s
    seen = {job["status"]}
    while job["status"] in ("queued", "running"):
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.2)
        job = client.get(f"/api/jobs/{job['job_id']}").json()["data"]
        seen.add(job["status"])
    job["seen"] = seen
    return job


@pytest.mark.slow
def test_custom_what_if_runs_as_a_job_and_repeats_from_cache(client: TestClient) -> None:
    customer = client.get("/api/whatif/presets").json()["data"]["customers"][0]["id"]
    body = {"what_if": {"customer_id": customer, "delay_days": 11}}

    first = client.post("/api/optimize", json=body).json()["data"]
    assert first["source"] == "job" and first["status"] in ("queued", "running", "done")
    done = _wait(client, first)

    assert done["status"] == "done" and not done["cached"]
    result = done["result"]
    assert result["source"] == "live"
    assert "not certified" in result["estimate"]["label"]
    assert "planning scenarios" in result["estimate"]["label"]
    assert set(result["tradeoff"]) >= {"financing", "late_only", "accept_risk"}

    again = client.post("/api/optimize", json=body).json()["data"]
    assert again["status"] == "done" and again["cached"]
    assert again["result"]["plan_hash"] == result["plan_hash"]


@pytest.mark.slow
def test_jobs_queue_one_at_a_time(client: TestClient) -> None:
    customer = client.get("/api/whatif/presets").json()["data"]["customers"][1]["id"]
    a = client.post("/api/optimize", json={"what_if": {"customer_id": customer, "delay_days": 9}}).json()[
        "data"
    ]
    b = client.post("/api/optimize", json={"what_if": {"customer_id": customer, "delay_days": 19}}).json()[
        "data"
    ]

    assert b["status"] == "queued" and b["position"] >= 1
    assert _wait(client, a)["status"] == "done"
    assert _wait(client, b)["status"] == "done"


@pytest.mark.slow
def test_extreme_shock_returns_a_plan_with_the_financing_message_not_an_error(client: TestClient) -> None:
    job = client.post("/api/optimize", json={"what_if": {"shock_cents": 200_000_000}}).json()["data"]
    done = _wait(client, job)

    assert done["status"] == "done"
    kpis = done["result"]["kpis"]
    assert kpis["credit_drawn_cents"] >= 0
    if kpis["credit_drawn_cents"]:
        assert kpis["credit_first_date"]


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/jobs/nope").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"what_if": {}},
        {"what_if": {"customer_id": "c", "delay_days": 999}},
        {"what_if": {"shock_cents": -5}},
        {"what_if": {"shock_cents": 99_999}},
        {"what_if": {"shock_cents": 200_000_001}},
        {"what_if": {"customer_id": "c", "delay_days": 0}},
        {"what_if": {"customer_id": "c", "delay_days": 61}},
        {"bogus": 1},
    ],
)
def test_bad_optimize_input_is_rejected(client: TestClient, body: dict) -> None:
    assert client.post("/api/optimize", json=body).status_code == 422


def test_unknown_customer_is_a_clear_422(client: TestClient) -> None:
    r = client.post("/api/optimize", json={"what_if": {"customer_id": "cus_999", "delay_days": 5}})
    assert r.status_code == 422
    assert "listed customers" in r.json()["detail"]


def test_review_accept_and_validation(client: TestClient) -> None:
    items = client.get("/api/review").json()["data"]["items"]
    assert items, "the demo seeds Needs-review items"

    ok = client.post(f"/api/review/{items[0]['bill_id']}", json={"action": "accept"})
    bad = client.post(f"/api/review/{items[0]['bill_id']}", json={"action": "edit"})
    missing = client.post("/api/review/not-a-bill", json={"action": "accept"})

    assert ok.status_code == 200
    assert bad.status_code == 422
    assert missing.status_code == 404


def test_approve_writes_a_verified_audit_entry(client: TestClient) -> None:
    r = client.post("/api/plan/approve", json={"approver": "Dana Ortiz", "autonomy": {"mode": "suggest"}})
    audit = client.get("/api/audit").json()["data"]

    assert r.status_code == 200
    assert audit["chain"]["ok"] and audit["chain"]["entries"] >= 1


def test_approve_rejects_markup_in_the_approver_name(client: TestClient) -> None:
    assert client.post("/api/plan/approve", json={"approver": "<script>alert(1)</script>"}).status_code == 422


def test_payload_preview_is_never_sent(client: TestClient) -> None:
    data = client.get("/api/ramp/payload-preview").json()["data"]

    assert data["sent"] is False
    assert data["counts"]["requests"] > 0


def test_negotiation_routes(client: TestClient) -> None:
    offers = client.get("/api/negotiate").json()["data"].get("offers", [])
    if not offers:
        pytest.skip("offers are precomputed by `make precompute`")
    vendor = offers[0]["vendor_id"]

    draft = client.post(f"/api/negotiate/{vendor}").json()["data"]
    reply = client.post(f"/api/negotiate/{vendor}/reply", json={"kind": "accept"}).json()["data"]
    bad = client.post(f"/api/negotiate/{vendor}/reply", json={"kind": "maybe"})

    assert draft["sent"] is False and draft["email"]["body"]
    assert reply["needs_human_accept"] is True
    assert bad.status_code == 422
    assert client.post("/api/negotiate/ven_999").status_code == 404


def test_pdf_upload_reads_terms_and_rejects_non_pdfs(client: TestClient) -> None:
    from tests.unit.test_upload import make_pdf

    pdf = make_pdf(["Invoice #Z-9", "Payment terms: 1/10 Net 30"])
    ok = client.post("/api/extract/upload", files={"file": ("inv.pdf", pdf, "application/pdf")})
    bad = client.post("/api/extract/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})

    assert ok.status_code == 200
    assert ok.json()["data"]["terms"]["discount_bps"] == 100
    assert bad.status_code == 422


def test_an_approval_survives_the_idle_reset(client: TestClient) -> None:
    from app.main import STATE

    s = STATE["app"]
    s.touched_at -= 31 * 60  # the server looks idle
    bill_ids = [r["bill_id"] for r in client.get("/api/bills").json()["data"]["bills"][:3]]

    approved = client.post("/api/plan/approve", json={"approver": "Dana Ortiz", "bill_ids": bill_ids})
    preview = client.get("/api/ramp/payload-preview").json()["data"]

    assert approved.status_code == 200
    assert preview["scope"] == "last approval"
    assert preview["counts"]["bills"] == 3


def test_financing_plan_is_labeled_and_certified(client: TestClient) -> None:
    fin = client.get("/api/plan/financing").json()["data"]

    assert "assumption" in fin["label"]
    assert fin["certification"]["reported"]["n"] == 10_000
    assert fin["kpis"]["financed_count"] == fin["financed_count"]


def test_offers_carry_annual_value(client: TestClient) -> None:
    offers = client.get("/api/negotiate").json()["data"]["offers"]

    assert offers
    for o in offers:
        assert o["annual_value_cents"] == round(
            o["vendor_spend_13w_cents"] * 365 / 91 * o["offer_bps"] / 10_000
        )
