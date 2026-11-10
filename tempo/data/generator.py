"""Seeded synthetic dataset for Tempo. ALL DATA HERE IS SYNTHETIC; every name is fictional.

A fictional mid-market manufacturer (Kestrel Ridge Manufacturing) with ~200 open bills from 40 vendors over
13 weeks, 25 customers with payment histories and open receivables, scheduled billings, and fixed outflows
(payroll, rent, debt service, software, insurance, taxes). Invoice documents vary in layout and include
tagged hard cases for the extraction eval; ground truth is written alongside.

Bills issued after the as-of date stand for recurring or PO-backed invoices already entered in Bill Pay
(an ASSUMPTION stated in the README and UI).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np

from tempo.assumptions import AS_OF, HORIZON_DAYS, SEED
from tempo.business_days import next_business_day, previous_business_day
from tempo.data.customers import generate_customers
from tempo.data.invoice_text import RenderSpec, render_document
from tempo.data.names import COMPANY_DOMAIN, COMPANY_NAME, LINE_ITEMS
from tempo.data.vendors import VendorProfile, generate_vendors
from tempo.extract.due_dates import due_date
from tempo.models import (
    Company,
    Dataset,
    FixedOutflow,
    HardCaseTag,
    Invoice,
    LineItem,
    TermsRecord,
    TermsTruth,
)

ISSUE_WINDOW = (-28, 60)  # issue dates relative to AS_OF, in days. ASSUMPTION.
BUFFER_CENTS = 50_000_000  # $500,000 operating buffer. ASSUMPTION (CFO setting).
DEFAULT_STARTING_CASH_CENTS = 200_000_000  # $2.0M before calibration (scripts/calibrate_cash.py).
AMPLE_EXTRA_CASH_CENTS = 600_000_000  # the "ample" regime adds $6M so every positive option is affordable.
TAX_RATES = (0.0625, 0.07, 0.0725, 0.0825)
HARD_CASE_COUNTS = {"injection": 1, "footer_conflict": 5, "email_override": 5, "prose_terms": 6, "ocr_noise": 8}
EMAIL_ONLY_SHARE = 0.20
PAYROLL_CENTS = 61_000_000
YEAR_END_BONUS_CENTS = 18_000_000


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = SEED
    regime: str = "demo"  # "demo" or "ample"
    starting_cash_cents: int = DEFAULT_STARTING_CASH_CENTS


@dataclass(frozen=True)
class _BaseBill:
    profile: VendorProfile
    issued_at: date
    invoice_number: str
    bill_id: str


def generate(config: GeneratorConfig = GeneratorConfig()) -> Dataset:
    """Build the full synthetic dataset deterministically from `config.seed`."""
    vendor_ss, bill_ss, text_ss, customer_ss = np.random.SeedSequence(config.seed).spawn(4)
    profiles = generate_vendors(np.random.default_rng(vendor_ss))
    bill_rng = np.random.default_rng(bill_ss)
    bases = _base_bills(bill_rng, profiles)
    tags = _assign_tags(bill_rng, bases)
    text_rng = np.random.default_rng(text_ss)
    invoices, truth = _render_all(bill_rng, text_rng, bases, tags)
    customers, customer_truth = generate_customers(np.random.default_rng(customer_ss), AS_OF, HORIZON_DAYS)
    cash = config.starting_cash_cents + (AMPLE_EXTRA_CASH_CENTS if config.regime == "ample" else 0)
    company = Company(
        name=COMPANY_NAME,
        domain=COMPANY_DOMAIN,
        as_of=AS_OF,
        horizon_days=HORIZON_DAYS,
        starting_cash_cents=cash,
        buffer_cents=BUFFER_CENTS,
        funding_account="ramp_checking",
    )
    return Dataset(
        company=company,
        vendors=tuple(p.vendor for p in profiles),
        invoices=invoices,
        customers=customers,
        fixed_outflows=fixed_outflows(AS_OF, HORIZON_DAYS),
        truth=truth,
        customer_truth=customer_truth,
        seed=config.seed,
        regime=config.regime,
    )


def _base_bills(rng: np.random.Generator, profiles: tuple[VendorProfile, ...]) -> list[_BaseBill]:
    horizon_end = AS_OF + timedelta(days=HORIZON_DAYS - 1)
    bills: list[_BaseBill] = []
    for p in profiles:
        seq = int(rng.integers(1000, 90000))
        issued = AS_OF + timedelta(days=ISSUE_WINDOW[0] + int(rng.integers(0, p.cadence_days)))
        while issued <= AS_OF + timedelta(days=ISSUE_WINDOW[1]):
            due = due_date(issued, p.terms)
            if AS_OF <= due <= horizon_end:
                seq += 1
                number = f"{issued.month}/{issued.day}/{issued.year}" if p.date_style_numbers else f"{p.invoice_prefix}-{seq}"
                bills.append(_BaseBill(p, issued, number, str(uuid.UUID(bytes=rng.bytes(16), version=4))))
            issued += timedelta(days=p.cadence_days + int(rng.integers(-2, 3)))
    return sorted(bills, key=lambda b: (b.issued_at, b.profile.vendor.id))


def _assign_tags(rng: np.random.Generator, bases: list[_BaseBill]) -> list[HardCaseTag]:
    tags: list[HardCaseTag | None] = [None] * len(bases)

    def pick(tag: HardCaseTag, count: int, eligible) -> None:
        pool = [i for i, b in enumerate(bases) if tags[i] is None and eligible(b.profile)]
        for i in rng.choice(pool, size=min(count, len(pool)), replace=False):
            tags[int(i)] = tag

    def standard(p: VendorProfile) -> bool:
        return p.terms.anchor == "invoice_date" and not p.date_style_numbers and p.terms.discount_bps != 50

    pick("injection", HARD_CASE_COUNTS["injection"], lambda p: standard(p) and p.terms.discount_bps == 200 and not p.vendor.is_new)
    pick("footer_conflict", HARD_CASE_COUNTS["footer_conflict"], lambda p: standard(p) and p.terms.discount_bps is None and p.terms.net_days == 30)
    pick("email_override", HARD_CASE_COUNTS["email_override"], lambda p: standard(p) and not p.vendor.is_new)
    pick("prose_terms", HARD_CASE_COUNTS["prose_terms"], lambda p: standard(p) and p.terms.discount_bps is not None)
    pick("ocr_noise", HARD_CASE_COUNTS["ocr_noise"], lambda p: p.terms.anchor != "receipt")
    pick("email_only", round(EMAIL_ONLY_SHARE * len(bases)), lambda p: True)
    return [t if t is not None else _structural_tag(bases[i].profile) for i, t in enumerate(tags)]


def _structural_tag(p: VendorProfile) -> HardCaseTag:
    if p.date_style_numbers:
        return "date_lookalike"
    if p.terms.discount_bps == 50:
        return "fraction"
    if p.terms.anchor in ("eom", "prox"):
        return "eom_prox"
    if p.surcharge_bps:
        return "surcharge_text"
    return "clean"


def _override_terms(old: TermsRecord) -> TermsRecord:
    """New terms announced by email: 1/10 on the same net days, or 2/10 if the vendor already offered 1/10."""
    bps = 200 if old.discount_bps == 100 and old.discount_days == 10 else 100
    return replace(old, discount_bps=bps, discount_days=10, net_days=old.net_days or 30)


def _line_items(rng: np.random.Generator, p: VendorProfile, subtotal_target: float) -> tuple[LineItem, ...]:
    catalog = LINE_ITEMS[p.vendor.category]
    k = int(rng.integers(1, min(4, len(catalog)) + 1))
    parts = rng.dirichlet(np.full(k, 3.0)) * subtotal_target
    items = []
    for desc, part in zip(rng.choice(catalog, size=k, replace=False), parts, strict=True):
        qty = int(rng.integers(1, 40))
        unit = max(100, int(round(part * 100 / qty)))
        items.append(LineItem(str(desc), qty, unit, unit * qty))
    return tuple(items)


def _render_all(
    bill_rng: np.random.Generator,
    text_rng: np.random.Generator,
    bases: list[_BaseBill],
    tags: list[HardCaseTag],
) -> tuple[tuple[Invoice, ...], dict[str, TermsTruth]]:
    invoices, truth = [], {}
    for b, tag in zip(bases, tags, strict=True):
        invoice, t = _render_one(bill_rng, text_rng, b, tag)
        invoices.append(invoice)
        truth[invoice.id] = t
    return tuple(invoices), truth


def _render_one(
    bill_rng: np.random.Generator, text_rng: np.random.Generator, b: _BaseBill, tag: HardCaseTag
) -> tuple[Invoice, TermsTruth]:
    p = b.profile
    items = _line_items(bill_rng, p, float(bill_rng.lognormal(np.log(p.median_subtotal), p.log_sd)))
    subtotal = sum(li.amount_cents for li in items)
    vendor_num = int(p.vendor.id[-3:])
    tax_rate = TAX_RATES[vendor_num % 4] if p.vendor.sells_goods and vendor_num % 2 == 0 else 0.0
    tax = int(round(subtotal * tax_rate))
    freight = int(round(subtotal * bill_rng.uniform(0.01, 0.03) / 100)) * 100 if p.vendor.sells_goods and vendor_num % 3 else 0
    true_terms = _override_terms(p.terms) if tag == "email_override" else p.terms
    shown = None if tag == "email_only" else p.terms
    email_terms = true_terms if tag in ("email_only", "email_override") else None
    footer_conflict = replace(p.terms, net_days=45) if tag == "footer_conflict" else None
    spec = RenderSpec(
        vendor_name=p.vendor.name,
        vendor_domain=p.vendor.domain,
        template=p.template,
        invoice_number=b.invoice_number,
        issued_at=b.issued_at,
        line_items=items,
        subtotal_cents=subtotal,
        tax_cents=tax,
        tax_rate_text=f"{tax_rate * 100:g}%",
        freight_cents=freight,
        total_cents=subtotal + tax + freight,
        shown_terms=shown,
        email_terms=email_terms,
        late_fee=p.late_fee,
        late_fee_annual=p.late_fee_annual,
        methods=p.methods,
        surcharge_bps=p.surcharge_bps,
        card_discount_allowed=p.card_discount_allowed,
        tag=tag,
        footer_conflict_terms=footer_conflict,
    )
    invoice = Invoice(
        id=b.bill_id,
        vendor_id=p.vendor.id,
        invoice_number=b.invoice_number,
        issued_at=b.issued_at,
        currency_code="USD",
        line_items=items,
        subtotal_cents=subtotal,
        tax_cents=tax,
        freight_cents=freight,
        total_cents=subtotal + tax + freight,
        document=render_document(spec, text_rng),
        tag=tag,
    )
    truth = TermsTruth(
        terms=true_terms,
        late_fee=p.late_fee,
        accepted_methods=p.methods,
        card_surcharge_bps=p.surcharge_bps if "CARD" in p.methods else 0,
        card_discount_allowed=p.card_discount_allowed,
        terms_overridden_in_email=tag == "email_override",
        expect_review=tag in ("footer_conflict", "injection", "email_override"),
    )
    return invoice, truth


def fixed_outflows(as_of: date, horizon_days: int) -> tuple[FixedOutflow, ...]:
    """Deterministic outflows: biweekly payroll, rent, debt service, software, insurance, taxes."""
    end = as_of + timedelta(days=horizon_days - 1)
    out: list[FixedOutflow] = []
    payday = date(2026, 11, 13)
    while payday <= end:
        amount = PAYROLL_CENTS + (YEAR_END_BONUS_CENTS if payday == date(2026, 12, 11) else 0)
        note = "Biweekly payroll" + (" incl. year-end bonus" if amount > PAYROLL_CENTS else "")
        out.append(FixedOutflow(previous_business_day(payday), amount, "payroll", note))
        payday += timedelta(days=14)
    for month_start in _month_starts(as_of, end):
        out.append(FixedOutflow(next_business_day(month_start), 9_200_000, "rent", "Facility lease"))
        out.append(FixedOutflow(next_business_day(month_start.replace(day=15)), 13_500_000, "debt_service", "Term loan payment"))
        out.append(FixedOutflow(next_business_day(month_start.replace(day=5)), 3_800_000, "software", "ERP and software subscriptions"))
    out.append(FixedOutflow(date(2026, 11, 16), 13_500_000, "debt_service", "Term loan payment"))
    out.append(FixedOutflow(date(2026, 12, 1), 6_400_000, "insurance", "Quarterly insurance premium"))
    out.append(FixedOutflow(date(2027, 1, 15), 31_000_000, "taxes", "Q4 estimated income tax"))
    return tuple(sorted((o for o in out if as_of <= o.on <= end), key=lambda o: (o.on, o.category)))


def _month_starts(start: date, end: date) -> list[date]:
    months, d = [], date(start.year, start.month, 1)
    while d <= end:
        nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
        if nxt > start:
            months.append(nxt)
        d = nxt
    return [m for m in months if m <= end]
