"""The chance-constrained bill-timing MILP (directive 5.5; full derivation in docs/MATH.md).

Variables: x[o] binary (one option per bill), C[d] cumulative plan outflow through check day d, G[d]
cumulative backstop credit (nondecreasing), z[s] binary "scenario s is protected".

    maximize   sum_o v[o] x[o] - CREDIT_COST * G[last]
    subject to sum_{o in bill i} x[o] = 1                              for every bill i
               C[d] = C[d-1] + sum_{o: day(o) = d} c[o] x[o]            (C[-1] = 0)
               G[d] >= G[d-1] >= 0
               C[d] - G[d] <= R[s, d] + M[s, d] (1 - z[s])              for scenarios s, check days d
               sum_s z[s] >= N - K

Only R (inflows) is random and G is the same in every scenario, so Luedtke-Ahmed-Nemhauser preprocessing
applies. Exact reductions:
1. Check days: day 0 plus every day on which the plan or a fixed outflow can take cash out (any day where
   R drops in some scenario). Between them slack only rises, so the minimum sits on a check day.
2. Quantile cut: with at most K unprotected scenarios, C[d] - G[d] <= q[d], the (K+1)-th smallest R[:, d].
3. Row drop and tight big-M: given the cut, rows with R[s, d] >= q[d] are implied and dropped; the at most
   K remaining rows per day use M[s, d] = q[d] - R[s, d], the smallest valid value.
"""

import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix

from tempo.assumptions import CREDIT_COST, SOLVER_MIP_REL_GAP, SOLVER_TIME_LIMIT_S
from tempo.models import PaymentOption
from tempo.optimize.cash import day_index

CENTS = 100.0
CREDIT_TOLERANCE = 0.01  # dollars: below one cent, phase-1 credit is numerical noise
NODE_LIMIT = 200_000  # branch-and-bound nodes: bounds effort independently of CPU speed (council C1, R3)


class SolverError(RuntimeError):
    """The solver returned no feasible plan (should not happen: the backstop credit keeps it feasible)."""


@dataclass(frozen=True)
class MilpStats:
    status: str  # "optimal" or "time_limit"
    mip_gap: float | None
    solve_seconds: float
    rows: int
    cols: int
    nonzeros: int
    rows_naive: int  # N * T scenario rows plus assignment rows: the formulation before any reduction
    check_days: int
    scenario_rows: int
    reduced: bool


@dataclass(frozen=True)
class MilpResult:
    choice: tuple[int, ...]  # chosen option index within each bill's option tuple
    credit_cum_cents: np.ndarray = field(repr=False)  # (T,) cumulative backstop credit by end of day
    objective_dollars: float
    stats: MilpStats


@dataclass(frozen=True)
class _Layout:
    opts: tuple[PaymentOption, ...]
    bill_of: np.ndarray
    opt_day: np.ndarray  # index into check days
    days: np.ndarray  # check day indices
    n_x: int
    n_d: int

    def c_col(self, d: int) -> int:
        return self.n_x + d

    def g_col(self, d: int) -> int:
        return self.n_x + self.n_d + d

    @property
    def z_start(self) -> int:
        return self.n_x + 2 * self.n_d


def check_days(headroom: np.ndarray, option_days: np.ndarray) -> np.ndarray:
    """Day 0, every option cash-out day, and every day where R drops in some scenario (sorted)."""
    drops = np.flatnonzero((np.diff(headroom, axis=1) < 0).any(axis=0)) + 1
    return np.unique(np.concatenate([[0], option_days, drops]))


