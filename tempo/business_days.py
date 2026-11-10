"""Business-day arithmetic for ACH (weekends and Federal Reserve holidays are not business days)."""

from datetime import date, timedelta

from tempo.assumptions import FED_HOLIDAYS

_HOLIDAYS = frozenset(FED_HOLIDAYS)
SATURDAY = 5


def is_business_day(d: date) -> bool:
    """True on weekdays that are not Federal Reserve holidays."""
    return d.weekday() < SATURDAY and d not in _HOLIDAYS


def previous_business_day(d: date) -> date:
    """The latest business day on or before `d`."""
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def next_business_day(d: date) -> date:
    """The earliest business day on or after `d`."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def subtract_business_days(arrival: date, n: int) -> date:
    """Send date for an ACH that must arrive by `arrival`, taking `n` business days.

    The payment must arrive on a business day on or before `arrival`, so we first move to the previous
    business day, then step back `n` business days.
    """
    d = previous_business_day(arrival)
    for _ in range(n):
        d = previous_business_day(d - timedelta(days=1))
    return d


def add_business_days(send: date, n: int) -> date:
    """Arrival date of an ACH sent on `send` that takes `n` business days."""
    d = next_business_day(send)
    for _ in range(n):
        d = next_business_day(d + timedelta(days=1))
    return d


def business_days_between(start: date, end: date) -> int:
    """Business days in (start, end]: how many business days `end` is after `start`."""
    count, d = 0, start
    while d < end:
        d += timedelta(days=1)
        count += is_business_day(d)
    return count
