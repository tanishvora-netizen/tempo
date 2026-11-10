"""API smoke tests for every route (no Ollama, no network: TEMPO_PROVIDER=cached)."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TEMPO_PROVIDER", "cached")

from app.main import app


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


@pytest.mark.slow
def test_custom_what_if_solves_live_and_labels_the_estimate(client: TestClient) -> None:
    customer = client.get("/api/whatif/presets").json()["data"]["customers"][0]["id"]

    data = client.post("/api/optimize", json={"what_if": {"customer_id": customer, "delay_days": 10}}).json()[
        "data"
    ]

    assert data["source"] == "live"
    assert "not re-certified" in data["estimate"]["label"]


@pytest.mark.parametrize(
    "body",
    [
        {"what_if": {}},
        {"what_if": {"customer_id": "c", "delay_days": 999}},
        {"what_if": {"shock_cents": -5}},
        {"bogus": 1},
    ],
)
def test_bad_optimize_input_is_rejected(client: TestClient, body: dict) -> None:
    assert client.post("/api/optimize", json=body).status_code == 422


def test_unknown_customer_is_404(client: TestClient) -> None:
    r = client.post("/api/optimize", json={"what_if": {"customer_id": "cus_999", "delay_days": 5}})
    assert r.status_code == 404


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
