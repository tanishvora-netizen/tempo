"""Synthetic vendors: terms profile, card acceptance, rails, late fees, and invoice template.

All data is synthetic; names come from `tempo.data.names` and are fictional.
"""

from dataclasses import dataclass

import numpy as np

from tempo.assumptions import RTP_VENDOR_SHARE
from tempo.data.invoice_text import DATE_FORMATS, VendorTemplate
from tempo.data.names import CITIES, STREETS, VENDORS
from tempo.models import LateFeeRecord, Method, TermsRecord, Vendor


def _t(bps: int | None, dd: int | None, net: int | None, anchor: str = "invoice_date", prox: int | None = None) -> TermsRecord:
    return TermsRecord(discount_bps=bps, discount_days=dd, net_days=net, anchor=anchor, prox_day=prox)


# One entry per vendor (40). Directive section 6 terms mix.
TERMS_POOL: tuple[TermsRecord, ...] = (
    *[_t(200, 10, 30)] * 8,
    *[_t(100, 10, 30)] * 4,
    *[_t(100, 15, 45)] * 3,
    _t(50, 10, 30),
    *[_t(None, None, 30)] * 8,
    *[_t(None, None, 45)] * 4,
    *[_t(None, None, 60)] * 3,
    _t(None, None, 15),
    *[_t(None, None, 0, "receipt")] * 2,
    *[_t(200, 10, 30, "eom")] * 2,
    *[_t(None, None, None, "prox", 10)] * 2,
    *[_t(None, None, 30, "eom")] * 2,
)

# category -> (median bill subtotal in dollars, log-std, cadence in days)
CATEGORY_PROFILE: dict[str, tuple[float, float, int]] = {
    "raw_materials": (58_000.0, 0.45, 14),
    "components": (17_000.0, 0.5, 14),
    "packaging": (9_000.0, 0.4, 14),
    "freight": (6_500.0, 0.35, 7),
    "services": (24_000.0, 0.4, 30),
    "software": (11_000.0, 0.3, 30),
    "supplies": (2_400.0, 0.5, 21),
    "utilities": (31_000.0, 0.15, 30),
}

N_CARD_VENDORS = 14
N_NEW_VENDORS = 4
N_CARD_DISCOUNT_VENDORS = 3
N_DATE_NUMBER_VENDORS = 2


@dataclass(frozen=True)
class VendorProfile:
    """Generator-only facts about a vendor (truth for its invoices and how they look)."""

    vendor: Vendor
    terms: TermsRecord
    late_fee: LateFeeRecord | None
    late_fee_annual: bool
    methods: tuple[Method, ...]
    surcharge_bps: int
    card_discount_allowed: bool
    template: VendorTemplate
    invoice_prefix: str
    date_style_numbers: bool  # invoice numbers that look like dates ("2/10/2026"): a parser hazard
    median_subtotal: float
    log_sd: float
    cadence_days: int


def generate_vendors(rng: np.random.Generator) -> tuple[VendorProfile, ...]:
    """Create the 40 vendor profiles with a fixed terms mix and seeded attributes."""
    terms = [TERMS_POOL[i] for i in rng.permutation(len(TERMS_POOL))]
    n = len(VENDORS)
    card = set(rng.choice(n, N_CARD_VENDORS, replace=False).tolist())
    new = set(rng.choice(n, N_NEW_VENDORS, replace=False).tolist())
    discount_card = [i for i in sorted(card) if terms[i].discount_bps and terms[i].anchor == "invoice_date"]
    card_discount = set(discount_card[:N_CARD_DISCOUNT_VENDORS])
    plain_net = [i for i in range(n) if terms[i].discount_bps is None and terms[i].anchor == "invoice_date" and (terms[i].net_days or 0) >= 30]
    date_numbers = set(plain_net[:N_DATE_NUMBER_VENDORS])
    return tuple(
        _profile(rng, i, terms[i], i in card, i in new, i in card_discount, i in date_numbers) for i in range(n)
    )


def _profile(
    rng: np.random.Generator,
    i: int,
    terms: TermsRecord,
    accepts_card: bool,
    is_new: bool,
    card_discount: bool,
    date_numbers: bool,
) -> VendorProfile:
    name, category, goods = VENDORS[i]
    slug = "".join(ch for ch in name.lower() if ch.isalnum())[:18]
    vendor = Vendor(
        id=f"ven_{i + 1:03d}",
        name=name,
        domain=f"{slug}.example",
        category=category,
        sells_goods=goods,
        rtp_eligible=bool(rng.random() < RTP_VENDOR_SHARE),
        is_new=is_new,
        prior_terms=None if is_new else terms,
    )
    median, log_sd, cadence = CATEGORY_PROFILE[category]
    surcharge = int(rng.choice([250, 300])) if accepts_card and rng.random() < 0.5 else 0
    late_fee, annual = _late_fee(rng)
    return VendorProfile(
        vendor=vendor,
        terms=terms,
        late_fee=late_fee,
        late_fee_annual=annual,
        methods=_methods(rng, accepts_card),
        surcharge_bps=surcharge,
        card_discount_allowed=card_discount,
        template=_template(rng),
        invoice_prefix="".join(w[0] for w in name.split() if w[0].isalpha()).upper()[:3],
        date_style_numbers=date_numbers,
        median_subtotal=median,
        log_sd=log_sd,
        cadence_days=cadence,
    )


def _late_fee(rng: np.random.Generator) -> tuple[LateFeeRecord | None, bool]:
    u = rng.random()
    if u < 0.22:
        return LateFeeRecord("pct_month", 150, None), False
    if u < 0.27:
        return LateFeeRecord("pct_month", 150, None), True
    if u < 0.32:
        return LateFeeRecord("flat", None, 2500), False
    return None, False


def _methods(rng: np.random.Generator, accepts_card: bool) -> tuple[Method, ...]:
    methods: list[Method] = ["ACH"]
    if rng.random() < 0.6:
        methods.append("CHECK")
    if rng.random() < 0.2:
        methods.append("WIRE")
    if accepts_card:
        methods.append("CARD")
    return tuple(methods)


def _template(rng: np.random.Generator) -> VendorTemplate:
    return VendorTemplate(
        terms_location=str(rng.choice(["header", "payment_box", "footer"], p=[0.5, 0.3, 0.2])),
        date_format=str(rng.choice(DATE_FORMATS)),
        phrase_style=int(rng.integers(0, 6)),
        street=str(rng.choice(STREETS)),
        city=str(rng.choice(CITIES)),
        account_last4=f"{int(rng.integers(1000, 10000))}",
    )
