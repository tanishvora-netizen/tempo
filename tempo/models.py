"""Tempo's data model: plain frozen dataclasses.

Two groups:
1. Input records produced by the synthetic generator (company, vendors, invoices with their documents,
   customers and receivables, fixed outflows, ground truth).
2. Ramp-shaped records. `RampBill` mirrors the fields of Ramp's developer-API bill object where one
   exists (see docs/ramp_api_snapshot.md); `DiscountTerms`, `PaymentOption`, and `Decision` are
   Tempo additions (discount terms would live in Ramp's Custom Records API).

Money is integer cents; rates in the extraction layer are integer basis points.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Anchor = Literal["invoice_date", "eom", "prox", "receipt"]
BlockKind = Literal["header", "body", "payment_box", "footer"]
Method = Literal["ACH", "CARD", "CHECK", "WIRE"]
Segment = Literal["prompt", "slow", "erratic"]
HardCaseTag = Literal[
    "clean",
    "eom_prox",
    "email_only",
    "email_override",
    "prose_terms",
    "date_lookalike",
    "fraction",
    "surcharge_text",
    "footer_conflict",
    "ocr_noise",
    "injection",
]
TermsSource = Literal["INVOICE", "EMAIL", "NEGOTIATED"]


# --- Generator inputs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Company:
    name: str
    domain: str
    as_of: date
    horizon_days: int
    starting_cash_cents: int
    buffer_cents: int
    funding_account: Literal["ramp_checking", "external_bank"]


@dataclass(frozen=True)
class FixedOutflow:
    on: date
    amount_cents: int
    category: Literal["payroll", "rent", "debt_service", "software", "insurance", "taxes"]
    description: str


@dataclass(frozen=True)
class TermsRecord:
    """A vendor's payment terms in canonical form (ground truth, prior terms on file, or extracted)."""

    discount_bps: int | None
    discount_days: int | None
    net_days: int | None
    anchor: Anchor
    prox_day: int | None = None


@dataclass(frozen=True)
class LateFeeRecord:
    kind: Literal["pct_month", "flat"]
    pct_month_bps: int | None
    flat_cents: int | None


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    domain: str
    category: str
    sells_goods: bool
    rtp_eligible: bool
    is_new: bool
    prior_terms: TermsRecord | None  # terms on file from earlier bills; None for new vendors


@dataclass(frozen=True)
class DocumentBlock:
    id: str  # e.g. "header", "payment_box", "footer", "body"
    kind: BlockKind
    text: str


@dataclass(frozen=True)
class EmailMessage:
    id: str  # message id, used as the source_block for quotes from email
    sender: str
    sent_at: datetime
    subject: str
    body: str


@dataclass(frozen=True)
class InvoiceDocument:
    blocks: tuple[DocumentBlock, ...]
    emails: tuple[EmailMessage, ...]

    def full_text(self) -> str:
        """All blocks then all emails, in order, as one string (what a reviewer would read)."""
        parts = [b.text for b in self.blocks]
        parts += [
            f"From: {m.sender}\nSent: {m.sent_at.isoformat()}\nSubject: {m.subject}\n\n{m.body}"
            for m in self.emails
        ]
        return "\n\n".join(parts)


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int


@dataclass(frozen=True)
class Invoice:
    """An open bill as ingested: document plus the amounts printed on it."""

    id: str
    vendor_id: str
    invoice_number: str
    issued_at: date
    currency_code: str
    line_items: tuple[LineItem, ...]
    subtotal_cents: int
    tax_cents: int
    freight_cents: int
    total_cents: int
    document: InvoiceDocument
    tag: HardCaseTag


@dataclass(frozen=True)
class TermsTruth:
    """Ground truth for one invoice's extraction fields (synthetic, written by the generator)."""

    terms: TermsRecord
    late_fee: LateFeeRecord | None
    accepted_methods: tuple[Method, ...]
    card_surcharge_bps: int
    card_discount_allowed: bool
    terms_overridden_in_email: bool
    expect_review: bool  # documents that a careful clerk would escalate (conflicts, injection)


@dataclass(frozen=True)
class PaymentRecord:
    invoice_date: date
    paid_date: date
    amount_cents: int


@dataclass(frozen=True)
class Receivable:
    id: str
    customer_id: str
    issued_at: date
    amount_cents: int


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    segment: Segment
    history: tuple[PaymentRecord, ...]
    open_receivables: tuple[Receivable, ...]
    scheduled_billings: tuple[Receivable, ...]


@dataclass(frozen=True)
class CustomerTruth:
    """The generator's true days-to-pay law for a customer (used only for robustness evaluation)."""

    customer_id: str
    mu: float  # mean of log days-to-pay
    sigma: float  # std of log days-to-pay


@dataclass(frozen=True)
class Dataset:
    company: Company
    vendors: tuple[Vendor, ...]
    invoices: tuple[Invoice, ...]
    customers: tuple[Customer, ...]
    fixed_outflows: tuple[FixedOutflow, ...]
    truth: dict[str, TermsTruth]  # invoice id -> ground truth
    customer_truth: tuple[CustomerTruth, ...]
    seed: int
    regime: str


# --- Ramp-shaped records and Tempo additions -------------------------------------------------------


@dataclass(frozen=True)
class RampAmount:
    amount: int  # minor units (cents)
    currency_code: str
    minor_unit_conversion_rate: int = 100


@dataclass(frozen=True)
class RampVendorRef:
    id: str
    name: str


@dataclass(frozen=True)
class DiscountTerms:
    """Tempo addition: discount terms for a bill (would live in Ramp's Custom Records API)."""

    discount_bps: int | None
    discount_days: int | None
    net_days: int | None
    anchor: Anchor
    prox_day: int | None
    discount_deadline: date | None
    due_date: date
    late_fee: LateFeeRecord | None
    source: TermsSource
    status: str  # reconciliation status, e.g. "verified", "conflict"


@dataclass(frozen=True)
class PaymentOption:
    """One way to pay one bill: when cash leaves, when the vendor receives it, and what it is worth."""

    bill_id: str
    kind: Literal["BANK_DUE", "BANK_EARLY", "CARD", "CARD_EARLY", "FINANCE_EARLY", "FINANCE_DUE", "LATE"]
    rail: Literal["RTP", "ACH", "CARD", "FINANCE"]
    send_date: date  # the date sent to Ramp as payment_date (or charged, for card)
    arrival_date: date  # when the vendor receives funds
    cash_out_date: date  # when cash leaves the company's account (card: statement payment date)
    cash_out_cents: int
    value_cents: int  # value vs paying by bank on the due date
    takes_discount: bool
    discount_cents: int
    rewards_cents: int
    fee_cents: int
    surcharge_cents: int
    yield_cents: int
    penalty_cents: int  # objective-only relationship penalty (LATE)


@dataclass(frozen=True)
class Decision:
    """Tempo's recommendation for one bill."""

    bill_id: str
    recommended_payment_date: date
    recommended_payment_method: str  # Ramp request enum where one exists, else Tempo-only FINANCE / LATE
    option_kind: str
    rail: str
    cash_out_date: date
    cash_out_cents: int
    value_cents: int
    annualized_return: float | None
    reason: str
    binding_day: date | None
