"""Baseline policies Tempo is compared against (directive 5.6, council C1).

1. pay_on_due         every bill by bank, arriving on its due date.
2. weekly_run         one run per week; each bill is sent in the last run on or before its send date; a
                      discount is taken when its deadline falls in a run window (ASSUMPTION: common practice).
3. greedy_discount    due-date order; take the best discount or card option the P50 balance path allows.
4. greedy_p05         the "smart spreadsheet": same, but checks the pointwise P5 path and only takes a
                      discount whose annualized return beats the cost of cash.
5. deterministic_p50  the same MILP on the P50 path only (one scenario, no chance constraint).
Ablations solve the MILP against a single pointwise-quantile path (per-day constraints instead of joint).
"""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from tempo.models import PaymentOption
from tempo.optimize.engine import Plan, solve_plan
from tempo.optimize.options import PlannableBill, yield_cents

RUN_INTERVAL_DAYS = 7
EARLY_KINDS = ("BANK_EARLY", "CARD_EARLY", "FINANCE_EARLY")


def _zero_credit(horizon: int) -> np.ndarray:
    return np.zeros(horizon, dtype=np.int64)


def pay_on_due(bills, options, horizon: int) -> Plan:
    choice = tuple(next(i for i, o in enumerate(opts) if o.kind == "BANK_DUE") for opts in options)
    return Plan("pay_on_due", bills, options, choice, _zero_credit(horizon))


def weekly_run(bills: tuple[PlannableBill, ...], options, as_of: date, horizon: int) -> Plan:
    """Shift each bill's bank payment back to the most recent weekly run day."""
    chosen = []
    for opts in options:
        due = next(o for o in opts if o.kind == "BANK_DUE")
        early = next((o for o in opts if o.kind == "BANK_EARLY"), None)
        target = early if early is not None and _run_on_or_before(early.send_date, as_of) >= as_of else due
        chosen.append(_shift(target, _run_on_or_before(target.send_date, as_of), due.cash_out_date))
    custom = tuple((o,) for o in chosen)
    return Plan("weekly_run", bills, custom, tuple(0 for _ in custom), _zero_credit(horizon))


def _run_on_or_before(d: date, as_of: date) -> date:
    weeks = max((d - as_of).days, 0) // RUN_INTERVAL_DAYS
    return as_of + timedelta(days=weeks * RUN_INTERVAL_DAYS)


def _shift(o: PaymentOption, run: date, base: date) -> PaymentOption:
    """Send on the run day instead; cash leaves then, so the yield term changes."""
    if run >= o.send_date:
        return o
    new_yield = yield_cents(o.cash_out_cents, run, base)
    return replace(
        o,
        send_date=run,
        cash_out_date=run,
        yield_cents=new_yield,
        value_cents=o.value_cents - o.yield_cents + new_yield,
    )


def greedy(
    bills: tuple[PlannableBill, ...],
    options,
    path: np.ndarray,
    as_of: date,
    policy: str,
    min_annual_return: float | None = None,
) -> Plan:
    """Due-date order; adopt the best-value non-late option that keeps `path - plan_cum` from getting worse
    below zero on any day. `path` is a single headroom path (P50 or P5)."""
    horizon = path.shape[0]
    choice = [next(i for i, o in enumerate(opts) if o.kind == "BANK_DUE") for opts in options]
    daily = np.zeros(horizon, dtype=np.int64)
    for opts, c in zip(options, choice, strict=True):
        daily[_day(opts[c], as_of, horizon)] += opts[c].cash_out_cents
    for i in sorted(range(len(bills)), key=lambda i: (bills[i].due_date, bills[i].id)):
        choice[i] = _greedy_pick(bills[i], options[i], choice[i], daily, path, as_of, min_annual_return)
    return Plan(policy, bills, options, tuple(choice), _zero_credit(horizon))


def _greedy_pick(bill, opts, current: int, daily: np.ndarray, path, as_of, min_annual_return) -> int:
    horizon = path.shape[0]
    base_min = min(0, int((path - np.cumsum(daily)).min()))
    ranked = sorted(
        (i for i, o in enumerate(opts) if o.kind != "LATE" and o.value_cents > opts[current].value_cents),
        key=lambda i: -opts[i].value_cents,
    )
    for i in ranked:
        too_cheap = min_annual_return is not None and annualized_discount_return(bill) <= min_annual_return
        if too_cheap and opts[i].kind in EARLY_KINDS:
            continue
        trial = daily.copy()
        trial[_day(opts[current], as_of, horizon)] -= opts[current].cash_out_cents
        trial[_day(opts[i], as_of, horizon)] += opts[i].cash_out_cents
        if int((path - np.cumsum(trial)).min()) >= base_min:
            daily[:] = trial
            return i
    return current


def _day(o: PaymentOption, as_of: date, horizon: int) -> int:
    return min(max((o.cash_out_date - as_of).days, 0), horizon - 1)


def annualized_discount_return(bill: PlannableBill) -> float:
    """r = d / (1 - d) * 365 / (N - D): simple annualized return of taking the discount (0 if none)."""
    t = bill.terms
    if not t.discount_bps or not bill.discount_deadline:
        return 0.0
    d = t.discount_bps / 10_000
    window = (bill.due_date - bill.discount_deadline).days
    return d / (1 - d) * 365 / window if window > 0 else 0.0


def path_plan(bills, options, path: np.ndarray, as_of: date, policy: str) -> Plan:
    """Solve the MILP against one deterministic headroom path (K = 0)."""
    plan = solve_plan(bills, options, path[None, :], as_of, 0, policy)
    return replace(plan, policy=policy)


def quantile_path(headroom: np.ndarray, q: float) -> np.ndarray:
    """Pointwise quantile of headroom across scenarios, as int64 cents."""
    return np.floor(np.quantile(headroom, q, axis=0, method="lower")).astype(np.int64)
