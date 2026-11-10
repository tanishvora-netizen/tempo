"""Discount deadlines and due dates from payment terms.

Conventions (the parser only reports what is written; dates are decided here):
  * invoice_date: the discount deadline is issue date + discount_days; the due date is issue date + net_days.
  * receipt: due on the issue date; there is no discount window.
  * eom: days count from the last day of the issue month. "2/10 EOM" therefore means a discount until the
    10th of the next month and payment due 30 days after month end.
  * prox: due on ``prox_day`` of the month after the issue month, clamped to that month's length (prox 31
    in February is the 28th or 29th). Prox terms carry no discount window.
  * roll_after_25th (off by default): an invoice issued after the 25th is treated as issued next month, so
    eom counts from the end of the next month and prox moves to the month after next.
"""

import calendar
from datetime import date, timedelta

from tempo.extract.regex_parser import PaymentTerms

ROLL_CUTOFF_DAY = 25
_MONTHS_PER_YEAR = 12


def discount_deadline(issued: date, terms: PaymentTerms, roll_after_25th: bool = False) -> date | None:
    """Last day the early-payment discount can be taken, or None when the terms offer no discount."""
    if terms.discount_bps is None or terms.discount_days is None:
        return None
    if terms.anchor == "invoice_date":
        return issued + timedelta(days=terms.discount_days)
    if terms.anchor == "eom":
        return _eom_base(issued, roll_after_25th) + timedelta(days=terms.discount_days)
    return None


def due_date(issued: date, terms: PaymentTerms, roll_after_25th: bool = False) -> date:
    """Date the full amount is due. Raises ValueError when the terms lack the field their anchor needs."""
    if terms.anchor == "receipt":
        return issued
    if terms.anchor == "prox":
        return _prox_due(issued, _required(terms.prox_day, "prox_day", terms), roll_after_25th)
    net_days = _required(terms.net_days, "net_days", terms)
    if terms.anchor == "eom":
        return _eom_base(issued, roll_after_25th) + timedelta(days=net_days)
    return issued + timedelta(days=net_days)


def _required(value: int | None, field: str, terms: PaymentTerms) -> int:
    if value is None:
        raise ValueError(f"{terms.anchor} terms need {field}: {terms}")
    return value


def _months_ahead(issued: date, roll_after_25th: bool) -> int:
    return 1 if roll_after_25th and issued.day > ROLL_CUTOFF_DAY else 0


def _shift_month(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * _MONTHS_PER_YEAR + (month - 1) + months
    return index // _MONTHS_PER_YEAR, index % _MONTHS_PER_YEAR + 1


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _eom_base(issued: date, roll_after_25th: bool) -> date:
    year, month = _shift_month(issued.year, issued.month, _months_ahead(issued, roll_after_25th))
    return _month_end(year, month)


def _prox_due(issued: date, prox_day: int, roll_after_25th: bool) -> date:
    year, month = _shift_month(issued.year, issued.month, 1 + _months_ahead(issued, roll_after_25th))
    return date(year, month, min(prox_day, _month_end(year, month).day))
