"""Tempo HTTP API. Routes only; all logic lives in the `tempo` package."""

import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.jobs import JobRunner, QueueFull
from app.schemas import (
    ApproveRequest,
    NegotiatedTerms,
    OptimizeRequest,
    Payload,
    ReplyRequest,
    ReviewAction,
    TermsInput,
)
from app.security import SecurityHeaders, Throttle
from app.state import AppState, load_state
from tempo import audit
from tempo.agent.negotiation import Offer, annual_value_cents, draft_email, parse_reply, vendor_spend_cents
from tempo.extract.upload import MAX_BYTES as MAX_UPLOAD_BYTES
from tempo.extract.upload import UploadRejected, read_upload
from tempo.forecast.simulate import WhatIf
from tempo.models import TermsRecord
from tempo.ramp.payloads import payment_run
from tempo.serde import from_jsonable
from tempo.views import assumptions_catalog, bill_detail, review_items

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("tempo")
STATE: dict[str, AppState] = {}
JOBS: dict[str, JobRunner] = {}
LIVE_SOLVE_LIMIT_S = 20.0  # what-if plan; the two tradeoff variants get half each, so solving stops by 40 s


def _solve_job(what_if: WhatIf, overrides: dict) -> dict:
    """Run one custom solve in the worker thread (never under the shared state lock)."""
    s = STATE["app"]
    result = s.solve_live(what_if, overrides, time_limit=LIVE_SOLVE_LIMIT_S)
    return {"source": "live", **result.payload}


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["app"] = load_state()
    JOBS["runner"] = JobRunner(_solve_job)
    yield


app = FastAPI(title="Tempo", version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeaders)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
THROTTLE = Throttle()


def state() -> AppState:
    """The shared demo state; it resets itself after IDLE_RESET_S without changes (council-free hygiene for a
    public no-auth demo: one visitor's clicks should not linger for the next)."""
    s = STATE["app"]
    s.reset_if_idle()
    return s


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError) -> JSONResponse:
    log.warning("rejected input: %s", exc)
    return JSONResponse(
        status_code=422, content={"error": "invalid input", "detail": "the request could not be used"}
    )


@app.post("/api/reset", response_model=Payload)
def post_reset() -> Payload:
    """Clear review acceptances, negotiated terms, and the autonomy setting (the audit log is append-only)."""
    s = STATE["app"]
    s.reset()
    return Payload(data={"reset": True})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Render and the keep-warm workflow."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state", response_model=Payload)
def get_state() -> Payload:
    s = state()
    b = s.bundle
    return Payload(
        data={
            "company": b["company"],
            "provider": {**b["provider"], "label": s.provider_label},
            "provenance": {
                "input_hash": b["input_hash"],
                "current_hash": s.current_hash,
                "hash_ok": s.hash_ok,
                "built_at": b["built_at"],
            },
            "kpis": b["kpis"],
            "kpis_seed_b": b.get("kpis_seed_b"),
            "certification": b["certification"],
            "cash_value": b["cash_value"],
            "solver": b["solver"],
            "plan_hash": b["plan_hash"],
            "autonomy": s.autonomy,
            "review_count": sum(r["needs_review"] and r["bill_id"] not in s.overrides for r in b["bills"]),
            "assumptions": assumptions_catalog(),
            "synthetic": True,
            "bill_count": len(b["bills"]),
        }
    )


@app.get("/api/bills", response_model=Payload)
def get_bills() -> Payload:
    return Payload(data={"bills": state().bundle["bills"], "plan_hash": state().bundle["plan_hash"]})