def solve(
    bill_options: tuple[tuple[PaymentOption, ...], ...],
    headroom_cents: np.ndarray,
    as_of: date,
    k: int,
    *,
    reduced: bool = True,
    capacity: tuple[tuple[tuple[int, ...], int], ...] = (),
    credit_cost: float = CREDIT_COST,
    time_limit: float = SOLVER_TIME_LIMIT_S,
    mip_rel_gap: float = SOLVER_MIP_REL_GAP,
) -> MilpResult:
    """Solve the chance-constrained plan with at most `k` unprotected scenarios.

    `capacity` adds credit limits: each (flat option indices, cap in cents) row says
    sum of c[o] x[o] over those options <= cap (card charges per statement cycle, financed principal per window).
    """
    n_scen, horizon = headroom_cents.shape
    if not 0 <= k < n_scen:
        raise ValueError(f"k must be in [0, {n_scen}), got {k}")
    layout = _layout(bill_options, headroom_cents, as_of)
    r_d = headroom_cents[:, layout.days].astype(float) / CENTS
    rows = _Rows()
    _assignment_rows(rows, layout, len(bill_options))
    _recurrence_rows(rows, layout)
    _monotone_rows(rows, layout)
    for idx, cap in capacity:
        rows.add({int(j): layout.opts[j].cash_out_cents / CENTS for j in idx}, -np.inf, cap / CENTS)
    n_z, scenario_rows = (_reduced_rows if reduced else _full_rows)(rows, layout, r_d, k)
    n_cols = layout.z_start + n_z
    objective = np.zeros(n_cols)
    objective[: layout.n_x] = [-o.value_cents / CENTS for o in layout.opts]
    objective[layout.g_col(layout.n_d - 1)] = credit_cost
    integrality = np.zeros(n_cols)
    integrality[: layout.n_x] = 1
    integrality[layout.z_start :] = 1
    lb = np.zeros(n_cols)
    ub = np.full(n_cols, np.inf)
    ub[: layout.n_x] = 1
    ub[layout.z_start :] = 1
    a = rows.matrix(n_cols)
    constraints = LinearConstraint(a, rows.lb, rows.ub)
    g_cols = slice(layout.g_col(0), layout.g_col(0) + layout.n_d)
    started = time.perf_counter()
    ub[g_cols] = _minimum_credit(constraints, integrality, lb, ub, layout, time_limit)
    res = _run(objective, constraints, integrality, Bounds(lb, ub), time_limit, mip_rel_gap)
    elapsed = time.perf_counter() - started
    stats = MilpStats(
        status="optimal" if res.status == 0 else "time_limit",
        mip_gap=None if getattr(res, "mip_gap", None) is None else float(res.mip_gap),
        solve_seconds=elapsed,
        rows=a.shape[0],
        cols=n_cols,
        nonzeros=int(a.nnz),
        rows_naive=n_scen * horizon + len(bill_options) + 1,
        check_days=layout.n_d,
        scenario_rows=scenario_rows,
        reduced=reduced,
    )
    return MilpResult(
        _choices(res.x, layout, len(bill_options)), _credit(res.x, layout, horizon), -float(res.fun), stats
    )


def _run(objective, constraints, integrality, bounds, time_limit: float, mip_rel_gap: float):
    res = milp(
        objective,
        constraints=constraints,
        integrality=integrality,
        bounds=bounds,
        options={
            "time_limit": time_limit,
            "mip_rel_gap": mip_rel_gap,
            "node_limit": NODE_LIMIT,
            "disp": False,
        },
    )
    if res.x is None or res.status not in (0, 1):
        raise SolverError(f"HiGHS returned status {res.status}: {res.message}")
    return res


def _minimum_credit(constraints, integrality, lb, ub, layout: "_Layout", time_limit: float) -> float:
    """Phase 1 of a lexicographic solve: the least backstop credit any plan needs (dollars).

    The backstop exists only to keep the model feasible. Priced in the objective alone, a few cents of credit
    can unlock a large early payment, so credit would be used to buy value. Phase 1 minimizes credit; phase 2
    maximizes value with credit capped at that minimum (plus one cent of numerical tolerance), and any credit
    left over is exactly what feasibility requires.
    """
    phase1 = np.zeros(len(lb))
    phase1[layout.g_col(layout.n_d - 1)] = 1.0
    res = _run(phase1, constraints, integrality, Bounds(lb, ub), time_limit, 0.0)
    needed = float(res.fun)
    return 0.0 if needed < CREDIT_TOLERANCE else needed + CREDIT_TOLERANCE


class _Rows:
    """Sparse row accumulator: each row is {col: coef} with bounds lb <= a.x <= ub."""

    def __init__(self) -> None:
        self.data: list[float] = []
        self.r: list[int] = []
        self.c: list[int] = []
        self.lb: list[float] = []
        self.ub: list[float] = []

    def add(self, coefs: dict[int, float], lo: float, hi: float) -> None:
        row = len(self.lb)
        for col, val in coefs.items():
            self.r.append(row)
            self.c.append(col)
            self.data.append(val)
        self.lb.append(lo)
        self.ub.append(hi)

    def matrix(self, n_cols: int) -> csr_matrix:
        return csr_matrix((self.data, (self.r, self.c)), shape=(len(self.lb), n_cols))


def _layout(bill_options, headroom_cents: np.ndarray, as_of: date) -> _Layout:
    horizon = headroom_cents.shape[1]
    opts = tuple(o for opts in bill_options for o in opts)
    bill_of = np.array([i for i, opts in enumerate(bill_options) for _ in opts])
    raw_day = np.array([day_index(o.cash_out_date, as_of, horizon) for o in opts])
    days = check_days(headroom_cents, raw_day)
    pos = {int(d): j for j, d in enumerate(days)}
    opt_day = np.array([pos[int(d)] for d in raw_day])
    return _Layout(opts, bill_of, opt_day, days, len(opts), len(days))


