"""Ramp API payload preview for an approved payment run. NEVER SENT: Tempo makes no Ramp calls.

Field names and enums follow docs/ramp_api_snapshot.md (retrieved 2026-11-10):
- bank rails: PATCH /developer/v1/bills/{bill_id} with payment_date (the send date) and payment_method "ACH"
  (Ramp's request enum has no RTP; RTP is expected when paying from Ramp Checking, so the preview also gives
  the ACH-safe fallback send date). Only approved bills can be updated.
- bills in Needs review: POST /developer/v1/bills/{bill_id}/hold (beta); a reviewer-accepted bill gets
  POST /developer/v1/bills/{bill_id}/release (beta).
- card bills: no API lever (payment_date applies to non-card bills); Flex-style financing: no public API.
Wiring this to Ramp's sandbox is one adapter that sends these requests.
"""

from datetime import date

from tempo.assumptions import ACH_LEAD_BUSINESS_DAYS, ACH_LEAD_DISCOUNT_BUSINESS_DAYS
from tempo.business_days import subtract_business_days

BILLS = "/developer/v1/bills"
REQUEST_PAYMENT_METHODS = frozenset(
    {
        "ACH",
        "CARD",
        "CHECK",
        "CRYPTO_WALLET_TRANSFER",
        "DOMESTIC_WIRE",
        "INTERNATIONAL",
        "LOCAL_BANK_TRANSFER",
        "ONE_TIME_CARD",
        "ONE_TIME_CARD_DELIVERY",
        "PAID_MANUALLY",
        "SWIFT",
    }
)
PATCH_FIELDS = frozenset({"payment_date", "payment_method"})


def _patch(row: dict, auto: bool) -> dict:
    target = date.fromisoformat(row["discount_deadline"] if row["takes_discount"] else row["due_date"])
    lead = ACH_LEAD_DISCOUNT_BUSINESS_DAYS if row["takes_discount"] else ACH_LEAD_BUSINESS_DAYS
    request = {
        "method": "PATCH",
        "path": f"{BILLS}/{row['bill_id']}",
        "body": {"payment_date": row["send_date"], "payment_method": "ACH"},
    }
    notes = ["Only approved bills can be updated."]
    if row["rail"] == "RTP":
        notes.append(
            f"Planned as RTP from Ramp Checking. If Ramp routes standard ACH, send by "
            f"{subtract_business_days(target, lead).isoformat()} instead."
        )
    return {**_base(row, auto), "requests": [request], "notes": notes}


def _base(row: dict, auto: bool) -> dict:
    return {
        "bill_id": row["bill_id"],
        "vendor": row["vendor"],
        "invoice_number": row["invoice_number"],
        "option": row["option"],
        "amount_cents": row["amount_cents"],
        "auto_scheduled": auto,
    }


def bill_actions(row: dict, accepted_review: bool, auto: bool) -> dict:
    """The request(s) Tempo would send for one bill, or a note where the API has no lever."""
    if row["needs_review"] and not accepted_review:
        req = {
            "method": "POST",
            "path": f"{BILLS}/{row['bill_id']}/hold",
            "body": {"reason": f"Tempo: terms need review ({row.get('review_reason') or row['status']})"},
        }
        return {**_base(row, False), "requests": [req], "notes": ["Held until a person confirms the terms."]}
    release = []
    if accepted_review:
        release = [{"method": "POST", "path": f"{BILLS}/{row['bill_id']}/release", "body": {}}]
    if row["rail"] in ("RTP", "ACH"):
        action = _patch(row, auto)
        return {**action, "requests": release + action["requests"]}
    note = (
        "Card bills: the payment method is set when the bill is created and payment_date applies to non-card "
        "bills, so there is no API lever; schedule the card charge in Ramp."
        if row["rail"] == "CARD"
        else "Flex-style financing has no public API; arrange it in Ramp."
    )
    return {**_base(row, auto), "requests": release, "notes": [note]}


def payment_run(rows: list[dict], accepted: set[str], autonomy: dict, plan_hash: str) -> dict:
    """The full preview: one entry per bill, plus counts. Never sent."""
    threshold = int(autonomy.get("threshold_cents", 0))
    auto_mode = autonomy.get("mode") == "auto"
    actions = []
    for row in rows:
        auto = auto_mode and row["chip"] == "Verified" and row["amount_cents"] < threshold
        actions.append(bill_actions(row, row["bill_id"] in accepted, auto))
    requests = [r for a in actions for r in a["requests"]]
    return {
        "sent": False,
        "note": "Preview only. Tempo never calls Ramp's API.",
        "plan_hash": plan_hash,
        "autonomy": autonomy,
        "counts": {
            "bills": len(actions),
            "requests": len(requests),
            "patch": sum(r["method"] == "PATCH" for r in requests),
            "hold": sum(r["path"].endswith("/hold") for r in requests),
            "release": sum(r["path"].endswith("/release") for r in requests),
            "auto_scheduled": sum(a["auto_scheduled"] for a in actions),
        },
        "bills": actions,
    }
