"""Baseline policies Tempo is compared against (directive 5.6, council C1).

1. pay_on_due         every bill by bank, arriving on its due date.
2. weekly_run         one run per week (every 7 days from the as-of date). A bill is sent in the last run on or
                      before its send date. Its discount is taken when the discount deadline falls in a run
                      window: the run on or before the early send date must be on or after the as-of date and
                      no earlier than the invoice date (ASSUMPTION: common AP practice).
3. greedy_discount    due-date order; take the best discount or card option the P50 balance path allows.
4. greedy_p05         the "smart spreadsheet": same, but checks the pointwise P5 path and only takes a
                      discount whose annualized return beats the cost of cash.
5. deterministic_p50  the same MILP on the P50 path only (one scenario, no chance constraint).
Every policy respects the same card and financing caps as Tempo. Ablations solve the MILP against a single
pointwise-quantile path (per-day constraints instead of joint).
"""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from tempo.assumptions import DAYS_IN_YEAR
from tempo.models import PaymentOption
from tempo.money import BPS_PER_UNIT
from tempo.optimize.capacity import capacity_groups, flat_options, within_capacity
from tempo.optimize.cash import day_index
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.options import PlannableBill, yield_cents

RUN_INTERVAL_DAYS = 7
EARLY_KINDS = ("BANK_EARLY", "CARD_EARLY", "FINANCE_EARLY")
Options = tuple[tuple[PaymentOption, ...], ...]


def _zero_credit(horizon: int) -> np.ndarray:
    return np.zeros(horizon, dtype=np.int64)


def _due_index(opts: tuple[PaymentOption, ...]) -> int:
    return next(i for i, o in enumerate(opts) if o.kind == "BANK_DUE")


def pay_on_due(bills: tuple[PlannableBill, ...], options: Options, horizon: int) -> Plan:
    choice = tuple(_due_index(opts) for opts in options)
    return Plan("pay_on_due", bills, options, choice, _zero_credit(horizon))


def weekly_run(bills: tuple[PlannableBill, ...], options: Options, as_of: date, horizon: int) -> Plan:
    """Shift each bill's bank payment back to the most recent weekly run day."""
    chosen = []
    for bill, opts in zip(bills, options, strict=True):
        due = opts[_due_index(opts)]
        early = next((o for o in opts if o.kind == "BANK_EARLY"), None)
        target = early if early is not None and _caught_in_a_run(early, bill, as_of) else due
        chosen.append(_shift(target, _run_on_or_before(target.send_date, as_of), due.cash_out_date))
    custom = tuple((o,) for o in chosen)
    return Plan("weekly_run", bills, custom, tuple(0 for _ in custom), _zero_credit(horizon))


def _caught_in_a_run(early: PaymentOption, bill: PlannableBill, as_of: date) -> bool:
    run = _run_on_or_before(early.send_date, as_of)
    return early.send_date >= as_of and run >= bill.issued_at


def _run_on_or_before(d: date, as_of: date) -> date:
    weeks = max((d - as_of).days, 0) // RUN_INTERVAL_DAYS
    return as_of + timedelta(days=weeks * RUN_INTERVAL_DAYS)


def _shift(o: PaymentOption, run: date, base: date) -> PaymentOption:
    """Send on the run day instead: cash leaves (and the vendor is paid) that many days earlier."""
    if run >= o.send_date:
        return o
    moved = o.send_date - run
    new_yield = yield_cents(o.cash_out_cents, run, base)
    return replace(
        o,
        send_date=run,
        cash_out_date=run,
        arrival_date=o.arrival_date - moved,
        yield_cents=new_yield,
        value_cents=o.value_cents - o.yield_cents + new_yield,
    )


def greedy(
    bills: tuple[PlannableBill, ...],
    options: Options,
    path: np.ndarray,
    as_of: date,
    policy: str,
    min_annual_return: float | None = None,
) -> Plan:
    """Due-date order; adopt the best-value non-late option that keeps `path - plan_cum` from getting worse
    below zero on any day, within the credit caps. `path` is a single headroom path (P50 or P5)."""
    horizon = path.shape[0]
    flat = flat_options(options)
    offsets = np.cumsum([0, *[len(o) for o in options]])[:-1]
    groups = capacity_groups(options)
    choice = [_due_index(opts) for opts in options]
    daily = np.zeros(horizon, dtype=np.int64)
    for opts, c in zip(options, choice, strict=True):
        daily[day_index(opts[c].cash_out_date, as_of, horizon)] += opts[c].cash_out_cents
    for i in sorted(range(len(bills)), key=lambda i: (bills[i].due_date, bills[i].id)):
        skip_early = (
            min_annual_return is not None and annualized_discount_return(bills[i]) <= min_annual_return
        )
        chosen_flat = {int(offsets[b] + c) for b, c in enumerate(choice)}
        for cand in _ranked(options[i], choice[i], skip_early):
            trial_flat = (chosen_flat - {int(offsets[i] + choice[i])}) | {int(offsets[i] + cand)}
            trial = _moved(daily, options[i][choice[i]], options[i][cand], as_of)
            if within_capacity(trial_flat, flat, groups) and _no_worse(path, daily, trial):
                daily[:] = trial
                choice[i] = cand
                break
    return Plan(policy, bills, options, tuple(choice), _zero_credit(horizon))


def _ranked(opts: tuple[PaymentOption, ...], current: int, skip_early: bool) -> list[int]:
    better = [i for i, o in enumerate(opts) if o.kind != "LATE" and o.value_cents > opts[current].value_cents]
    if skip_early:
        better = [i for i in better if opts[i].kind not in EARLY_KINDS]
    return sorted(better, key=lambda i: -opts[i].value_cents)


def _moved(daily: np.ndarray, old: PaymentOption, new: PaymentOption, as_of: date) -> np.ndarray:
    horizon = daily.shape[0]
    trial = daily.copy()
    trial[day_index(old.cash_out_date, as_of, horizon)] -= old.cash_out_cents
    trial[day_index(new.cash_out_date, as_of, horizon)] += new.cash_out_cents
    return trial


def _no_worse(path: np.ndarray, daily: np.ndarray, trial: np.ndarray) -> bool:
    """The new min of path - cumulative outflow stays >= 0, or no worse than it already was."""
    base_min = min(0, int((path - np.cumsum(daily)).min()))
    return int((path - np.cumsum(trial)).min()) >= base_min


def annualized_discount_return(bill: PlannableBill) -> float:
    """r = d / (1 - d) * 365 / (N - D) with N - D the days between the deadline and the due date (0 if none)."""
    t = bill.terms
    if not t.discount_bps or not bill.discount_deadline:
        return 0.0
    d = t.discount_bps / BPS_PER_UNIT
    window = (bill.due_date - bill.discount_deadline).days
    return d / (1 - d) * DAYS_IN_YEAR / window if window > 0 else 0.0


def path_plan(
    bills: tuple[PlannableBill, ...], options: Options, path: np.ndarray, as_of: date, policy: str
) -> Plan:
    """Solve the MILP against one deterministic headroom path (K = 0)."""
    return solve_plan(bills, options, path[None, :], as_of, 0, policy)


def quantile_path(headroom: np.ndarray, q: float) -> np.ndarray:
    """Pointwise quantile of headroom across scenarios (an actual sample value), as int64 cents."""
    return np.quantile(headroom, q, axis=0, method="lower").astype(np.int64)