def _assignment_rows(rows: _Rows, layout: _Layout, n_bills: int) -> None:
    for i in range(n_bills):
        rows.add({int(j): 1.0 for j in np.flatnonzero(layout.bill_of == i)}, 1.0, 1.0)


def _recurrence_rows(rows: _Rows, layout: _Layout) -> None:
    """C[d] - C[d-1] - sum_{o on day d} c[o] x[o] = 0."""
    for d in range(layout.n_d):
        coefs = {layout.c_col(d): 1.0}
        if d > 0:
            coefs[layout.c_col(d - 1)] = -1.0
        for j in np.flatnonzero(layout.opt_day == d):
            coefs[int(j)] = -layout.opts[j].cash_out_cents / CENTS
        rows.add(coefs, 0.0, 0.0)


def _monotone_rows(rows: _Rows, layout: _Layout) -> None:
    """G[d] - G[d-1] >= 0."""
    for d in range(1, layout.n_d):
        rows.add({layout.g_col(d): 1.0, layout.g_col(d - 1): -1.0}, 0.0, np.inf)


def _reduced_rows(rows: _Rows, layout: _Layout, r_d: np.ndarray, k: int) -> tuple[int, int]:
    """Quantile cut per check day plus at most K tight-big-M scenario rows per day."""
    q = np.partition(r_d, k, axis=0)[k]
    below = r_d < q[None, :]
    scen = np.flatnonzero(below.any(axis=1))
    z_of = {int(s): j for j, s in enumerate(scen)}
    for d in range(layout.n_d):
        rows.add({layout.c_col(d): 1.0, layout.g_col(d): -1.0}, -np.inf, float(q[d]))
    count = 0
    for s, d in zip(*np.nonzero(below), strict=True):
        m = float(q[d] - r_d[s, d])
        rows.add(
            {layout.c_col(d): 1.0, layout.g_col(d): -1.0, layout.z_start + z_of[int(s)]: m},
            -np.inf,
            float(r_d[s, d]) + m,
        )
        count += 1
    _cardinality_row(rows, layout, len(scen), k)
    return len(scen), count


def _cardinality_row(rows: _Rows, layout: _Layout, n_z: int, k: int) -> None:
    """At most k of the scenarios that have rows may be unprotected: sum z >= n_z - k."""
    if n_z:
        rows.add({layout.z_start + j: 1.0 for j in range(n_z)}, n_z - k, np.inf)


def _full_rows(rows: _Rows, layout: _Layout, r_d: np.ndarray, k: int) -> tuple[int, int]:
    """Naive SAA rows for every scenario and check day, big-M = max(0, Cmax[d] - R[s, d])."""
    c_max = _max_cumulative_outflow(layout)
    n_scen = r_d.shape[0]
    count = 0
    for s in range(n_scen):
        for d in range(layout.n_d):
            m = max(0.0, float(c_max[d] - r_d[s, d]))
            rows.add(
                {layout.c_col(d): 1.0, layout.g_col(d): -1.0, layout.z_start + s: m},
                -np.inf,
                float(r_d[s, d]) + m,
            )
            count += 1
    _cardinality_row(rows, layout, n_scen, k)
    return n_scen, count


def _max_cumulative_outflow(layout: _Layout) -> np.ndarray:
    """Upper bound on C[d]: for each bill, the largest cash-out among its options on or before day d."""
    c_max = np.zeros(layout.n_d)
    cash = np.array([o.cash_out_cents / CENTS for o in layout.opts])
    for i in np.unique(layout.bill_of):
        idx = np.flatnonzero(layout.bill_of == i)
        for d in range(layout.n_d):
            due = cash[idx][layout.opt_day[idx] <= d]
            c_max[d] += due.max() if due.size else 0.0
    return c_max


def _choices(x: np.ndarray, layout: _Layout, n_bills: int) -> tuple[int, ...]:
    out = []
    for i in range(n_bills):
        idx = np.flatnonzero(layout.bill_of == i)
        out.append(int(np.argmax(x[idx])))
    return tuple(out)


def _credit(x: np.ndarray, layout: _Layout, horizon: int) -> np.ndarray:
    """Cumulative credit per day in cents (step function between check days), rounded up to whole cents."""
    g = np.maximum(x[layout.g_col(0) : layout.g_col(0) + layout.n_d], 0.0)
    g_cents = np.ceil(np.round(g * CENTS, 6)).astype(np.int64)
    out = np.zeros(horizon, dtype=np.int64)
    for j, d in enumerate(layout.days):
        out[d:] = g_cents[j]
    return out