@app.get("/api/bills/{bill_id}", response_model=Payload)
def get_bill(bill_id: str) -> Payload:
    s = state()
    row = next((r for r in s.bundle["bills"] if r["bill_id"] == bill_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown bill")
    return Payload(data=bill_detail(s.dataset, s.ingest.reconciled, row))


@app.get("/api/review", response_model=Payload)
def get_review() -> Payload:
    s = state()
    items = review_items(s.dataset, s.ingest.reconciled, s.bundle["bills"], s.review_effects)
    return Payload(data={"items": items, "accepted": sorted(s.overrides)})


@app.post("/api/review/{bill_id}", response_model=Payload)
def post_review(bill_id: str, body: ReviewAction, request: Request) -> Payload:
    s = state()
    items = {
        i["bill_id"]: i
        for i in review_items(s.dataset, s.ingest.reconciled, s.bundle["bills"], s.review_effects)
    }
    item = items.get(bill_id)
    if item is None:
        raise HTTPException(status_code=404, detail="bill is not in Needs review")
    terms = _terms_from(body.terms) if body.action == "edit" else _terms_from_dict(item["suggested"])
    if terms is None:
        raise HTTPException(status_code=422, detail="no suggested terms; use edit")
    with s.lock:
        overrides = {**s.overrides, bill_id: terms}
        if body.action == "accept" and not s.overrides and item["effect"]:
            s.overrides = overrides
            s.touch()
            return Payload(
                data={
                    "source": "precomputed",
                    "bill_id": bill_id,
                    "terms": item["suggested"],
                    "effect": item["effect"],
                }
            )
        THROTTLE.check(request)
        result = s.solve_live(None, overrides)
        s.overrides = overrides
        s.touch()
    return Payload(data={"source": "live", "bill_id": bill_id, "terms": terms.__dict__, **result.payload})


@app.post("/api/extract/upload", response_model=Payload)
async def post_upload(request: Request, file: Annotated[UploadFile, File()]) -> Payload:
    """Read terms from an uploaded invoice PDF (in memory, never stored; never changes the plan)."""
    THROTTLE.check(request)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    s = state()
    try:
        result = await run_in_threadpool(read_upload, data, s.live_provider(), s.dataset.company.as_of)
    except UploadRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Payload(data={**result, "filename": (file.filename or "upload.pdf")[:120]})


@app.get("/api/forecast", response_model=Payload)
def get_forecast() -> Payload:
    b = state().bundle
    return Payload(
        data={
            "fan": b["fan"],
            "markers": b["markers"],
            "fixed_outflows": b["fixed_outflows"],
            "breach_rate": b["kpis"]["breach_rate"],
            "breach_upper": b["kpis"]["breach_upper"],
        }
    )


@app.get("/api/plan/financing", response_model=Payload)
def get_financing_plan() -> Payload:
    """The precomputed plan with Flex-style financing on (Overview toggle). Its fee is an assumption, so the
    headline plan never uses it; this view is certified the same way and labeled as such."""
    fin = state().bundle.get("financing")
    if not fin:
        raise HTTPException(status_code=404, detail="no financing plan in this build")
    return Payload(data=fin)


@app.get("/api/whatif/presets", response_model=Payload)
def get_presets() -> Payload:
    w = state().whatifs
    customers = [{"id": cid, "name": name} for cid, name in w.get("customers", [])]
    presets = [{"id": p["id"], "label": p["label"], "what_if": p["what_if"]} for p in w.get("presets", [])]
    return Payload(data={"customers": customers, "presets": presets})


@app.post("/api/optimize", response_model=Payload)
def post_optimize(body: OptimizeRequest, request: Request) -> Payload:
    s = state()
    wi = body.what_if
    if wi is None:
        return Payload(data={"source": "precomputed", "kpis": s.bundle["kpis"], "diff": []})
    if wi.preset_id is not None:
        preset = next((p for p in s.whatifs.get("presets", []) if p["id"] == wi.preset_id), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="unknown preset")
        return Payload(data={"source": "precomputed", **preset})
    known = {c.id for c in s.dataset.customers}
    if wi.customer_id is not None and wi.customer_id not in known:
        raise HTTPException(status_code=422, detail="unknown customer: pick one of the listed customers")
    what_if = WhatIf(wi.customer_id, wi.delay_days, wi.shock_cents, wi.shock_day)
    runner = JOBS["runner"]
    with s.lock:
        overrides = dict(s.overrides)
    if not runner.is_cached(what_if, overrides):
        THROTTLE.check(request)
    try:
        job = runner.submit(what_if, overrides)
    except QueueFull as exc:
        raise HTTPException(
            status_code=503, detail="Too many scenarios are waiting. Please retry in a minute."
        ) from exc
    return Payload(data={"source": "job", **job})


@app.get("/api/jobs/{job_id}", response_model=Payload)
def get_job(job_id: str) -> Payload:
    """Poll a custom solve: queued (with how many are ahead), running, done (with the result), or error."""
    job = JOBS["runner"].get(job_id[:40])
    if job is None:
        raise HTTPException(status_code=404, detail="unknown or expired job")
    return Payload(data=job)


@app.get("/api/evaluate", response_model=Payload)
def get_evaluate() -> Payload:
    return Payload(data=state().proof)


@app.get("/api/cash-value", response_model=Payload)
def get_cash_value() -> Payload:
    return Payload(data=state().bundle["cash_value"])


@app.get("/api/negotiate", response_model=Payload)
def get_offers() -> Payload:
    """Offers with "annual value if accepted" (13-week spend x 365/91 x offer), computed from the committed data."""
    s = state()
    spend = vendor_spend_cents(s.base_plan.bills)
    horizon = s.dataset.company.horizon_days
    offers = [
        {
            **o,
            "annual_value_cents": annual_value_cents(spend.get(o["vendor_id"], 0), o["offer_bps"], horizon),
            "vendor_spend_13w_cents": spend.get(o["vendor_id"], 0),
        }
        for o in s.offers.get("offers", [])
    ]
    return Payload(data={**s.offers, "offers": offers, "negotiated": s.negotiated})


def _offer_raw(vendor_id: str) -> dict:
    raw = next((o for o in state().offers.get("offers", []) if o["vendor_id"] == vendor_id), None)
    if raw is None:
        raise HTTPException(status_code=404, detail="no offer for this vendor")
    return raw


def _offer(vendor_id: str) -> Offer:
    return from_jsonable(Offer, _offer_raw(vendor_id))


@app.post("/api/negotiate/{vendor_id}", response_model=Payload)
def post_offer(vendor_id: str) -> Payload:
    """Draft the offer email: the model writes placeholders only; code fills and guards every number."""
    text, source = draft_email(state().live_provider(), _offer(vendor_id))
    email = {
        "subject": text.subject,
        "body": text.body,
        "source": source,
        "used_fallback": text.used_fallback,
        "problems": list(text.problems),
    }
    return Payload(data={"offer": _offer_raw(vendor_id), "email": email, "sent": False})


@app.post("/api/negotiate/{vendor_id}/reply", response_model=Payload)
def post_reply(vendor_id: str, body: ReplyRequest) -> Payload:
    """Simulate a vendor reply and parse it; terms are written only after a person clicks Accept."""
    return Payload(data=parse_reply(state().live_provider(), _offer(vendor_id), body.kind))


@app.post("/api/negotiate/{vendor_id}/accept", response_model=Payload)
def post_accept_terms(vendor_id: str, body: NegotiatedTerms) -> Payload:
    _offer(vendor_id)
    terms = _terms_from(body.terms)
    s = state()
    with s.lock:
        s.negotiated = {
            **s.negotiated,
            vendor_id: {"terms": terms.__dict__ if terms else None, "source": "NEGOTIATED"},
        }
        s.touch()
    return Payload(data={"vendor_id": vendor_id, "negotiated": s.negotiated[vendor_id]})


@app.post("/api/plan/approve", response_model=Payload)
def post_approve(body: ApproveRequest, request: Request) -> Payload:
    """Record the CFO's approval in the append-only, hash-chained audit log. Nothing is sent to Ramp."""
    s = state()
    autonomy = body.autonomy.model_dump()
    with s.lock:
        if s.overrides and s.override_result is None:
            THROTTLE.check(request)
        plan_rows, plan_hash, plan_kpis = s.current_plan()
        rows = {r["bill_id"]: r for r in plan_rows}
        ids = sorted(set(body.bill_ids)) if body.bill_ids is not None else sorted(rows)
        unknown = [i for i in ids if i not in rows]
        if unknown:
            raise HTTPException(status_code=422, detail=f"{len(unknown)} unknown bill ids")
        scope = {
            "bill_count": len(ids),
            "cash_out_cents": sum(rows[i]["cash_out_cents"] for i in ids),
            "value_cents": sum(rows[i]["value_cents"] for i in ids),
            "rtp_dependent_count": sum(rows[i]["rtp_dependent"] for i in ids),
            "bill_ids_sha256": hashlib.sha256(",".join(ids).encode()).hexdigest(),
            "approver_authenticated": False,
        }
        metrics = {
            "scope": scope,
            "plan": {k: plan_kpis[k] for k in ("value_vs_pay_on_due_cents", "breach_rate", "breach_upper")},
        }
        s.autonomy = autonomy
        try:
            entry = audit.append(
                s.audit_path,
                body.approver,
                autonomy,
                plan_hash,
                s.bundle["input_hash"],
                metrics,
                plan_as_of=s.dataset.company.as_of.isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        s.approved_ids = set(ids)
        s.touch()
    return Payload(data={"entry": entry, "chain": audit.verify_chain(s.audit_path).__dict__})


@app.get("/api/audit", response_model=Payload)
def get_audit() -> Payload:
    path = state().audit_path
    return Payload(data={"entries": audit.read_entries(path), "chain": audit.verify_chain(path).__dict__})


@app.get("/api/ramp/payload-preview", response_model=Payload)
def get_payload_preview() -> Payload:
    s = state()
    with s.lock:
        rows, plan_hash, _ = s.current_plan()
    if s.approved_ids:
        rows = [r for r in rows if r["bill_id"] in s.approved_ids]
    preview = payment_run(rows, set(s.overrides), s.autonomy, plan_hash)
    return Payload(
        data={**preview, "scope": "last approval" if s.approved_ids else "whole plan (not yet approved)"}
    )


def _terms_from(t: TermsInput | None) -> TermsRecord | None:
    if t is None:
        return None
    bps = round(t.discount_pct * 100) if t.discount_pct else None
    return TermsRecord(bps, t.discount_days if bps else None, t.net_days, t.anchor, t.prox_day)


def _terms_from_dict(d: dict | None) -> TermsRecord | None:
    return None if d is None else TermsRecord(**d)
