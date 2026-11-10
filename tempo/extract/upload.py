"""Read terms from an uploaded invoice PDF: text via pypdf, then the same parser, model, and reconciliation.

Uploads never change the plan; they show what Tempo would read. Limits keep a public demo safe: at most
MAX_BYTES and MAX_PAGES, parsed in memory, never written to disk. On the hosted demo there is no local model,
so the model reading is reported as unavailable and the parser result is labeled "parser only".
"""

import io
from dataclasses import asdict
from datetime import date

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from tempo.extract.reconcile import reconcile
from tempo.extract.regex_parser import parse_block
from tempo.llm.provider import LLMProvider, ProviderError, extraction_call
from tempo.models import DocumentBlock, Invoice, InvoiceDocument, Vendor

MAX_BYTES = 2_000_000
MAX_PAGES = 10
MAX_CHARS = 20_000
PDF_MAGIC = b"%PDF-"


class UploadRejected(ValueError):
    """The file is not a small, readable PDF with text."""


def pdf_text(data: bytes) -> str:
    """Extract text from a small PDF, enforcing size, page, and length limits."""
    if len(data) > MAX_BYTES:
        raise UploadRejected(f"file is larger than {MAX_BYTES // 1_000_000} MB")
    if not data.startswith(PDF_MAGIC):
        raise UploadRejected("not a PDF")
    try:
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PAGES:
            raise UploadRejected(f"more than {MAX_PAGES} pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, UploadRejected):
            raise
        raise UploadRejected("the PDF could not be read") from exc
    text = text.strip()[:MAX_CHARS]
    if not text:
        raise UploadRejected("no text found (scanned PDFs need OCR, which is out of scope)")
    return text


def read_upload(data: bytes, provider: LLMProvider | None, as_of: date) -> dict:
    """Parse and reconcile an uploaded invoice; returns the same reconciliation view as Needs review."""
    text = pdf_text(data)
    doc = InvoiceDocument((DocumentBlock("upload", "body", text),), ())
    invoice = Invoice("upload", "upload", "uploaded", as_of, "USD", (), 0, 0, 0, 0, doc, "clean")
    vendor = Vendor("upload", "Uploaded vendor", "uploaded.example", "unknown", False, False, True, None)
    extraction, error = None, None
    if provider is not None:
        try:
            extraction = provider.extract(extraction_call(invoice, vendor.domain, "buyer.example"))
        except ProviderError as exc:
            error = f"model unavailable here: {exc}"
    r = reconcile(invoice, vendor, extraction, error)
    spans = [{"start": m.span.start, "end": m.span.end, "text": m.span.text} for m in parse_block(text).terms]
    return {
        "text": text,
        "status": r.terms.status,
        "reason": r.terms.reason,
        "terms": None if r.terms.value is None else asdict(r.terms.value),
        "regex_values": [asdict(v) for v in r.terms.regex_values],
        "model_value": None if r.terms.model_value is None else asdict(r.terms.model_value),
        "model_check": r.model_checks["terms"].reason if "terms" in r.model_checks else error,
        "late_fee": None if r.late_fee is None else asdict(r.late_fee),
        "accepted_methods": list(r.accepted_methods),
        "card_surcharge_bps": r.card_surcharge_bps,
        "evidence": spans,
        "provider": getattr(provider, "name", "none"),
    }
