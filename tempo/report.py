"""Turn solver output into plain JSON views for the API and UI. Every number here comes from the data,
assumptions.py, or the solver; nothing is invented.
"""

from dataclasses import asdict
from datetime import date, timedelta

from tempo.assumptions import (
    EPSILON,
    SEED_C,
    WILSON_Z_REPORT,
)
from tempo.business_days import next_business_day, subtract_business_days
from tempo.extract.reconcile import Reconciled
from tempo.models import Decision, PaymentOption
from tempo.optimize.baselines import annualized_discount_return
from tempo.optimize.cash_value import CashValue
from tempo.optimize.certify import Certification
from tempo.optimize.engine import Plan
from tempo.optimize.evaluate import PolicyResult
from tempo.optimize.explain import terms_label
from tempo.optimize.options import PlannableBill, ach_lead
from tempo.serde import to_jsonable

STATUS_CHIPS = {
    "verified": "Verified",
    "regex_only": "Regex only",
    "model_verified": "Model verified",
    "human_accepted": "Accepted by reviewer",
}


def rtp_dependent(bill: PlannableBill, o: PaymentOption, as_of: date | None) -> bool:
    """True if only RTP can meet the target: an ACH that arrives on time would have to be sent before today (or
    before the invoice exists). Other RTP-planned payments can be sent earlier as ACH instead."""
    if o.rail != "RTP":
        return False
    earliest = next_business_day(max(as_of or bill.issued_at, bill.issued_at))
    target = bill.discount_deadline if o.takes_discount and bill.discount_deadline else bill.due_date
    lead = ach_lead(o.takes_discount, bill.is_new_vendor)
    return subtract_business_days(target, lead) < earliest


def chip(status: str) -> str:
    return STATUS_CHIPS.get(status, "Needs review")


def option_view(o: PaymentOption) -> dict:
    return {
        "kind": o.kind,
        "rail": o.rail,
        "send_date": o.send_date.isoformat(),
        "arrival_date": o.arrival_date.isoformat(),
        "cash_out_date": o.cash_out_date.isoformat(),
        "cash_out_cents": o.cash_out_cents,
        "value_cents": o.value_cents,
        "discount_cents": o.discount_cents,
        "rewards_cents": o.rewards_cents,
        "fee_cents": o.fee_cents,
        "surcharge_cents": o.surcharge_cents,
        "yield_cents": o.yield_cents,
    }


def bill_rows(
    plan: Plan, decisions: tuple[Decision, ...], reconciled: dict[str, Reconciled], as_of: date | None = None
) -> list[dict]:
    """One row per bill for the Payment run table (plus everything the side panel needs)."""
    rows = []
    for bill, opts, c, d in zip(plan.bills, plan.options, plan.choice, decisions, strict=True):
        rows.append(_row(bill, opts, c, d, reconciled.get(bill.id), as_of))
    return rows


def _row(bill: PlannableBill, opts, c: int, d: Decision, r: Reconciled | None, as_of: date | None) -> dict:
    o = opts[c]
    return {
        "bill_id": bill.id,
        "vendor_id": bill.vendor_id,
        "vendor": bill.vendor_name,
        "invoice_number": bill.invoice_number,
        "issued_at": bill.issued_at.isoformat(),
        "amount_cents": bill.total_cents,
        "subtotal_cents": bill.subtotal_cents,
        "terms": terms_label(bill),
        "status": bill.status,
        "chip": chip(bill.status),
        "needs_review": bill.status not in STATUS_CHIPS,
        "due_date": bill.due_date.isoformat(),
        "discount_deadline": bill.discount_deadline.isoformat() if bill.discount_deadline else None,
        "option": o.kind,
        "rail": o.rail,
        "method": d.recommended_payment_method,
        "send_date": o.send_date.isoformat(),
        "cash_out_date": o.cash_out_date.isoformat(),
        "cash_out_cents": o.cash_out_cents,
        "value_cents": o.value_cents,
        "annualized_return": d.annualized_return,
        "takes_discount": o.takes_discount,
        "is_card": o.rail == "CARD",
        "is_late": o.kind == "LATE",
        "arrives_after_due": o.arrival_date > bill.due_date,
        "expected": as_of is not None and bill.issued_at > as_of,
        "rtp_dependent": rtp_dependent(bill, o, as_of),
        "new_vendor": bill.is_new_vendor,
        "arrival_date": o.arrival_date.isoformat(),
        "terms_rate": annualized_discount_return(bill) if o.takes_discount else None,
        "reason": d.reason,
        "binding_day": d.binding_day.isoformat() if d.binding_day else None,
        "options": [option_view(x) for x in opts],
        "chosen_index": c,
        "accepts_card": bill.accepts_card,
        "rtp_eligible": bill.rtp_eligible,
        "review_reason": r.terms.reason if r is not None and bill.status not in STATUS_CHIPS else None,
    }


