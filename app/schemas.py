"""Request and response models. Requests are validated strictly; responses wrap the precomputed views."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DELAY_DAYS = 60
MAX_SHOCK_CENTS = 200_000_000  # $2M


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WhatIfRequest(Strict):
    preset_id: str | None = Field(default=None, max_length=80)
    customer_id: str | None = Field(default=None, max_length=40)
    delay_days: int = Field(default=0, ge=0, le=MAX_DELAY_DAYS)
    shock_cents: int = Field(default=0, ge=0, le=MAX_SHOCK_CENTS)
    shock_day: int = Field(default=0, ge=0, le=90)

    @model_validator(mode="after")
    def one_kind(self) -> "WhatIfRequest":
        if self.preset_id is None and self.customer_id is None and self.shock_cents == 0:
            raise ValueError("give a preset_id, a customer_id with delay_days, or a shock_cents")
        return self


class OptimizeRequest(Strict):
    what_if: WhatIfRequest | None = None


class TermsInput(Strict):
    discount_pct: float | None = Field(default=None, ge=0, le=5)
    discount_days: int | None = Field(default=None, ge=0, le=60)
    net_days: int | None = Field(default=None, ge=0, le=120)
    anchor: Literal["invoice_date", "eom", "prox", "receipt"] = "invoice_date"
    prox_day: int | None = Field(default=None, ge=1, le=31)


class ReviewAction(Strict):
    action: Literal["accept", "edit"]
    terms: TermsInput | None = None

    @model_validator(mode="after")
    def edit_needs_terms(self) -> "ReviewAction":
        if self.action == "edit" and self.terms is None:
            raise ValueError("edit needs terms")
        return self


class Payload(BaseModel):
    """Envelope for view payloads (shapes documented in tempo/report.py and tempo/views.py)."""

    model_config = ConfigDict(extra="allow")
    data: dict[str, Any]


class ErrorBody(BaseModel):
    error: str
    detail: str | None = None
