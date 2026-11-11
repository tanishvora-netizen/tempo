"""Negotiation agent: price an early-payment offer for vendors with no discount terms, verify it with the
optimizer, draft the email (number-guarded), and parse the vendor's reply (directive 5.7, 7.5, 7.6).

Pricing for a bill issued on day I and due on day T:
    proposed pay date P = I + OFFER_DAYS;  days early Delta = T - P (skipped if Delta <= 0 or P is past)
    break-even d* = 1 - 1 / (1 + c * Delta / 365), with c the company's cost of cash
    offer d_offer = ceil_to_0.25%(d* + OFFER_MARGIN)
Verification: add a hypothetical discount option at d_offer to that bill and re-solve at the base plan's K and
N; the offer is ranked only if Tempo would take it, by the value it adds. Offers come from the buyer and
trade about three weeks of cash for a discount priced at the buyer's cost of cash; the vendor's reason to say
yes is "paid early, instantly by RTP, no fee to you". Nothing is ever sent.
"""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta

from tempo.assumptions import DAYS_IN_YEAR, OFFER_DAYS, OFFER_MARGIN, OFFER_ROUNDING
from tempo.business_days import next_business_day
from tempo.economics import annualized_return, break_even_discount
from tempo.extract.reconcile import decide_terms
from tempo.extract.regex_parser import parse_block
from tempo.extract.verify import as_record, verify_extraction
from tempo.llm.provider import LLMProvider, ModelCall, ProviderError, draft_call, reply_call
from tempo.models import EmailMessage, InvoiceDocument, TermsRecord
from tempo.money import BPS_PER_UNIT, apply_rate, ceil_to_step, format_usd
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.options import PlannableBill, RailContext, build_options
from tempo.optimize.run import RunInputs

from .number_guard import GuardedText, guard

REPLY_KINDS = ("accept", "counter", "decline", "ambiguous")
COUNTER_BPS = 50


@dataclass(frozen=True)
class Offer:
    vendor_id: str
    vendor_name: str
    bill_id: str
    invoice_number: str
    amount_cents: int
    subtotal_cents: int
    issued_at: date
    due_date: date
    proposed_date: date
    days_early: int
    cost_of_cash: float
    break_even: float
    offer_bps: int
    savings_cents: int
    annualized_return: float
    tempo_takes_it: bool
    value_delta_cents: int
    verdict: str


def vendor_spend_cents(bills: tuple[PlannableBill, ...]) -> dict[str, int]:
    """Each vendor's bill spend (subtotals: the base a discount applies to) in the 13-week data."""
    out: dict[str, int] = {}
    for b in bills:
        out[b.vendor_id] = out.get(b.vendor_id, 0) + b.subtotal_cents
    return out


def annual_value_cents(spend_cents: int, offer_bps: int, horizon_days: int) -> int:
    """Annual value if the vendor accepts: 13-week spend x (365 / horizon) x offer discount. An estimate that
    assumes the next 39 weeks look like these 13; labeled as such in the UI."""
    return round(spend_cents * (DAYS_IN_YEAR / horizon_days) * offer_bps / BPS_PER_UNIT)


def price(cost_of_cash: float, days_early: int) -> tuple[float, int]:
    """(d*, d_offer in basis points) from the formulas in the module docstring."""
    d_star = break_even_discount(cost_of_cash, days_early)
    offer = ceil_to_step(d_star + OFFER_MARGIN, OFFER_ROUNDING)
    return d_star, round(offer * BPS_PER_UNIT)


def candidate_bills(bills: tuple[PlannableBill, ...], as_of: date) -> dict[str, int]:
    """Per vendor with no discount terms: the index of its largest bill that can still be paid early."""
    best: dict[str, int] = {}
    for i, b in enumerate(bills):
        proposed = b.issued_at + timedelta(days=OFFER_DAYS)
        if b.terms.discount_bps or not b.discount_usable or proposed < next_business_day(as_of):
            continue
        if (b.due_date - proposed).days <= 0:
            continue
        if b.vendor_id not in best or b.subtotal_cents > bills[best[b.vendor_id]].subtotal_cents:
            best[b.vendor_id] = i
    return best


def hypothetical(bill: PlannableBill, offer_bps: int) -> PlannableBill:
    """The bill as if the vendor accepted: offer_bps if paid by issue + OFFER_DAYS, else the same due date."""
    proposed = bill.issued_at + timedelta(days=OFFER_DAYS)
    net = (bill.due_date - bill.issued_at).days
    terms = TermsRecord(offer_bps, OFFER_DAYS, net, "invoice_date")
    return replace(bill, terms=terms, discount_deadline=proposed, discount_usable=True, status="negotiated")


def verify_offer(inputs: RunInputs, base: Plan, index: int, offer_bps: int) -> tuple[bool, int, str]:
    """Re-solve with the hypothetical discount on one bill: does Tempo take it, and what does it add?"""
    bill = hypothetical(inputs.bills[index], offer_bps)
    ctx_options = build_options(bill, _rail_context(inputs))
    options = (*inputs.options[:index], ctx_options, *inputs.options[index + 1 :])
    bills = (*inputs.bills[:index], bill, *inputs.bills[index + 1 :])
    n = base.n_scenarios or inputs.headroom_a.shape[0]
    plan = solve_plan(bills, options, inputs.headroom_a_fallback[:n], inputs.as_of, base.k or 0)
    chosen = plan.chosen()[index]
    return chosen.takes_discount, plan.objective_cents() - base.objective_cents(), chosen.kind


