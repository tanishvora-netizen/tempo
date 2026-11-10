// Proof: policies on fresh scenarios, breach chart with upper bounds, certification, ablation,
// cost of cash, extraction accuracy, and solver stats. Everything comes from /api/evaluate,
// /api/state, and /api/cash-value.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, money, moneyExact, pct, perYear, seconds, shortDate } from "./format.js";
import { breachChart } from "./charts.js";
import { loadCashValue, loadEvaluate, loadState } from "./store.js";
import { extractionSection, wireExtraction } from "./extraction.js";

const POLICY = {
  pay_on_due: ["Pay on due date", "Every bill by bank on its due date"],
  weekly_run: ["Weekly AP run", "Today's practice: one run a week, discounts only inside the window"],
  greedy_discount: ["Greedy discounts", "Every discount and card option the median forecast allows"],
  greedy_p05: ["Smart spreadsheet", "Discounts that beat the cost of cash while each day's P5 stays above the buffer"],
  deterministic_p50: ["Optimizer on the median", "Same optimizer on the median forecast only, no risk limit"],
  tempo: ["Tempo", "Chance-constrained optimizer, certified out of sample"],
  per_day_5pct: ["Per-day 5% limit", "Each day separately at 5%, not the 13 weeks jointly"],
  bonferroni_per_day: ["Bonferroni per day", "Each day at 5% divided by the number of days"],
};

function policyName(id) {
  return POLICY[id]?.[0] ?? id;
}

/** Split a label into two lines at the space nearest the middle (Chart.js draws arrays as lines). */
function twoLines(label) {
  const words = label.split(" ");
  if (words.length < 2) return label;
  const cut = Math.ceil(words.length / 2);
  return [words.slice(0, cut).join(" "), words.slice(cut).join(" ")];
}

function section(id, title, sub, body, aside = "") {
  return html`<section class="panel" id="${id}" aria-labelledby="${id}-title" tabindex="-1">
    <div class="panel-head">
      <div><h2 id="${id}-title" class="panel-title">${title}</h2>${sub ? html`<p class="meta">${sub}</p>` : ""}</div>
      ${aside}
    </div>
    ${body}
  </section>`;
}

function policyRow(p, epsilon) {
  const tempo = p.policy === "tempo";
  const over = p.breach_upper > epsilon;
  return html`<tr class="${tempo ? "is-selected" : ""}">
    <td class="min-w-[170px]" title="${POLICY[p.policy]?.[1] ?? ""}"><div class="${tempo ? "font-semibold" : "font-medium"}">${policyName(p.policy)}</div><div class="meta max-w-[360px] max-[1200px]:hidden">${POLICY[p.policy]?.[1] ?? ""}</div></td>
    <td class="r num ${p.value_cents > 0 ? "gain" : ""}" title="${moneyExact(p.value_cents)}">${money(p.value_cents, { signed: true })}</td>
    <td class="r num max-[1200px]:hidden">${count(p.discount_count)}</td>
    <td class="r num max-[1200px]:hidden">${count(p.card_count)}</td>
    <td class="r num ${over ? "risk" : ""}">${pct(p.breach_rate)}</td>
    <td class="r num ${over ? "risk font-medium" : ""}">${pct(p.breach_upper)}</td>
    <td class="r num" title="${moneyExact(p.worst_p10_balance_cents)}">${money(p.worst_p10_balance_cents)} <span class="text-ink-3">${shortDate(p.worst_p10_date)}</span></td>
    <td class="r num ${p.late_count ? "risk" : "text-ink-3"}">${count(p.late_count)}</td>
    <td class="r num ${p.credit_drawn_cents ? "risk" : "text-ink-3"}">${money(p.credit_drawn_cents)}</td>
  </tr>`;
}

function policyTable(policies, epsilon, caption) {
  return html`<table class="tbl">
    <caption class="sr-only">${caption}</caption>
    <thead><tr>
      <th scope="col">Policy</th><th scope="col" class="r">Value vs pay on due</th><th scope="col" class="r max-[1200px]:hidden">Discounts</th><th scope="col" class="r max-[1200px]:hidden">Card</th>
      <th scope="col" class="r">Breach rate</th><th scope="col" class="r">95% bound</th><th scope="col" class="r">Lowest P10 cash</th>
      <th scope="col" class="r">Late</th><th scope="col" class="r">Credit drawn</th>
    </tr></thead>
    <tbody>${policies.map((p) => policyRow(p, epsilon))}</tbody>
  </table>`;
}

