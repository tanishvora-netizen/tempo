"""Deterministic reconciliation of parser and model readings (directive 7.4).

Authoritative source: the most recent email from the vendor's own domain that states terms (an override),
otherwise the invoice blocks. Emails from the buyer's domain never count.

Terms table (first matching row wins; R = distinct regex values in the authoritative source,
M = the model's value after quote verification):
    |R| >= 2                                  -> ambiguous_document   (review)
    |R| = 1, M verified and equal             -> verified             (accept)
    |R| = 1, M verified and different         -> conflict             (review, show both quotes)
    |R| = 1, M missing or unverified          -> regex_only           (accept; model flagged if it gave a value)
    |R| = 0, M verified                       -> model_verified       (accept)
    |R| = 0, M given but unverified           -> hallucination_flag   (review, model value rejected)
    |R| = 0, M missing                        -> sanity_fail          (review: no terms found)
Then on an accepted value: sanity rules -> sanity_fail; differs from the vendor's prior terms -> history_mismatch.
Sanity: 0 < discount <= 5%, discount_days < net_days, net_days in [0, 120], prox day in [1, 31], and a
discount needs a net term.
"""

from dataclasses import dataclass, replace

from tempo.assumptions import (
    CARD_SURCHARGE_SANITY_MAX,
    LATE_FEE_SANITY_MAX_BPS_PER_MONTH,
    MAX_DISCOUNT,
    MAX_NET_DAYS,
)
from tempo.extract.regex_parser import BlockParse, parse_block
from tempo.extract.verify import FieldCheck, as_record, verify_extraction
from tempo.llm.schemas import TermsExtraction
from tempo.models import EmailMessage, Invoice, LateFeeRecord, TermsRecord, Vendor
from tempo.money import BPS_PER_UNIT

ACCEPTED = frozenset({"verified", "regex_only", "model_verified"})
REVIEW = frozenset(
    {"conflict", "hallucination_flag", "ambiguous_document", "sanity_fail", "history_mismatch"}
)
MAX_PROX_DAY = 31


@dataclass(frozen=True)
class Evidence:
    """A highlighted span for the UI: where a value was read, and by whom."""

    source: str  # block id or email message id
    start: int
    end: int
    text: str
    origin: str  # "regex" or "model"


@dataclass(frozen=True)
class TermsDecision:
    status: str
    value: TermsRecord | None  # accepted terms, or None while in review
    proposed: TermsRecord | None  # what the table would accept before sanity and history checks
    regex_values: tuple[TermsRecord, ...]
    model_value: TermsRecord | None
    model_check: FieldCheck | None
    reason: str

    @property
    def needs_review(self) -> bool:
        return self.status in REVIEW


@dataclass(frozen=True)
class Reconciled:
    bill_id: str
    terms: TermsDecision
    late_fee: LateFeeRecord | None
    accepted_methods: tuple[str, ...]
    card_surcharge_bps: int
    card_discount_allowed: bool
    overridden_in_email: bool
    authoritative_source: str  # "invoice" or the overriding email's message id
    evidence: tuple[Evidence, ...]
    model_checks: dict[str, FieldCheck]
    provider_error: str | None


def reconcile(
    invoice: Invoice,
    vendor: Vendor,
    extraction: TermsExtraction | None,
    provider_error: str | None = None,
) -> Reconciled:
    """Apply the reconciliation table to one invoice."""
    doc = invoice.document
    block_parses = {b.id: parse_block(b.text) for b in doc.blocks}
    override = _overriding_email(doc.emails, vendor.domain)
    if override is not None:
        email_parse = parse_block(f"{override.subject}\n{override.body}")
        auth_parses = {override.id: email_parse}
    else:
        auth_parses = block_parses
    regex_values = _distinct_terms(auth_parses)
    invoice_values = _distinct_terms(block_parses)
    checks = verify_extraction(extraction, doc) if extraction is not None else {}
    late_fee = _late_fee(block_parses, checks.get("late_fee"))
    surcharge = _surcharge(block_parses, checks.get("surcharge"))
    terms = _with_fee_sanity(
        decide_terms(regex_values, checks.get("terms"), vendor.prior_terms), late_fee, surcharge
    )
    overridden = override is not None and bool(invoice_values) and set(invoice_values) != set(regex_values)
    all_parses = {**block_parses, **({override.id: auth_parses[override.id]} if override else {})}
    return Reconciled(
        bill_id=invoice.id,
        terms=terms,
        late_fee=late_fee if fee_problem(late_fee, 0) is None else None,
        accepted_methods=_methods(block_parses, checks.get("methods")),
        card_surcharge_bps=surcharge,
        card_discount_allowed=_card_discount(block_parses, checks.get("card_discount")),
        overridden_in_email=overridden,
        authoritative_source=override.id if override else "invoice",
        evidence=_evidence(all_parses, checks.get("terms")),
        model_checks=checks,
        provider_error=provider_error,
    )


def decide_terms(
    regex_values: tuple[TermsRecord, ...], model: FieldCheck | None, prior: TermsRecord | None
) -> TermsDecision:
    """The terms table, then sanity and history rules (see module docstring)."""
    m_value = model.model_value if model is not None else None
    m_verified = model is not None and model.verified
    status, value, reason = _table_row(regex_values, m_value, m_verified)
    proposed = value
    if value is not None:
        problem = sanity_problem(value)
        if problem:
            status, value, reason = "sanity_fail", None, problem
        elif prior is not None and as_record(prior) != value:
            status, value, reason = "history_mismatch", None, "differs from the vendor's terms on file"
    return TermsDecision(status, value, proposed, regex_values, m_value, model, reason)  # type: ignore[arg-type]


