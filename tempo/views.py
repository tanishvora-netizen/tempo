"""Read-only views for the API: bill documents with highlighted evidence, Needs-review items, assumptions.

No FastAPI imports; the routes in app/main.py call these.
"""

import re
from dataclasses import asdict
from pathlib import Path

from tempo.extract.evidence import locate_quote
from tempo.extract.reconcile import Reconciled
from tempo.extract.verify import source_texts
from tempo.models import Dataset, Invoice, TermsRecord
from tempo.precompute import suggested_terms

ASSUMPTIONS_FILE = Path(__file__).parent / "assumptions.py"
_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]+)(?::[^=]+)? = (.+?)\s+#\s*(.*)$")
_CONTINUATION = re.compile(r"^#\s{2,}(.*)$")


def assumptions_catalog() -> list[dict]:
    """Every documented parameter in assumptions.py: name, value as written, label, and its comment."""
    out: list[dict] = []
    for line in ASSUMPTIONS_FILE.read_text().splitlines():
        m = _ASSIGN.match(line)
        if m:
            name, value, comment = m.groups()
            label = "SOURCED" if "SOURCED" in comment else "ASSUMPTION" if "ASSUMPTION" in comment else ""
            out.append({"name": name, "value": value, "label": label, "comment": comment})
            continue
        c = _CONTINUATION.match(line.strip())
        if c and out:
            out[-1]["comment"] += " " + c.group(1)
    return out


def terms_dict(t: TermsRecord | None) -> dict | None:
    return None if t is None else asdict(t)


def evidence_spans(invoice: Invoice, r: Reconciled) -> list[dict]:
    """Regex spans (exact offsets) plus the model's quote, located in its source text."""
    texts = source_texts(invoice.document)
    spans = []
    for e in r.evidence:
        if e.origin == "regex":
            spans.append(
                {"source": e.source, "start": e.start, "end": e.end, "text": e.text, "origin": "regex"}
            )
            continue
        located = _locate_anywhere(e.text, e.source, texts)
        if located is not None:
            spans.append({**located, "text": e.text, "origin": "model"})
    return spans


def _locate_anywhere(quote: str, source: str, texts: dict[str, str]) -> dict | None:
    order = [source, *[s for s in texts if s != source]]
    for src in order:
        if src in texts:
            span = locate_quote(quote, texts[src])
            if span is not None:
                return {"source": src, "start": span.start, "end": span.end}
    return None


def document_view(invoice: Invoice) -> dict:
    doc = invoice.document
    return {
        "blocks": [{"id": b.id, "kind": b.kind, "text": b.text} for b in doc.blocks],
        "emails": [
            {
                "id": m.id,
                "sender": m.sender,
                "sent_at": m.sent_at.isoformat(),
                "subject": m.subject,
                "text": f"{m.subject}\n{m.body}",
            }
            for m in doc.emails
        ],
    }


def reconciliation_view(r: Reconciled) -> dict:
    check = r.model_checks.get("terms")
    return {
        "status": r.terms.status,
        "reason": r.terms.reason,
        "regex_values": [asdict(v) for v in r.terms.regex_values],
        "model_value": terms_dict(r.terms.model_value),
        "model_quote": check.quote if check else None,
        "model_source": check.source if check else None,
        "model_check": check.reason if check else ("no model output" if r.provider_error else None),
        "proposed": terms_dict(r.terms.proposed),
        "accepted": terms_dict(r.terms.value),
        "authoritative_source": r.authoritative_source,
        "overridden_in_email": r.overridden_in_email,
        "provider_error": r.provider_error,
        "late_fee": asdict(r.late_fee) if r.late_fee else None,
        "accepted_methods": list(r.accepted_methods),
        "card_surcharge_bps": r.card_surcharge_bps,
        "card_discount_allowed": r.card_discount_allowed,
    }


def bill_detail(dataset: Dataset, reconciled: dict[str, Reconciled], row: dict) -> dict:
    invoice = next(i for i in dataset.invoices if i.id == row["bill_id"])
    r = reconciled[invoice.id]
    return {
        **row,
        "tag": invoice.tag,
        "document": document_view(invoice),
        "evidence": evidence_spans(invoice, r),
        "reconciliation": reconciliation_view(r),
    }


def review_items(
    dataset: Dataset, reconciled: dict[str, Reconciled], rows: list[dict], effects: dict
) -> list[dict]:
    """Every bill whose terms need a person, with both readings, highlighted quotes, and the suggestion."""
    vendors = {v.id: v for v in dataset.vendors}
    by_bill = {e["bill_id"]: e for e in effects.get("effects", [])}
    items = []
    for row in rows:
        r = reconciled[row["bill_id"]]
        if not r.terms.needs_review:
            continue
        invoice = next(i for i in dataset.invoices if i.id == row["bill_id"])
        prior = vendors[invoice.vendor_id].prior_terms
        items.append(
            {
                **bill_detail(dataset, reconciled, row),
                "prior_terms": terms_dict(prior),
                "suggested": terms_dict(suggested_terms(r, prior)),
                "effect": by_bill.get(row["bill_id"]),
            }
        )
    return items