function policiesSection(ev, state) {
  const toggle = html`<div class="seg" role="group" aria-label="Which payment model scores the policies">
    <button type="button" data-model="fitted" aria-pressed="true">Fitted forecast model</button>
    <button type="button" data-model="true" aria-pressed="false">Generator's true model</button>
  </div>`;
  const body = html`<div data-policy-table class="overflow-x-auto">${policyTable(ev.policies, state.kpis.epsilon, "Policies scored on seed C")}</div>
    <div class="grid grid-cols-12 gap-4 border-t border-line p-4">
      <div class="col-span-8 max-[1180px]:col-span-12">
        <h3 class="section-title">Chance of any buffer breach in 13 weeks</h3>
        <p class="meta mb-2">Bar: measured rate. Tick: one-sided 95% upper bound. Red: the bound misses the target.</p>
        <div class="relative h-[240px]"><canvas id="breach-canvas" role="img" aria-label="Breach rate by policy with upper bounds and the target line"></canvas></div>
      </div>
      <div class="col-span-4 flex flex-col gap-2 text-sm text-ink-2 max-[1180px]:col-span-12">
        <p>Scored on <span class="num font-medium text-ink">${count(ev.policies[0]?.n_scenarios)}</span> fresh scenarios (seed C = <span class="num">${ev.seed_c}</span>) that no decision ever saw.</p>
        <p>The true-model view re-scores the same plans when customers follow the data generator's payment behavior instead of the fitted forecast: a robustness check on the forecast itself.</p>
      </div>
    </div>`;
  return section("policies", "Policies on fresh scenarios", "Value against paying every bill on its due date, and the chance of dropping below the buffer", body, toggle);
}

function certificationSection(state) {
  const c = state.certification;
  const r = c.reported;
  const steps = html`<table class="tbl">
    <caption class="sr-only">Certification ladder</caption>
    <thead><tr><th scope="col" class="r">N</th><th scope="col" class="r">K</th><th scope="col" class="r">In sample</th>
      <th scope="col" class="r">Seed B breaches</th><th scope="col" class="r">Rate</th><th scope="col" class="r">Bound</th><th scope="col">Result</th><th scope="col" class="r">Solve</th></tr></thead>
    <tbody>${c.steps.map(
      (s) => html`<tr>
        <td class="r num">${count(s.n)}</td><td class="r num">${count(s.k)}</td><td class="r num">${count(s.in_sample_breaches)}</td>
        <td class="r num">${count(s.cert_breaches)} / ${count(s.cert_n)}</td><td class="r num">${pct(s.cert_rate)}</td><td class="r num">${pct(s.cert_upper)}</td>
        <td>${s.passed ? html`<span class="chip chip-solid">${icon("check")}Pass</span>` : html`<span class="chip chip-risk">${icon("x")}Fail</span>`}</td>
        <td class="r num">${seconds(s.solve_seconds)}</td>
      </tr>`,
    )}</tbody>
  </table>`;
  const body = html`<div class="grid grid-cols-12 gap-0">
    <div class="col-span-5 flex flex-col gap-3 border-r border-line p-4 max-[1180px]:col-span-12 max-[1180px]:border-r-0 max-[1180px]:border-b">
      <p class="text-sm text-ink-2">Seed A builds the optimizer's ${count(c.n)} scenarios. Seed B (${count(c.steps[0]?.cert_n)} scenarios) decides whether the plan passes. Seed C is used only for the numbers we report.</p>
      <dl class="dl">
        <dt>Target</dt><dd class="num">at most ${pct(c.epsilon, 0)} chance of any breach</dd>
        <dt>Unprotected scenarios</dt><dd class="num">K = ${c.k} of N = ${c.n} (in-sample ${pct(c.in_sample_rate)})</dd>
        <dt>Certification test</dt><dd class="num">one-sided Wilson bound, Bonferroni z = ${c.z_certify.toFixed(3)}</dd>
        <dt>Reported (seed C)</dt><dd class="num">${count(r.breaches)} of ${count(r.n)} = ${pct(r.rate)}, bound ${pct(r.upper)} at z = ${r.z}</dd>
        <dt>Result</dt><dd>${r.passes ? html`<span class="chip chip-solid">${icon("shield-check")}Passes</span>` : html`<span class="chip chip-risk">${icon("x")}Misses the target</span>`}</dd>
      </dl>
    </div>
    <div class="col-span-7 overflow-x-auto max-[1180px]:col-span-12">${steps}</div>
  </div>`;
  return section("certification", "How the 5% holds", "Tempo lowers K until the plan passes on scenarios it was not built on", body);
}

function ablationSection(ev, state) {
  const body = html`<div class="overflow-x-auto">${policyTable(ev.ablations, state.kpis.epsilon, "Joint versus per-day chance constraints")}</div>
    <p class="border-t border-line px-4 py-3 text-sm text-ink-2">A per-day limit checks each day on its own, so the chance of a breach on some day adds up past the target. Bonferroni is safe but leaves money on the table. The joint constraint bounds the 13 weeks at once.</p>`;
  return section("ablation", "Joint vs per-day risk limits", "Same scenarios (seed C)", body);
}