def fee_problem(late_fee: LateFeeRecord | None, surcharge_bps: int) -> str | None:
    """Sanity rules for the other fields: late fee <= 3% per month, card surcharge <= 4%."""
    if (
        late_fee is not None
        and late_fee.kind == "pct_month"
        and (late_fee.pct_month_bps or 0) > LATE_FEE_SANITY_MAX_BPS_PER_MONTH
    ):
        return f"late fee {late_fee.pct_month_bps / 100:g}%/month exceeds 3%/month"
    if surcharge_bps > CARD_SURCHARGE_SANITY_MAX * BPS_PER_UNIT:
        return f"card surcharge {surcharge_bps / 100:g}% exceeds 4%"
    return None


def _with_fee_sanity(
    terms: TermsDecision, late_fee: LateFeeRecord | None, surcharge_bps: int
) -> TermsDecision:
    """An accepted bill whose late fee or surcharge fails sanity goes to review too (directive 7.4)."""
    problem = fee_problem(late_fee, surcharge_bps)
    if problem is None or terms.status not in ACCEPTED:
        return terms
    return replace(terms, status="sanity_fail", value=None, reason=problem)


def _table_row(regex_values, m_value, m_verified) -> tuple[str, TermsRecord | None, str]:
    if len(regex_values) >= 2:
        return "ambiguous_document", None, "the document states more than one set of terms"
    if len(regex_values) == 1:
        (a,) = regex_values
        if m_verified and m_value != a:
            return "conflict", None, "parser and model disagree"
        if m_verified:
            return "verified", a, "parser and model agree"
        return "regex_only", a, "parser only; one unambiguous match"
    if m_verified:
        return "model_verified", m_value, "model quote verified and re-parsed"
    if m_value is not None:
        return "hallucination_flag", None, "model value not supported by its quote"
    return "sanity_fail", None, "no payment terms found"


def sanity_problem(t: TermsRecord) -> str | None:
    """Return why terms fail the sanity rules, or None."""
    if t.discount_bps is not None and not 0 < t.discount_bps <= MAX_DISCOUNT * BPS_PER_UNIT:
        return f"discount {t.discount_bps / 100:g}% is outside (0%, 5%]"
    if t.anchor == "prox":
        return None if t.prox_day and 1 <= t.prox_day <= MAX_PROX_DAY else "prox day missing or invalid"
    if t.net_days is None:
        return "a discount with no net term" if t.discount_bps else "no net term"
    if not 0 <= t.net_days <= MAX_NET_DAYS:
        return f"net {t.net_days} days is outside [0, {MAX_NET_DAYS}]"
    if t.discount_bps and (t.discount_days is None or t.discount_days >= t.net_days):
        return "discount window is not shorter than the net term"
    return None


def _overriding_email(emails: tuple[EmailMessage, ...], vendor_domain: str) -> EmailMessage | None:
    """Most recent message from the vendor's own domain that states terms."""
    vendor_msgs = [m for m in emails if m.sender.lower().endswith("@" + vendor_domain.lower())]
    for m in sorted(vendor_msgs, key=lambda m: m.sent_at, reverse=True):
        if parse_block(f"{m.subject}\n{m.body}").terms:
            return m
    return None


def _distinct_terms(parses: dict[str, BlockParse]) -> tuple[TermsRecord, ...]:
    values = {as_record(t) for p in parses.values() for t in p.distinct_terms()}
    return tuple(sorted(values, key=repr))


def _single(values: set) -> object | None:
    return next(iter(values)) if len(values) == 1 else None


def _late_fee(parses: dict[str, BlockParse], check: FieldCheck | None) -> LateFeeRecord | None:
    found = {
        LateFeeRecord(m.fee.kind, m.fee.pct_month_bps, m.fee.flat_cents)
        for p in parses.values()
        for m in p.late_fees
    }
    value = _single(found)
    if value is None and check is not None and check.verified:
        value = check.model_value
    return value  # type: ignore[return-value]


def _methods(parses: dict[str, BlockParse], check: FieldCheck | None) -> tuple[str, ...]:
    found = {m.method for p in parses.values() for m in p.methods}
    if not found and check is not None and check.verified:
        found = set(check.model_value)  # type: ignore[arg-type]
    return tuple(sorted(found)) or ("ACH",)


def _surcharge(parses: dict[str, BlockParse], check: FieldCheck | None) -> int:
    found = {m.bps for p in parses.values() for m in p.surcharges}
    if len(found) == 1:
        return next(iter(found))
    if not found and check is not None and check.verified:
        return int(check.model_value)  # type: ignore[arg-type]
    return max(found) if found else 0


def _card_discount(parses: dict[str, BlockParse], check: FieldCheck | None) -> bool:
    found = {m.allowed for p in parses.values() for m in p.card_discount}
    if found:
        return found == {True}
    return bool(check is not None and check.verified and check.model_value)


def _evidence(parses: dict[str, BlockParse], model: FieldCheck | None) -> tuple[Evidence, ...]:
    spans = [
        Evidence(src, m.span.start, m.span.end, m.span.text, "regex")
        for src, p in parses.items()
        for m in p.terms
    ]
    spans += [
        Evidence(src, m.span.start, m.span.end, m.span.text, "regex")
        for src, p in parses.items()
        for m in p.late_fees
    ]
    spans += [
        Evidence(src, m.span.start, m.span.end, m.span.text, "regex")
        for src, p in parses.items()
        for m in p.surcharges
    ]
    if model is not None and model.quote and model.source:
        spans.append(Evidence(model.source, -1, -1, model.quote, "model"))
    return tuple(spans)
