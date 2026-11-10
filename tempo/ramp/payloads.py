"""Ramp API payload preview for an approved payment run. NEVER SENT: Tempo makes no Ramp calls.

Field names and enums follow docs/ramp_api_snapshot.md (retrieved 2026-11-10):
- bank rails: PATCH /developer/v1/bills/{bill_id} with payment_date (the send date) and payment_method "ACH"
  (Ramp's request enum has no RTP). An RTP-planned payment that an ACH can still deliver on time is previewed
  as that earlier ACH; one that only RTP can deliver gets no request and a "send by RTP in Ramp" note.
  Only approved bills can be updated.
- bills in Needs review: POST /developer/v1/bills/{bill_id}/hold (beta); a reviewer-accepted bill gets
  POST /developer/v1/bills/{bill_id}/release (beta).
- card bills: no API lever (payment_date applies to non-card bills); Flex-style financing: no public API.
Wiring this to Ramp's sandbox is one adapter that sends these requests.
"""

from datetime import date

from tempo.business_days import add_business_days, business_days_between, subtract_business_days
from tempo.optimize.options import ach_lead

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


def _target_and_lead(row: dict) -> tuple[date, int]:
    """The arrival target and the ACH lead time, from the same rule the option builder uses."""
    target = date.fromisoformat(row["discount_deadline"] if row["takes_discount"] else row["due_date"])
    return target, ach_lead(row["takes_discount"], bool(row.get("new_vendor")))


def _patch(row: dict, auto: bool) -> dict:
    """PATCH payment_date and payment_method for a bank payment Ramp's API can express.

    Ramp's request enum has no RTP, so a payment planned as RTP is previewed as the ACH that meets the same
    target: sent earlier by the ACH lead time. Payments with no such ACH date are handled by `_manual_rtp`.
    """
    send = date.fromisoformat(row["send_date"])
    notes = ["Only approved bills can be updated."]
    if row["rail"] == "RTP":
        target, lead = _target_and_lead(row)
        ach_send = subtract_business_days(target, lead)
        notes.append(
            f"Planned as RTP from Ramp Checking on {send.isoformat()}; the API can only request ACH, so this "
            f"sends ACH on {ach_send.isoformat()} ({business_days_between(ach_send, send)} business days earlier) to "
            f"arrive by {target.isoformat()}. Cash leaves earlier than in the certified plan; the buffer risk "
            "was not re-certified for that shift."
        )
        send = ach_send
    request = {
        "method": "PATCH",
        "path": f"{BILLS}/{row['bill_id']}",
        "body": {"payment_date": send.isoformat(), "payment_method": "ACH"},
    }
    return {**_base(row, auto), "requests": [request], "notes": notes, "bucket": "patch"}


def _manual_rtp(row: dict) -> dict:
    """No ACH date can meet the target from today: the payment must be sent by RTP in Ramp; no API request."""
    target, lead = _target_and_lead(row)
    arrives = add_business_days(date.fromisoformat(row["send_date"]), lead)
    note = (
        f"Send by RTP from Ramp Checking on {row['send_date']} in Ramp. Ramp's API cannot request RTP, and a "
        f"standard ACH sent today would arrive {arrives.isoformat()}, after {target.isoformat()}."
    )
    return {**_base(row, False), "requests": [], "notes": [note], "bucket": "manual_rtp"}


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
        return {
            **_base(row, False),
            "requests": [req],
            "notes": ["Held until a person confirms the terms."],
            "bucket": "hold",
        }
    release = []
    if accepted_review:
        release = [{"method": "POST", "path": f"{BILLS}/{row['bill_id']}/release", "body": {}}]
    if row["rail"] == "RTP" and row.get("rtp_dependent"):
        action = _manual_rtp(row)
        return {**action, "requests": release}
    if row["rail"] in ("RTP", "ACH"):
        action = _patch(row, auto)
        return {**action, "requests": release + action["requests"]}
    note = (
        "Card bills: the payment method is set when the bill is created and payment_date applies to non-card "
        "bills, so there is no API lever; schedule the card charge in Ramp."
        if row["rail"] == "CARD"
        else "Flex-style financing has no public API; arrange it in Ramp."
    )
    return {**_base(row, auto), "requests": release, "notes": [note], "bucket": "no_api_lever"}


def auto_scheduled_ids(rows: list[dict], autonomy: dict) -> set[str]:
    """Verified bills under the threshold, where the threshold applies to each vendor's total in a week (so an
    invoice split into small pieces does not slip under it). Ramp's own approval chain and vendor bank
    verification still gate every payment; Tempo only sets date and rail."""
    if autonomy.get("mode") != "auto":
        return set()
    threshold = int(autonomy.get("threshold_cents", 0))
    weekly: dict[tuple[str, int, int], int] = {}
    for r in rows:
        year, week, _ = date.fromisoformat(r["send_date"]).isocalendar()
        weekly[(r["vendor_id"], year, week)] = weekly.get((r["vendor_id"], year, week), 0) + r["amount_cents"]
    ok = set()
    for r in rows:
        year, week, _ = date.fromisoformat(r["send_date"]).isocalendar()
        if (
            r["chip"] == "Verified"
            and not r["needs_review"]
            and weekly[(r["vendor_id"], year, week)] < threshold
        ):
            ok.add(r["bill_id"])
    return ok


def payment_run(rows: list[dict], accepted: set[str], autonomy: dict, plan_hash: str) -> dict:
    """The full preview: one entry per bill, plus counts. Never sent."""
    auto_ids = auto_scheduled_ids(rows, autonomy)
    actions = [bill_actions(row, row["bill_id"] in accepted, row["bill_id"] in auto_ids) for row in rows]
    requests = [r for a in actions for r in a["requests"]]
    return {
        "sent": False,
        "note": "Preview only. Tempo never calls Ramp's API. Ramp's own bill approval chain and vendor bank "
        "verification still gate payment; Tempo only sets date and rail.",
        "plan_hash": plan_hash,
        "autonomy": autonomy,
        "counts": {
            "bills": len(actions),
            "requests": len(requests),
            "patch": sum(r["method"] == "PATCH" for r in requests),
            "hold": sum(r["path"].endswith("/hold") for r in requests),
            "release": sum(r["path"].endswith("/release") for r in requests),
            "auto_scheduled": sum(a["auto_scheduled"] for a in actions),
            "manual_rtp": sum(a.get("bucket") == "manual_rtp" for a in actions),
        },
        "bills": actions,
    }