function cashSection(cv, state) {
  const yieldOnCash = Number(state.assumptions.find((a) => a.name === "YIELD_ON_CASH")?.value);
  const body = html`<div class="flex flex-col gap-3 p-4">
    <dl class="dl">
      <dt>Plan value at today's cash</dt><dd class="num" title="${moneyExact(cv.base_objective_cents)}">${money(cv.base_objective_cents)}</dd>
      <dt>With ${money(cv.step_cents)} more cash</dt><dd class="num" title="${moneyExact(cv.bumped_objective_cents)}">${money(cv.bumped_objective_cents)}</dd>
      <dt>Value of an extra dollar</dt><dd class="num">${(cv.lam * 100).toFixed(2)} cents over the horizon, about ${perYear(cv.annual_rate, 2)}</dd>
      <dt>Yield on idle cash</dt><dd class="num">${perYear(yieldOnCash, 2)} (assumption)</dd>
      <dt>Cost of cash</dt><dd class="num font-semibold">${perYear(cv.cost_of_cash, 2)}${cv.credit_bound ? html` <span class="chip chip-risk">credit-bound</span>` : ""}</dd>
    </dl>
    <p class="text-xs text-ink-3">A MILP has no useful duals, so Tempo re-solves with more starting cash and takes the forward difference. Discounts are worth taking when their annualized return beats this rate.</p>
  </div>`;
  return section("cash", "Cost of cash", "Measured by re-solving, not assumed", body);
}

function solverSection(solver) {
  const ratio = solver.rows / solver.rows_naive;
  const body = html`<div class="grid grid-cols-12 gap-4 p-4">
    <div class="col-span-7 flex flex-col gap-3 max-[1180px]:col-span-12">
      <div>
        <div class="flex justify-between text-sm"><span>Naive formulation (every scenario, every day)</span><span class="num font-medium">${count(solver.rows_naive)} rows</span></div>
        <div class="mt-1 h-2.5 rounded-sm bg-[#d9d6ce]"></div>
      </div>
      <div>
        <div class="flex justify-between text-sm"><span>Tempo reduced (check days, quantile cut, tight big-M)</span><span class="num font-medium">${count(solver.rows)} rows</span></div>
        <div class="mt-1 h-2.5 rounded-sm bg-data" style="width:${Math.max(0.5, ratio * 100).toFixed(2)}%"></div>
      </div>
      <p class="text-xs text-ink-3">The reduced model is exact: tests check it against the full model and brute force on small cases.</p>
    </div>
    <dl class="dl col-span-5 max-[1180px]:col-span-12">
      <dt>Status</dt><dd>${solver.status}</dd>
      <dt>MIP gap</dt><dd class="num">${pct(solver.mip_gap, 4)}</dd>
      <dt>Solve time</dt><dd class="num">${seconds(solver.solve_seconds)} (whole case ${seconds(solver.case_seconds)})</dd>
      <dt>Nonzeros</dt><dd class="num">${count(solver.nonzeros)}</dd>
      <dt>Variables</dt><dd class="num">${count(solver.cols)}</dd>
      <dt>Days checked</dt><dd class="num">${count(solver.check_days)}</dd>
      <dt>Scenario rows kept</dt><dd class="num">${count(solver.scenario_rows)}</dd>
    </dl>
  </div>`;
  return section("solver", "Solver", "scipy.optimize.milp with HiGHS", body);
}

function drawBreach(ev, state, which) {
  const policies = which === "true" ? ev.policies_true_model : ev.policies;
  return breachChart($("#breach-canvas"), {
    labels: policies.map((p) => twoLines(policyName(p.policy))),
    rates: policies.map((p) => p.breach_rate),
    uppers: policies.map((p) => p.breach_upper),
    target: state.kpis.epsilon,
    highlight: policies.findIndex((p) => p.policy === "tempo"),
  });
}

export async function render(main, params) {
  const [ev, state, cv] = await Promise.all([loadEvaluate(), loadState(), loadCashValue()]);
  setHTML(
    main,
    html`<div class="flex flex-col gap-4">
      <div>
        <h1 class="text-xl">Proof</h1>
        <p class="text-sm text-ink-2">How Tempo compares with simpler policies on scenarios it never saw, how the risk limit is certified, and how well terms are read.</p>
      </div>
      ${policiesSection(ev, state)}
      ${certificationSection(state)}
      ${ablationSection(ev, state)}
      <div class="grid grid-cols-12 gap-4">
        <div class="col-span-5 max-[1180px]:col-span-12">${cashSection(cv, state)}</div>
        <div class="col-span-7 max-[1180px]:col-span-12">${solverSection(state.solver)}</div>
      </div>
      ${extractionSection(ev.extraction)}
    </div>`,
  );
  let chart = drawBreach(ev, state, "fitted");
  $$("[data-model]", main).forEach((btn) =>
    btn.addEventListener("click", () => {
      const which = btn.dataset.model;
      $$("[data-model]", main).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      const policies = which === "true" ? ev.policies_true_model : ev.policies;
      setHTML($("[data-policy-table]", main), policyTable(policies, state.kpis.epsilon, `Policies scored on seed C (${which === "true" ? "true" : "fitted"} model)`));
      chart.destroy();
      chart = drawBreach(ev, state, which);
    }),
  );
  wireExtraction(main, ev.extraction);
  const target = params.section && document.getElementById(params.section);
  if (target) {
    target.scrollIntoView({ block: "start" });
    target.focus({ preventScroll: true });
  }
  return () => chart.destroy();
}