def policy_view(r: PolicyResult) -> dict:
    out = to_jsonable(asdict(r))
    out["worst_p10_date"] = r.worst_p10_date.isoformat()
    return out


def certification_view(cert: Certification, oos: PolicyResult) -> dict:
    """Certification record (seed B) and the reported out-of-sample numbers (seed C)."""
    final = cert.final
    return {
        "epsilon": cert.epsilon,
        "z_certify": cert.z,
        "passed": cert.passed,
        "n": final.n,
        "k": final.k,
        "in_sample_rate": final.in_sample_breaches / final.n,
        "steps": [to_jsonable(asdict(s)) for s in cert.steps],
        "reported": {
            "seed": SEED_C,
            "n": oos.n_scenarios,
            "breaches": oos.breaches,
            "rate": oos.breach_rate,
            "upper": oos.breach_upper,
            "z": WILSON_Z_REPORT,
            "passes": oos.breach_upper <= EPSILON,
        },
    }


def cash_value_view(cv: CashValue) -> dict:
    return to_jsonable(asdict(cv))


def kpis(plan: Plan, oos: PolicyResult, cv: CashValue, buffer_cents: int, as_of: date) -> dict:
    chosen = plan.chosen()
    return {
        "value_vs_pay_on_due_cents": plan.value_cents(),
        "discounts_captured_cents": sum(o.discount_cents for o in chosen if o.takes_discount),
        "discounts_captured_count": sum(o.takes_discount for o in chosen),
        "card_rewards_cents": sum(o.rewards_cents for o in chosen),
        "card_count": sum(o.rail == "CARD" for o in chosen),
        "breach_rate": oos.breach_rate,
        "breach_upper": oos.breach_upper,
        "epsilon": EPSILON,
        "worst_p10_balance_cents": oos.worst_p10_balance_cents,
        "worst_p10_date": oos.worst_p10_date.isoformat(),
        "buffer_cents": buffer_cents,
        "cost_of_cash": cv.cost_of_cash,
        "cost_of_cash_credit_bound": cv.credit_bound,
        "late_count": oos.late_count,
        "arrive_after_due_count": sum(
            o.arrival_date > b.due_date for b, o in zip(plan.bills, chosen, strict=True)
        ),
        "yield_cents": sum(o.yield_cents for o in chosen),
        "surcharge_cents": sum(o.surcharge_cents for o in chosen),
        "fees_cents": sum(o.fee_cents for o in chosen),
        "credit_drawn_cents": plan.credit_drawn_cents(),
        "credit_first_date": _first_credit_date(plan, as_of),
    }


def _first_credit_date(plan: Plan, as_of: date) -> str | None:
    """First day the backstop credit is drawn, or None."""
    drawn = [i for i, v in enumerate(plan.credit_cum_cents) if v > 0]
    return (as_of + timedelta(days=drawn[0])).isoformat() if drawn else None


def diff_plans(before: Plan, after: Plan, after_decisions: tuple[Decision, ...]) -> list[dict]:
    """Bills whose option or send date changed, with the new reason."""
    reasons = {d.bill_id: d.reason for d in after_decisions}
    before_by = {o.bill_id: o for o in before.chosen()}
    rows = []
    for bill, o in zip(after.bills, after.chosen(), strict=True):
        b = before_by.get(bill.id)
        if b is None or (b.kind, b.send_date) != (o.kind, o.send_date):
            rows.append(
                {
                    "bill_id": bill.id,
                    "vendor": bill.vendor_name,
                    "invoice_number": bill.invoice_number,
                    "amount_cents": bill.total_cents,
                    "before": {
                        "option": b.kind,
                        "send_date": b.send_date.isoformat(),
                        "value_cents": b.value_cents,
                    }
                    if b
                    else None,
                    "after": {
                        "option": o.kind,
                        "send_date": o.send_date.isoformat(),
                        "value_cents": o.value_cents,
                    },
                    "reason": reasons.get(bill.id, ""),
                }
            )
    return rows