def _rail_context(inputs: RunInputs) -> RailContext:
    c = inputs.dataset.company
    return RailContext(c.as_of, c.funding_account)


def plan_offers(inputs: RunInputs, base: Plan, cost_of_cash: float) -> list[Offer]:
    """Every candidate vendor's priced and verified offer, ranked by verified value (takers first)."""
    offers = []
    for _vendor_id, i in sorted(candidate_bills(inputs.bills, inputs.as_of).items()):
        bill = inputs.bills[i]
        proposed = bill.issued_at + timedelta(days=OFFER_DAYS)
        days_early = (bill.due_date - proposed).days
        d_star, offer_bps = price(cost_of_cash, days_early)
        takes, delta, kind = verify_offer(inputs, base, i, offer_bps)
        d = offer_bps / BPS_PER_UNIT
        verdict = (
            f"If accepted, Tempo would take it: +{format_usd(delta)}"
            if takes
            else f"Tempo would not take it: {kind.replace('_', ' ').lower()} is still better or cash does not allow it"
        )
        offers.append(
            Offer(
                bill.vendor_id,
                bill.vendor_name,
                bill.id,
                bill.invoice_number,
                bill.total_cents,
                bill.subtotal_cents,
                bill.issued_at,
                bill.due_date,
                proposed,
                days_early,
                cost_of_cash,
                d_star,
                offer_bps,
                apply_rate(bill.subtotal_cents, d),
                annualized_return(d, OFFER_DAYS, OFFER_DAYS + days_early),
                takes,
                delta,
                verdict,
            )
        )
    return sorted(offers, key=lambda o: (not o.tempo_takes_it, -o.value_delta_cents, o.vendor_name))


def offer_values(o: Offer) -> dict[str, str]:
    """Every number the email may contain, computed by code."""
    return {
        "VENDOR": o.vendor_name,
        "INVOICE_NO": o.invoice_number,
        "AMOUNT": format_usd(o.amount_cents, 2),
        "DISC_PCT": f"{o.offer_bps / 100:g}%",
        "SAVINGS": format_usd(o.savings_cents, 2),
        "PAY_BY": f"{o.proposed_date:%b} {o.proposed_date.day}, {o.proposed_date.year}",
        "NET_DAYS": str((o.due_date - o.issued_at).days),
    }


def draft_email(provider: LLMProvider | None, o: Offer) -> tuple[GuardedText, str]:
    """Model-written template (placeholders only), then the number guard. Returns the text and its source."""
    if provider is None:
        return guard(None, offer_values(o)), "deterministic template (no model)"
    try:
        template = provider.draft_offer(draft_call(o.vendor_name))
    except ProviderError as exc:
        return guard(None, offer_values(o)), f"deterministic template (model unavailable: {exc})"
    out = guard(template, offer_values(o))
    return out, (
        "deterministic template (model draft rejected)" if out.used_fallback else f"{provider.model} draft"
    )


def simulated_reply(o: Offer, kind: str) -> str:
    """A vendor reply for the demo (synthetic). Numbers come from the offer, never from a model."""
    v = offer_values(o)
    net = v["NET_DAYS"]
    if kind == "accept":
        return (
            f"Hi, thanks for reaching out. That works for us: {v['DISC_PCT']} {OFFER_DAYS} days, net {net} on "
            f"invoice {v['INVOICE_NO']}, as long as payment arrives by {v['PAY_BY']}."
        )
    if kind == "counter":
        return (
            f"Thanks for the offer. We can't do {v['DISC_PCT']}, but we could offer {COUNTER_BPS / 100:g}% "
            f"{OFFER_DAYS} days, net {net} on invoice {v['INVOICE_NO']}."
        )
    if kind == "decline":
        return f"Thanks, but we are not able to offer an early-payment discount on this invoice. Terms stay net {net}."
    return "Let me check with our controller about the early payment and get back to you next week."


def reply_message(o: Offer, kind: str) -> tuple[str, str, str]:
    """(message id, sender, text) of a simulated reply; shared with scripts/build_cache.py so keys match."""
    return (
        f"<reply-{kind}-{o.bill_id[:8]}@vendor>",
        f"billing@{o.vendor_id}.example",
        simulated_reply(o, kind),
    )


def reply_model_call(o: Offer, kind: str) -> ModelCall:
    message_id, sender, text = reply_message(o, kind)
    return reply_call(message_id, sender, text)


def parse_reply(provider: LLMProvider | None, o: Offer, kind: str) -> dict:
    """Parse a reply with the parser and the model, cross-checked exactly like invoices; never auto-applied."""
    message_id, _sender, text = reply_message(o, kind)
    doc = InvoiceDocument(
        (),
        (
            EmailMessage(
                message_id, f"billing@{o.vendor_id}.example", _noon(o.issued_at), "Re: early payment", text
            ),
        ),
    )
    regex_values = tuple(sorted({as_record(t) for t in parse_block(text).distinct_terms()}, key=repr))
    check, model_note = None, "no model"
    if provider is not None:
        try:
            ext = provider.parse_reply(reply_model_call(o, kind))
            check = verify_extraction(ext, doc)["terms"]
            model_note = check.reason
        except ProviderError as exc:
            model_note = f"model unavailable: {exc}"
    decision = decide_terms(regex_values, check, None)
    return {
        "kind": kind,
        "text": text,
        "message_id": message_id,
        "status": decision.status,
        "terms": None if decision.value is None else asdict(decision.value),
        "reason": decision.reason,
        "model_check": model_note,
        "needs_human_accept": True,
    }


def _noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12)
