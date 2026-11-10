"""Credit capacity limits that sit outside the cash constraint (council C2).

Card charges and Flex-style financing move cash later, so the chance constraint alone would let a plan use
unlimited credit. Two caps, each a linear row over option indices (flat order, bill by bill):
- card: sum of card charges in one statement cycle <= CARD_LIMIT_PER_CYCLE_CENTS
- financing: principal financed with send dates inside any 30-day window <= FINANCE_LINE_LIMIT_CENTS
"""

from collections import defaultdict
from datetime import timedelta

from tempo.assumptions import CARD_LIMIT_PER_CYCLE_CENTS, FINANCE_LINE_LIMIT_CENTS, FINANCE_TERM_DAYS
from tempo.models import PaymentOption

Capacity = tuple[tuple[tuple[int, ...], int], ...]


def flat_options(options: tuple[tuple[PaymentOption, ...], ...]) -> list[PaymentOption]:
    return [o for opts in options for o in opts]


def capacity_groups(
    options: tuple[tuple[PaymentOption, ...], ...],
    card_limit_cents: int = CARD_LIMIT_PER_CYCLE_CENTS,
    finance_limit_cents: int = FINANCE_LINE_LIMIT_CENTS,
) -> Capacity:
    """Card-cycle and financing-window rows as (flat option indices, cap in cents)."""
    flat = flat_options(options)
    cycles: dict = defaultdict(list)
    for j, o in enumerate(flat):
        if o.rail == "CARD":
            cycles[o.cash_out_date].append(j)  # the statement payment date identifies the cycle
    groups = [(tuple(idx), card_limit_cents) for _, idx in sorted(cycles.items())]
    finance = [(j, o) for j, o in enumerate(flat) if o.rail == "FINANCE"]
    for start in sorted({o.send_date for _, o in finance}):
        end = start + timedelta(days=FINANCE_TERM_DAYS - 1)
        idx = tuple(j for j, o in finance if start <= o.send_date <= end)
        groups.append((idx, finance_limit_cents))
    return tuple(groups)


def within_capacity(chosen_flat: set[int], flat: list[PaymentOption], groups: Capacity) -> bool:
    """True if the chosen options respect every cap."""
    return all(sum(flat[j].cash_out_cents for j in idx if j in chosen_flat) <= cap for idx, cap in groups)
