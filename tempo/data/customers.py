"""Synthetic receivables side: customers, their payment history, open invoices, and scheduled billings.

All data is synthetic. Each customer has a true lognormal days-to-pay law (log-mean `mu`, log-std `sigma`)
that depends on its segment. History and open receivables are produced by the same simulation, so an
invoice is "open" exactly when its simulated payment falls on or after the as-of date.
"""

import math
from datetime import date, timedelta

import numpy as np

from tempo.data.names import CUSTOMERS
from tempo.models import Customer, CustomerTruth, PaymentRecord, Receivable, Segment

MONTHLY_REVENUE_CENTS = 400_000_000  # $4.0M per month billed across all customers. ASSUMPTION (synthetic).
BIG_CUSTOMER_SHARES = (0.18, 0.15, 0.12)  # the three largest customers' share of billings. ASSUMPTION.
SEGMENT_PARAMS: dict[Segment, tuple[tuple[float, float], tuple[float, float]]] = {
    # segment: ((median days low, high), (sigma low, high))
    "prompt": ((26.0, 34.0), (0.08, 0.14)),
    "slow": ((48.0, 64.0), (0.14, 0.24)),
    "erratic": ((34.0, 50.0), (0.38, 0.55)),
}
BIG_SEGMENTS: tuple[Segment, ...] = ("slow", "prompt", "erratic")
HISTORY_RANGE = (6, 30)  # payments on record per customer (directive section 6)
LOOKBACK_DAYS = 450


def generate_customers(
    rng: np.random.Generator, as_of: date, horizon_days: int
) -> tuple[tuple[Customer, ...], tuple[CustomerTruth, ...]]:
    """Create every customer with history, open receivables, and scheduled billings."""
    shares = _revenue_shares(rng, len(CUSTOMERS))
    customers, truths = [], []
    for i, name in enumerate(CUSTOMERS):
        segment = BIG_SEGMENTS[i] if i < len(BIG_SEGMENTS) else _segment(rng)
        truth = _truth(rng, f"cus_{i + 1:03d}", segment)
        customer = _customer(rng, truth, name, segment, shares[i], as_of, horizon_days)
        customers.append(customer)
        truths.append(truth)
    return tuple(customers), tuple(truths)


def _revenue_shares(rng: np.random.Generator, n: int) -> np.ndarray:
    big = np.array(BIG_CUSTOMER_SHARES)
    rest = rng.dirichlet(np.full(n - len(big), 2.0)) * (1.0 - big.sum())
    rest = np.minimum(rest, big.min() * 0.9)
    rest = rest / rest.sum() * (1.0 - big.sum())
    return np.concatenate([big, rest])


def _segment(rng: np.random.Generator) -> Segment:
    return rng.choice(np.array(["prompt", "slow", "erratic"]), p=[0.4, 0.35, 0.25]).item()


def _truth(rng: np.random.Generator, customer_id: str, segment: Segment) -> CustomerTruth:
    (m_lo, m_hi), (s_lo, s_hi) = SEGMENT_PARAMS[segment]
    median = rng.uniform(m_lo, m_hi)
    return CustomerTruth(customer_id=customer_id, mu=math.log(median), sigma=float(rng.uniform(s_lo, s_hi)))


def _customer(
    rng: np.random.Generator,
    truth: CustomerTruth,
    name: str,
    segment: Segment,
    share: float,
    as_of: date,
    horizon_days: int,
) -> Customer:
    cadence = 14 if share > 0.05 and rng.random() < 0.5 else 30
    per_invoice = MONTHLY_REVENUE_CENTS * share * cadence / 30.0
    n_history = int(rng.integers(HISTORY_RANGE[0], HISTORY_RANGE[1] + 1))
    first_issue = as_of - timedelta(days=min(LOOKBACK_DAYS, cadence * (n_history + 2)))
    history, open_items = _past_invoices(rng, truth, per_invoice, first_issue, cadence, as_of)
    scheduled = _future_invoices(rng, truth.customer_id, per_invoice, open_items, history, cadence, as_of, horizon_days)
    return Customer(
        id=truth.customer_id,
        name=name,
        segment=segment,
        history=tuple(history[-HISTORY_RANGE[1]:]),
        open_receivables=tuple(open_items),
        scheduled_billings=tuple(scheduled),
    )


def _amount(rng: np.random.Generator, per_invoice: float) -> int:
    return int(round(per_invoice * rng.lognormal(0.0, 0.15) / 100.0)) * 100


def _past_invoices(
    rng: np.random.Generator,
    truth: CustomerTruth,
    per_invoice: float,
    first_issue: date,
    cadence: int,
    as_of: date,
) -> tuple[list[PaymentRecord], list[Receivable]]:
    history: list[PaymentRecord] = []
    open_items: list[Receivable] = []
    issued = first_issue
    k = 0
    while issued < as_of:
        k += 1
        amount = _amount(rng, per_invoice)
        days = max(1, int(round(math.exp(truth.mu + truth.sigma * rng.standard_normal()))))
        paid = issued + timedelta(days=days)
        if paid < as_of:
            history.append(PaymentRecord(invoice_date=issued, paid_date=paid, amount_cents=amount))
        else:
            open_items.append(Receivable(f"{truth.customer_id}_ar_{k:03d}", truth.customer_id, issued, amount))
        issued += timedelta(days=cadence)
    return history, open_items


def _future_invoices(
    rng: np.random.Generator,
    customer_id: str,
    per_invoice: float,
    open_items: list[Receivable],
    history: list[PaymentRecord],
    cadence: int,
    as_of: date,
    horizon_days: int,
) -> list[Receivable]:
    last_dates = [r.issued_at for r in open_items] + [h.invoice_date for h in history]
    issued = max(last_dates) + timedelta(days=cadence) if last_dates else as_of
    end = as_of + timedelta(days=horizon_days)
    out, k = [], 0
    while issued < end:
        k += 1
        out.append(Receivable(f"{customer_id}_sb_{k:03d}", customer_id, issued, _amount(rng, per_invoice)))
        issued += timedelta(days=cadence)
    return out
