"""Ingest: run the provider and the parser over every invoice, reconcile, and produce plannable bills.

Bills whose terms need review are planned conservatively: no discount is taken on unverified terms, and the
due date is the earliest one any candidate reading implies (or the vendor's terms on file, else net 30).
"""

from dataclasses import dataclass, replace
from datetime import timedelta

from tempo.assumptions import EOM_ROLL_AFTER_25TH
from tempo.extract.due_dates import discount_deadline, due_date
from tempo.extract.reconcile import Reconciled, reconcile
from tempo.llm.provider import LLMProvider, ProviderError, extraction_call
from tempo.llm.schemas import TermsExtraction
from tempo.models import Dataset, Invoice, TermsRecord, Vendor
from tempo.optimize.options import PlannableBill

FALLBACK_NET_DAYS = 30  # ASSUMPTION: due date for a bill with no readable terms and none on file


@dataclass(frozen=True)
class IngestResult:
    reconciled: dict[str, Reconciled]
    extractions: dict[str, TermsExtraction | None]
    provider_name: str
    provider_model: str
    provider_errors: int


def ingest(dataset: Dataset, provider: LLMProvider | None) -> IngestResult:
    """Extract (model), parse (regex), and reconcile every invoice. Provider failures go to review paths."""
    vendors = {v.id: v for v in dataset.vendors}
    reconciled, extractions, errors = {}, {}, 0
    for inv in dataset.invoices:
        vendor = vendors[inv.vendor_id]
        ext, err = _extract(provider, inv, vendor, dataset.company.domain)
        errors += err is not None
        extractions[inv.id] = ext
        reconciled[inv.id] = reconcile(inv, vendor, ext, err)
    name = provider.name if provider is not None else "none"
    model = provider.model if provider is not None else "none"
    return IngestResult(reconciled, extractions, name, model, errors)


def _extract(provider: LLMProvider | None, inv: Invoice, vendor: Vendor, company_domain: str):
    if provider is None:
        return None, "no provider"
    try:
        return provider.extract(extraction_call(inv, vendor.domain, company_domain)), None
    except ProviderError as exc:
        return None, str(exc)


def planning_terms(
    r: Reconciled, vendor: Vendor, override: TermsRecord | None = None
) -> tuple[TermsRecord, bool]:
    """Terms the plan uses and whether its discount may be taken (only for accepted or human-approved terms)."""
    if override is not None:
        return override, True
    if r.terms.value is not None:
        return r.terms.value, True
    return _conservative_terms(r, vendor), False


def _conservative_terms(r: Reconciled, vendor: Vendor) -> TermsRecord:
    candidates = list(r.terms.regex_values)
    if vendor.prior_terms is not None:
        candidates.append(vendor.prior_terms)
    usable = [replace(c, discount_bps=None, discount_days=None) for c in candidates if _valid_net(c)]
    return usable[0] if usable else TermsRecord(None, None, FALLBACK_NET_DAYS, "invoice_date")


def _valid_net(t: TermsRecord) -> bool:
    return (t.anchor == "prox" and bool(t.prox_day)) or (t.net_days is not None and 0 <= t.net_days <= 120)


def plannable_bills(
    dataset: Dataset, ingest_result: IngestResult, overrides: dict[str, TermsRecord] | None = None
) -> tuple[PlannableBill, ...]:
    """Resolve every invoice into a PlannableBill (due date, deadline, card facts, review status)."""
    vendors = {v.id: v for v in dataset.vendors}
    overrides = overrides or {}
    out = []
    for inv in dataset.invoices:
        vendor = vendors[inv.vendor_id]
        r = ingest_result.reconciled[inv.id]
        out.append(_plannable(inv, vendor, r, overrides.get(inv.id), dataset.company.as_of))
    return tuple(out)


def _plannable(
    inv: Invoice, vendor: Vendor, r: Reconciled, override: TermsRecord | None, as_of
) -> PlannableBill:
    terms, usable = planning_terms(r, vendor, override)
    if not usable:
        terms = _earliest_due(inv, r, vendor, terms)
    due = max(due_date(inv.issued_at, terms, EOM_ROLL_AFTER_25TH), as_of)
    deadline = discount_deadline(inv.issued_at, terms, EOM_ROLL_AFTER_25TH) if terms.discount_bps else None
    return PlannableBill(
        id=inv.id,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        invoice_number=inv.invoice_number,
        issued_at=inv.issued_at,
        subtotal_cents=inv.subtotal_cents,
        tax_cents=inv.tax_cents,
        freight_cents=inv.freight_cents,
        total_cents=inv.total_cents,
        terms=terms,
        due_date=due,
        discount_deadline=deadline,
        late_fee=r.late_fee,
        accepts_card="CARD" in r.accepted_methods,
        surcharge_bps=r.card_surcharge_bps,
        card_discount_allowed=r.card_discount_allowed,
        rtp_eligible=vendor.rtp_eligible,
        is_new_vendor=vendor.is_new,
        discount_usable=usable,
        status="human_accepted" if override is not None else r.terms.status,
    )


def _earliest_due(inv: Invoice, r: Reconciled, vendor: Vendor, default: TermsRecord) -> TermsRecord:
    """Among all candidate readings, the one with the earliest due date (never pay a reviewed bill late)."""
    options = [default] + [
        replace(c, discount_bps=None, discount_days=None) for c in r.terms.regex_values if _valid_net(c)
    ]
    return min(options, key=lambda t: (due_date(inv.issued_at, t, EOM_ROLL_AFTER_25TH), repr(t)))


def days_between(a, b) -> int:
    return (b - a).days


__all__ = ["IngestResult", "ingest", "plannable_bills", "planning_terms", "timedelta"]
