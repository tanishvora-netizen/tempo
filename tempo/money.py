"""Money and rate helpers. Storage and APIs use integer cents; floats appear only in the solver and charts."""

import math

CENTS_PER_DOLLAR = 100
BPS_PER_UNIT = 10_000


def dollars(cents: int) -> float:
    """Cents to float dollars (solver and charts only)."""
    return cents / CENTS_PER_DOLLAR


def to_cents(amount_dollars: float) -> int:
    """Float dollars to integer cents, rounded half away from zero."""
    return int(math.copysign(math.floor(abs(amount_dollars) * CENTS_PER_DOLLAR + 0.5), amount_dollars))


def apply_rate(cents: int, rate: float) -> int:
    """Round `cents * rate` to whole cents (half away from zero)."""
    return to_cents(dollars(cents) * rate)


def bps_to_rate(bps: int) -> float:
    """Basis points to a fraction: 200 -> 0.02."""
    return bps / BPS_PER_UNIT


def format_usd(cents: int, decimals: int = 0) -> str:
    """Format cents as dollars with thousands separators: 123456789 -> "$1,234,568"."""
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / CENTS_PER_DOLLAR:,.{decimals}f}"


def ceil_to_step(rate: float, step: float) -> float:
    """Round a rate up to the next multiple of `step` (e.g. 0.0025 for quarter-percent offers).

    Formula: ceil(rate / step - 1e-12) * step; the tiny tolerance keeps exact multiples unchanged.
    """
    return math.ceil(rate / step - 1e-12) * step
