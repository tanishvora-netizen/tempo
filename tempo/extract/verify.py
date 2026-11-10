"""Verify the model's extraction against the document: is each quote really there, and does it say what the
model claims it says?

For each field group: (1) the quote must appear in its source block (or, failing that, anywhere in the
document) after whitespace normalization; (2) the quote is re-parsed with the deterministic parser (number
words normalized first); (3) the model's value must equal a value parsed from its own quote. Anything else is
not verified, and an unverified model value never reaches the plan.
"""

from collections.abc import Callable
from dataclasses import dataclass

from tempo.extract.evidence import quote_in_source
from tempo.extract.regex_parser import PaymentTerms, parse_block
from tempo.llm.schemas import TermsExtraction
from tempo.models import InvoiceDocument, LateFeeRecord, TermsRecord

MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class FieldCheck:
    group: str  # terms | late_fee | methods | surcharge | card_discount
    model_value: object | None
    quote: str | None
    source: str | None
    verified: bool
    reason: str  # ok | no_value | quote_not_found | value_mismatch


def as_record(t: PaymentTerms | TermsRecord) -> TermsRecord:
    """Canonical comparable form: drop fields that do not apply to the anchor."""
    has_discount = bool(t.discount_bps)
    return TermsRecord(
        discount_bps=t.discount_bps if has_discount else None,
        discount_days=t.discount_days if has_discount else None,
        net_days=None if t.anchor == "prox" else t.net_days,
        anchor=t.anchor,
        prox_day=t.prox_day if t.anchor == "prox" else None,
    )


def source_texts(doc: InvoiceDocument) -> dict[str, str]:
    """Block id or email message id -> its text."""
    texts = {b.id: b.text for b in doc.blocks}
    texts.update({m.id: f"{m.subject}\n{m.body}" for m in doc.emails})
    return texts


def quote_found(quote: str | None, source: str | None, doc: InvoiceDocument) -> bool:
    if not quote:
        return False
    texts = source_texts(doc)
    if source in texts and quote_in_source(quote, texts[source]):
        return True
    return any(quote_in_source(quote, t) for t in texts.values())


def model_terms(ext: TermsExtraction) -> TermsRecord | None:
    """The model's terms reading as a canonical record (percent -> basis points)."""
    if ext.net_days is None and ext.anchor is None and ext.prox_day is None and ext.discount_pct is None:
        return None
    bps = round(ext.discount_pct * 100) if ext.discount_pct else None
    return as_record(
        TermsRecord(bps, ext.discount_days, ext.net_days, ext.anchor or "invoice_date", ext.prox_day)
    )


def model_late_fee(ext: TermsExtraction) -> LateFeeRecord | None:
    if ext.late_fee_kind is None or ext.late_fee_value is None:
        return None
    if ext.late_fee_kind == "flat":
        return LateFeeRecord("flat", None, round(ext.late_fee_value * 100))
    monthly = ext.late_fee_value / (MONTHS_PER_YEAR if ext.late_fee_kind == "pct_year" else 1)
    return LateFeeRecord("pct_month", round(monthly * 100), None)


def verify_extraction(ext: TermsExtraction, doc: InvoiceDocument) -> dict[str, FieldCheck]:
    """Check every field group of the model's answer against the document."""
    surcharge = round(ext.card_surcharge_pct * 100) if ext.card_surcharge_pct else None
    methods = frozenset(ext.accepted_methods) or None
    return {
        "terms": _check("terms", model_terms(ext), ext.terms_quote, ext.terms_source, doc, _reparse_terms),
        "late_fee": _check(
            "late_fee", model_late_fee(ext), ext.late_fee_quote, ext.late_fee_source, doc, _reparse_late_fee
        ),
        "methods": _check("methods", methods, ext.methods_quote, ext.methods_source, doc, _reparse_methods),
        "surcharge": _check(
            "surcharge", surcharge, ext.surcharge_quote, ext.surcharge_source, doc, _reparse_surcharge
        ),
        "card_discount": _check(
            "card_discount",
            ext.card_discount_allowed,
            ext.card_discount_quote,
            ext.card_discount_source,
            doc,
            _reparse_card_discount,
        ),
    }


def _check(
    group: str,
    value: object | None,
    quote: str | None,
    source: str | None,
    doc: InvoiceDocument,
    reparse: Callable[[str], set],
) -> FieldCheck:
    if value is None:
        return FieldCheck(group, None, quote, source, False, "no_value")
    if not quote_found(quote, source, doc):
        return FieldCheck(group, value, quote, source, False, "quote_not_found")
    ok = value in reparse(quote)
    return FieldCheck(group, value, quote, source, ok, "ok" if ok else "value_mismatch")


def _reparse_terms(quote: str) -> set[TermsRecord]:
    return {as_record(t) for t in parse_block(quote).distinct_terms()}


def _reparse_late_fee(quote: str) -> set[LateFeeRecord]:
    return {
        LateFeeRecord(m.fee.kind, m.fee.pct_month_bps, m.fee.flat_cents) for m in parse_block(quote).late_fees
    }


def _reparse_methods(quote: str) -> set[frozenset[str]]:
    return {frozenset(m.method for m in parse_block(quote).methods)}


def _reparse_surcharge(quote: str) -> set[int]:
    return {m.bps for m in parse_block(quote).surcharges}


def _reparse_card_discount(quote: str) -> set[bool]:
    return {m.allowed for m in parse_block(quote).card_discount}
