"""Tempo HTTP API. Routes only; all logic lives in the `tempo` package."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import OptimizeRequest, Payload, ReviewAction, TermsInput
from app.state import AppState, load_state
from tempo.forecast.simulate import WhatIf
from tempo.live import live_solve
from tempo.models import TermsRecord
from tempo.views import assumptions_catalog, bill_detail, review_items

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("tempo")
STATE: dict[str, AppState] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["app"] = load_state()
    yield


app = FastAPI(title="Tempo", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def state() -> AppState:
    return STATE["app"]


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "invalid input", "detail": str(exc)})


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
            "certification": b["certification"],
            "cash_value": b["cash_value"],
            "solver": b["solver"],
            "plan_hash": b["plan_hash"],
            "autonomy": s.autonomy,
            "review_count": sum(r["needs_review"] for r in b["bills"]),
            "assumptions": assumptions_catalog(),
            "synthetic": True,
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
def post_review(bill_id: str, body: ReviewAction) -> Payload:
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
            return Payload(
                data={
                    "source": "precomputed",
                    "bill_id": bill_id,
                    "terms": item["suggested"],
                    "effect": item["effect"],
                }
            )
        result = live_solve(s.dataset, s.ingest, s.base_plan, s.cash_value, overrides=overrides)
        s.overrides = overrides
    return Payload(data={"source": "live", "bill_id": bill_id, "terms": terms.__dict__, **result.payload})


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


@app.get("/api/whatif/presets", response_model=Payload)
def get_presets() -> Payload:
    w = state().whatifs
    customers = [{"id": cid, "name": name} for cid, name in w.get("customers", [])]
    presets = [{"id": p["id"], "label": p["label"], "what_if": p["what_if"]} for p in w.get("presets", [])]
    return Payload(data={"customers": customers, "presets": presets})


@app.post("/api/optimize", response_model=Payload)
def post_optimize(body: OptimizeRequest) -> Payload:
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
        raise HTTPException(status_code=404, detail="unknown customer")
    what_if = WhatIf(wi.customer_id, wi.delay_days, wi.shock_cents, wi.shock_day)
    with s.lock:
        result = live_solve(s.dataset, s.ingest, s.base_plan, s.cash_value, what_if, dict(s.overrides))
    return Payload(data={"source": "live", **result.payload})


@app.get("/api/evaluate", response_model=Payload)
def get_evaluate() -> Payload:
    return Payload(data=state().proof)


@app.get("/api/cash-value", response_model=Payload)
def get_cash_value() -> Payload:
    return Payload(data=state().bundle["cash_value"])


def _terms_from(t: TermsInput | None) -> TermsRecord | None:
    if t is None:
        return None
    bps = round(t.discount_pct * 100) if t.discount_pct else None
    return TermsRecord(bps, t.discount_days if bps else None, t.net_days, t.anchor, t.prox_day)


def _terms_from_dict(d: dict | None) -> TermsRecord | None:
    return None if d is None else TermsRecord(**d)
