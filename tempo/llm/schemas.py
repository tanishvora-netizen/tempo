"""Structured-output schemas the model must fill. The model locates and quotes; code decides values.

Each field group carries the verbatim quote it relied on and the source block (invoice block id or email
message id) it came from: one quote for the terms phrase (discount, days, net, anchor, prox day), and one each
for the late fee, payment methods, card surcharge, and card discount. A flat schema is used because a local
8B model fills it far more reliably than nested per-field objects (measured; see DECISIONS.md). Code verifies
each quote against the document and re-parses it (tempo/extract/verify.py); a value that does not match its
own quote is rejected.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "terms-v2"

_SOURCE = "id of the block or email message the quote was copied from, or null"


class TermsExtraction(BaseModel):
    """The model's reading of an invoice's payment terms, with a verbatim quote per field group."""

    model_config = ConfigDict(extra="forbid")
    terms_quote: str | None = Field(description="the payment terms phrase copied verbatim, or null")
    terms_source: str | None = Field(description=_SOURCE)
    discount_pct: float | None = Field(
        description="early-payment discount in percent: 2 for 2%, 0.5 for 1/2%"
    )
    discount_days: int | None = Field(description="days within which the discount applies")
    net_days: int | None = Field(description="days until the full amount is due (0 for due on receipt)")
    anchor: Literal["invoice_date", "eom", "prox", "receipt"] | None = Field(
        description="what the days count from: invoice_date, eom (end of month), prox (day of next month), receipt"
    )
    prox_day: int | None = Field(description="day of the following month the bill is due, for prox terms")
    late_fee_quote: str | None = Field(description="the late fee or finance charge sentence copied verbatim")
    late_fee_source: str | None = Field(description=_SOURCE)
    late_fee_kind: Literal["pct_month", "pct_year", "flat"] | None = Field(
        description="pct_month for a monthly percent, pct_year for an annual percent, flat for a dollar fee"
    )
    late_fee_value: float | None = Field(description="the percent (1.5 for 1.5%) or the dollars, as written")
    methods_quote: str | None = Field(description="the sentence listing accepted payment methods, verbatim")
    methods_source: str | None = Field(description=_SOURCE)
    accepted_methods: list[Literal["ACH", "CARD", "CHECK", "WIRE"]] = Field(description="accepted methods")
    surcharge_quote: str | None = Field(description="the card surcharge sentence copied verbatim, or null")
    surcharge_source: str | None = Field(description=_SOURCE)
    card_surcharge_pct: float | None = Field(description="card surcharge in percent, as written")
    card_discount_quote: str | None = Field(
        description="sentence saying whether the discount applies to card"
    )
    card_discount_source: str | None = Field(description=_SOURCE)
    card_discount_allowed: bool | None = Field(description="true if the discount applies to card payments")
    terms_overridden_in_email: bool = Field(
        description="true if a later email from the vendor's domain changes the terms printed on the invoice"
    )


class OfferTemplate(BaseModel):
    """An early-payment offer email written ONLY with placeholders; code fills every number."""

    model_config = ConfigDict(extra="forbid")
    subject_template: str = Field(description="subject line using only the allowed {PLACEHOLDERS}; no digits")
    body_template: str = Field(description="email body using only the allowed {PLACEHOLDERS}; no digits")
