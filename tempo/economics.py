"""Early-payment discount economics (directive 5.1)."""

from tempo.assumptions import DAYS_IN_YEAR


def annualized_return(d: float, discount_days: int, net_days: int, days_in_year: int = DAYS_IN_YEAR) -> float:
    """Simple annualized return of taking discount d for paying (N - D) days early.

        r = d / (1 - d) * days_in_year / (N - D)

    2/10 net 30: 0.02 / 0.98 * 365 / 20 = 37.24% (365-day basis; 36.73% on Treasury's 360-day basis).
    """
    window = net_days - discount_days
    if window <= 0:
        raise ValueError("net days must exceed discount days")
    return d / (1 - d) * days_in_year / window


def compounded_return(d: float, discount_days: int, net_days: int, days_in_year: int = DAYS_IN_YEAR) -> float:
    """Effective annual rate: (1 / (1 - d)) ** (days_in_year / (N - D)) - 1. 2/10 net 30: 44.6% (tooltip only)."""
    return (1 / (1 - d)) ** (days_in_year / (net_days - discount_days)) - 1


def break_even_discount(cost_of_cash: float, days_early: int, days_in_year: int = DAYS_IN_YEAR) -> float:
    """Smallest discount worth paying `days_early` days early when cash costs c per year.

        d* = 1 - 1 / (1 + c * days_early / days_in_year)

    c = 8%, 30 days: 0.6532% (the shortcut c * days / 365 = 0.6575% slightly overstates it).
    """
    return 1 - 1 / (1 + cost_of_cash * days_early / days_in_year)
