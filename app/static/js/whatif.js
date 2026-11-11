// What-if: delay a large customer or apply a cash shock, re-forecast and re-solve.
// Presets are precomputed (instant, certified); custom runs solve live and are labeled as an
// out-of-sample estimate on seed B that is not re-certified.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, dollarsField, money, moneyExact, parseDollars, pct, seconds, shortDate } from "./format.js";
import { valueCell } from "./labels.js";
import { fanChart, PALETTE, updateSeries } from "./charts.js";
import { diffTable, riskMeter } from "./widgets.js";
import { loadForecast, loadPresets, loadState } from "./store.js";
import { getJob, runWhatIf } from "./api.js";

const MAX_DELAY_DAYS = 60;
const MAX_SHOCK_DOLLARS = 2_000_000;
const MIN_SHOCK_DOLLARS = 1_000;
const DEFAULT_DELAY_DAYS = 14;
const DEFAULT_SHOCK_DOLLARS = 150_000;
const TICK_MS = 100;
const POLL_MS = 1000;
const NOTICE_KEY = "tempo.hostingNotice.dismissed";
// Measured custom-solve times on the hosted free tier (seconds), filled in from the deploy check; null until then.
const HOSTED_SOLVE_SECONDS = null;

function controls(presets) {
  return html`<section class="panel" aria-labelledby="wi-controls">
    <div class="panel-head">
      <h2 id="wi-controls" class="panel-title">Scenario</h2>
      <div class="seg" role="group" aria-label="Kind of scenario">
        <button type="button" data-mode="delay" aria-pressed="true">A customer pays late</button>
        <button type="button" data-mode="shock" aria-pressed="false">An unexpected payment</button>
      </div>
    </div>
    <form class="flex flex-wrap items-end gap-4 px-4 py-4" data-form novalidate>
      <div class="flex flex-wrap items-end gap-4" data-mode-panel="delay">
        <label class="flex flex-col gap-1 text-xs text-ink-2">Customer
          <select class="field min-w-[260px]" name="customer">${presets.customers.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select>
        </label>
        <label class="flex flex-col gap-1 text-xs text-ink-2">Pays this many days later than forecast
          <span class="flex items-center gap-3">
            <input type="range" name="delay" min="0" max="${MAX_DELAY_DAYS}" step="1" value="${DEFAULT_DELAY_DAYS}" class="w-56" aria-describedby="delay-out">
            <output id="delay-out" class="num w-16 text-sm font-medium text-ink" data-delay-out>${DEFAULT_DELAY_DAYS} days</output>
          </span>
        </label>
      </div>
      <div class="flex flex-wrap items-end gap-4" data-mode-panel="shock" hidden>
        <label class="flex flex-col gap-1 text-xs text-ink-2">Unexpected payment today
          <span class="flex items-center gap-1.5"><span class="text-sm text-ink-2">$</span>
            <input type="text" name="shock" value="${dollarsField(DEFAULT_SHOCK_DOLLARS * 100)}" class="field w-40 num" inputmode="numeric">
          </span>
        </label>
      </div>
      <button type="submit" class="btn btn-primary h-9" data-run>${icon("play")}Re-solve plan</button>
      ${hostingNotice()}
      <p class="hidden basis-full text-sm" role="status" aria-live="polite" data-progress></p>
      <div class="hidden basis-full items-center gap-3 text-sm risk" role="alert" data-form-error><span data-error-text></span><button type="button" class="btn btn-sm" data-retry hidden>${icon("rotate-ccw")}Retry</button></div>
    </form>
    <div class="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-3">
      <span class="mr-1 text-xs text-ink-2">Precomputed, instant:</span>
      ${presets.presets.map((p) => html`<button type="button" class="filter" data-preset="${p.id}" aria-pressed="false">${p.label}</button>`)}
    </div>
  </section>`;
}

function noticeDismissed() {
  try {
    return window.localStorage.getItem(NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Honest, small, dismissible: presets are instant; custom runs solve live on a small CPU. */
function hostingNotice() {
  if (noticeDismissed()) return "";
  const times = HOSTED_SOLVE_SECONDS
    ? html` and take about <span class="num">${HOSTED_SOLVE_SECONDS[0]}</span> to <span class="num">${HOSTED_SOLVE_SECONDS[1]}</span> seconds`
    : "";
  return html`<p class="flex max-w-[560px] items-start gap-2 rounded-md border border-line bg-[#faf9f6] px-3 py-2 text-xs text-ink-2" data-notice>
    ${icon("info", "icon mt-0.5 flex-none")}
    <span>Live demo on a free hosting tier. Presets are precomputed and instant. Custom scenarios are solved live on a small CPU${times}. On a laptop the same solve takes a few seconds.</span>
    <button type="button" class="ml-auto flex-none text-ink-3 hover:text-ink" aria-label="Dismiss this notice" data-dismiss-notice>${icon("x")}</button>
  </p>`;
}

function compareRow(label, before, after, fmt, { tone = "value", total = false } = {}) {
  const delta = after - before;
  let deltaText = "";
  if (tone === "value") deltaText = valueCell(delta);
  if (tone === "rate") deltaText = html`<span class="num ${delta > 0 ? "risk" : "text-ink-2"}">${delta > 0 ? "+" : delta < 0 ? "−" : ""}${Math.abs(delta * 100).toFixed(2)} pts</span>`;
  if (tone === "balance") deltaText = html`<span class="num ${delta < 0 ? "risk" : "text-ink-2"}">${money(delta, { signed: true })}</span>`;
  const rule = total ? "border-t border-line-strong font-semibold" : "";
  return html`<tr class="${rule}"><td class="${total ? "text-ink" : "text-ink-2"}">${label}</td>
    <td class="r num text-ink-2">${fmt(before)}</td><td class="r num font-medium">${fmt(after)}</td><td class="r">${deltaText}</td></tr>`;
}

const wholeDollars = (cents) => Math.round(cents / 100);

/** Value minus discounts and rewards, in the same whole dollars the rows show, so the rows add up. */
function otherCents(k) {
  return (wholeDollars(k.value_vs_pay_on_due_cents) - wholeDollars(k.discounts_captured_cents) - wholeDollars(k.card_rewards_cents)) * 100;
}

function valueRows(base, k, exact) {
  return html`
    ${compareRow("Discounts captured", base.discounts_captured_cents, k.discounts_captured_cents, exact)}
    ${compareRow("Card rewards", base.card_rewards_cents, k.card_rewards_cents, exact)}
    ${compareRow("Yield, surcharges and fees", otherCents(base), otherCents(k), exact)}
    ${compareRow("Value vs paying on due date", base.value_vs_pay_on_due_cents, k.value_vs_pay_on_due_cents, exact, { total: true })}`;
}

/** The current plan's numbers on the same seed as the what-if: seed C for presets, seed B for live runs. */
function currentKpis(state, live) {
  return live && state.kpis_seed_b ? state.kpis_seed_b : state.kpis;
}

function resultSummary(state, result) {
  const k = result.kpis;
  const live = result.source === "live";
  const base = currentKpis(state, live);
  const rate = live ? result.estimate.rate : k.breach_rate;
  const upper = live ? result.estimate.upper : k.breach_upper;
  const over = upper > base.epsilon;
  const exact = (c) => html`<span title="${moneyExact(c)}">${money(c)}</span>`;
  return html`<div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      ${live
        ? html`<span class="chip chip-review">${icon("circle-alert")}Estimate on seed B, not certified</span>
          <span class="text-sm text-ink-2">Both columns are scored on the same ${count(result.estimate.n)} seed-B scenarios. Solved live in <span class="num font-medium text-ink">${seconds(result.total_seconds)}</span>${result.time_limit_reached ? html`; <span class="text-review font-medium">time limit reached, best plan found</span>` : ""}.</span>`
        : html`<span class="chip chip-solid">${icon("shield-check")}Certified</span>
          <span class="text-sm text-ink-2">Precomputed: certified on seed B; both columns reported on the same ${count(result.certification.reported.n)} fresh seed-C scenarios.</span>`}
    </div>
    <table class="tbl">
      <thead><tr><th scope="col">Measure</th><th scope="col" class="r">Current plan</th><th scope="col" class="r">What-if plan</th><th scope="col" class="r">Change</th></tr></thead>
      <tbody>
        ${valueRows(base, k, exact)}
        ${compareRow("Chance below buffer", base.breach_rate, rate, (x) => pct(x), { tone: "rate" })}
        ${compareRow("Lowest cash (P10)", base.worst_p10_balance_cents, k.worst_p10_balance_cents, exact, { tone: "balance" })}
      </tbody>
    </table>
    <div class="flex flex-col gap-1">
      <p class="text-sm text-ink-2">Chance of dipping below the buffer: <span class="num font-medium ${over ? "risk" : "text-ink"}">${pct(rate)}</span>, upper bound <span class="num">${pct(upper)}</span>.</p>
      ${riskMeter({ rate, upper, target: base.epsilon })}
    </div>
    ${latenessNotice(k)}
    ${k.credit_drawn_cents ? html`<p class="callout callout-risk">${icon("triangle-alert", "icon mt-0.5 flex-none")}You would need ${money(k.credit_drawn_cents)} of financing by ${shortDate(k.credit_first_date)}.</p>` : ""}
    ${result.tradeoff ? tradeoffBox(result.tradeoff, base.epsilon, live) : ""}
  </div>`;
}

function optionLine(n, title, body, ok) {
  return html`<li class="flex items-start gap-2.5 py-2">
    <span class="num mt-0.5 inline-flex h-5 w-5 flex-none items-center justify-center rounded-full border border-line-strong text-xs">${n}</span>
    <div class="min-w-0"><div class="font-medium ${ok === false ? "text-ink-2" : "text-ink"}">${title}</div><div class="text-sm text-ink-2">${body}</div></div>
  </li>`;
}

/** Three ways to respond to the scenario, priced on the same scenarios as the plan. */
function tradeoffBox(t, epsilon, live) {
  const f = t.financing;
  const l = t.late_only;
  const a = t.accept_risk;
  const target = pct(epsilon, 0);
  const value = (side) => html`plan value <span class="num font-medium text-ink" title="${moneyExact(side.value_cents)}">${money(side.value_cents, { signed: true })}</span>`;
  const rate = (side) => html`breach <span class="num">${pct(side.breach_rate)}</span> (bound <span class="num">${pct(side.breach_upper)}</span>)`;
  const finBody = f.under_target
    ? html`${value(f)} after <span class="num" title="${moneyExact(f.fees_cents)}">${money(f.fees_cents)}</span> in assumed Flex-style fees on ${count(f.financed_count)} ${f.financed_count === 1 ? "bill" : "bills"}, no late payments; ${rate(f)}.`
    : html`Financing alone can't keep the breach rate under ${target}${f.credit_drawn_cents ? html`: you would still need ${money(f.credit_drawn_cents)} of extra credit` : html`: ${rate(f)}`}.`;
  const lateBody = l.under_target
    ? l.late_count
      ? html`${value(l)} with <span class="num font-medium text-ink">${count(l.late_count)}</span> ${l.late_count === 1 ? "bill" : "bills"} paid late (<span class="num" title="${moneyExact(l.fees_cents)}">${money(l.fees_cents)}</span> in late fees), no financing; ${rate(l)}.`
      : html`${value(l)} with no late payments and no financing; ${rate(l)}.`
    : html`Late payments alone can't keep the breach rate under ${target}${l.credit_drawn_cents ? html`: you would still need ${money(l.credit_drawn_cents)} of extra credit` : html`: ${rate(l)}`}.`;
  const short = a.worst_shortfall_cents
    ? html` The worst scenario falls <span class="num font-medium" title="${moneyExact(a.worst_shortfall_cents)}">${money(a.worst_shortfall_cents)}</span> short of the buffer on ${shortDate(a.worst_shortfall_date)}.`
    : "";
  const riskBody = html`Breach rate <span class="num font-medium ${a.breach_upper > epsilon ? "risk" : "text-ink"}">${pct(a.breach_rate)}</span> (bound <span class="num">${pct(a.breach_upper)}</span>) if you keep the current plan unchanged.${short}`;
  return html`<div class="rounded-md border border-line">
    <div class="border-b border-line px-3 py-2"><h3 class="section-title">Ways to respond</h3>
      <p class="meta">Each priced on the same ${count(t.n)} ${live ? "seed-B" : "seed-C"} scenarios; options 1 and 2 are estimates, not separately certified.</p></div>
    <ol class="divide-y divide-line px-3">
      ${optionLine(1, `Stay under ${target} using financing`, finBody, f.under_target)}
      ${optionLine(2, `Stay under ${target} without financing (late payments if needed)`, lateBody, l.under_target)}
      ${optionLine(3, "Accept the risk", riskBody)}
    </ol>
  </div>`;
}

/** Late by choice (to stay above the buffer) is reported apart from bills that cannot arrive in time. */
function latenessNotice(k) {
  const byChoice = k.late_count ?? 0;
  const arriving = k.arrive_after_due_count ?? 0;
  if (!byChoice && !arriving) return "";
  const worst = byChoice && k.worst_shortfall_cents
    ? html`; financing is used first, and even so the worst scenario falls <span class="num font-medium" title="${moneyExact(k.worst_shortfall_cents)}">${money(k.worst_shortfall_cents)}</span> short of the buffer on ${shortDate(k.worst_shortfall_date)}`
    : "";
  const parts = [
    byChoice && html`<span class="num font-medium">${count(byChoice)}</span> ${byChoice === 1 ? "bill is" : "bills are"} paid late by choice to stay above the buffer${worst}`,
    arriving && html`<span class="num font-medium">${count(arriving)}</span> ${arriving === 1 ? "arrives" : "arrive"} after the due date because no rail sent from today is faster`,
  ].filter(Boolean);
  const tone = byChoice ? "callout-risk" : "";
  return html`<p class="callout ${tone} items-start">${icon(byChoice ? "triangle-alert" : "info", "icon mt-0.5 flex-none")}<span>${parts.length === 2 ? html`${parts[0]}; ${parts[1]}` : parts[0]}.</span></p>`;
}

function readRequest(form, mode) {
  if (mode === "delay") {
    const delay = Number(form.delay.value);
    if (!Number.isInteger(delay) || delay < 0 || delay > MAX_DELAY_DAYS) return { error: `Delay must be 0 to ${MAX_DELAY_DAYS} days.` };
    if (delay === 0) return { error: "Choose a delay of at least 1 day." };
    return { whatIf: { customer_id: form.customer.value, delay_days: delay } };
  }
  const cents = parseDollars(form.shock.value);
  if (cents === null || cents < MIN_SHOCK_DOLLARS * 100 || cents > MAX_SHOCK_DOLLARS * 100) {
    return { error: `Enter a payment between ${money(MIN_SHOCK_DOLLARS * 100)} and ${money(MAX_SHOCK_DOLLARS * 100)}.` };
  }
  return { whatIf: { shock_cents: cents } };
}

function setBusy(root, busy, startedAt, progress) {
  const btn = $("[data-run]", root);
  const line = $("[data-progress]", root);
  btn.disabled = busy;
  $$("[data-preset]", root).forEach((b) => (b.disabled = busy));
  $("[data-results]", root).setAttribute("aria-busy", String(busy));
  $("[data-results]", root).classList.toggle("opacity-60", busy);
  if (!busy) {
    setHTML(btn, html`${icon("play")}Re-solve plan`);
    line.classList.add("hidden");
    return null;
  }
  const tick = () => {
    const secs = ((performance.now() - startedAt) / 1000).toFixed(0);
    setHTML(btn, html`${icon("loader-circle", "icon spin")}Solving <span class="num">${secs} s</span>`);
    const p = progress.state;
    const text = p.queued
      ? html`Another scenario is solving, yours is next${p.position > 1 ? html` (<span class="num">${p.position}</span> ahead)` : ""}. <span class="num">${secs}</span> s`
      : p.live
        ? html`Solving ${count(progress.bills)} bills across ${count(progress.scenarios)} scenarios, then checking ${count(progress.check)} fresh ones. <span class="num">${secs}</span> s elapsed.`
        : html`Loading the precomputed result.`;
    setHTML(line, text);
    line.classList.remove("hidden");
  };
  tick();
  return setInterval(tick, TICK_MS * 5);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Start a custom solve, then poll its job every second until it finishes. Presets answer at once. */
async function solve(whatIf, progress) {
  const first = await runWhatIf(whatIf);
  if (first.source !== "job") return first;
  progress.state = { live: true, queued: first.status === "queued" && first.position > 0, position: first.position };
  let job = first;
  while (job.status === "queued" || job.status === "running") {
    await sleep(POLL_MS);
    job = await getJob(first.job_id);
    progress.state = { live: true, queued: job.status === "queued" && job.position > 0, position: job.position };
  }
  if (job.status === "error") throw new Error(job.error ?? "The solve failed. Please retry.");
  return { ...job.result, cached: job.cached };
}

export async function render(main) {
  const [state, forecast, presets] = await Promise.all([loadState(), loadForecast(), loadPresets()]);
  setHTML(
    main,
    html`<div class="flex flex-col gap-4">
      <div>
        <h1 class="text-xl">What-if</h1>
        <p class="text-sm text-ink-2">Move a big customer's payments later or take an unexpected hit, then see which decisions flip and why.</p>
      </div>
      ${controls(presets)}
      <div class="grid grid-cols-12 gap-4 transition-opacity" data-results aria-busy="false">
        <section class="panel col-span-7 flex flex-col max-[1180px]:col-span-12" aria-labelledby="wi-fan">
          <div class="panel-head"><div><h2 id="wi-fan" class="panel-title">End-of-day cash</h2><p class="meta">Pointwise 10th–90th percentile band and median</p></div>
            <div class="flex gap-4 text-xs text-ink-2">
              <span class="inline-flex items-center gap-1.5"><span class="swatch" style="background:${PALETTE.dataBand}"></span>Current plan</span>
              <span class="inline-flex items-center gap-1.5"><span class="swatch" style="background:${PALETTE.whatIfBand};box-shadow:inset 0 -2px 0 ${PALETTE.whatIf}"></span>What-if plan</span>
            </div>
          </div>
          <div class="relative min-h-[320px] flex-1 px-3 py-3"><canvas id="wi-canvas" role="img" aria-label="Fan chart comparing the current plan with the what-if plan"></canvas></div>
        </section>
        <section class="panel col-span-5 p-4 max-[1180px]:col-span-12" aria-labelledby="wi-summary" data-summary>
          <h2 id="wi-summary" class="panel-title mb-2">Result</h2>
          <p class="text-sm text-ink-2">Pick a preset for an instant, certified answer, or set your own scenario and re-solve it live.</p>
        </section>
        <section class="panel col-span-12 overflow-clip" aria-labelledby="wi-diff" data-diff-panel hidden>
          <div class="panel-head"><h2 id="wi-diff" class="panel-title">Decisions that flipped</h2><p class="meta" data-diff-count></p></div>
          <div data-diff></div>
        </section>
      </div>
    </div>`,
  );
  const chart = fanChart($("#wi-canvas", main), {
    dates: forecast.fan.dates,
    bufferCents: forecast.fan.buffer_cents,
    series: [
      { label: "Current plan", data: forecast.fan.after, style: { line: PALETTE.data, fill: PALETTE.dataBand } },
      { label: "What-if", data: forecast.fan.after, style: { line: PALETTE.whatIf, fill: PALETTE.whatIfBand, width: 2, hidden: true } },
    ],
  });
  wire(main, state, chart, presets);
  return () => chart.destroy();
}

function showResult(root, state, chart, result) {
  const fan = result.source === "live" ? result.fan_after : result.fan.after;
  updateSeries(chart, "What-if", fan);
  setHTML($("[data-summary]", root), html`<h2 id="wi-summary" class="panel-title mb-3">${result.label ?? "Custom scenario"}</h2>${resultSummary(state, result)}`);
  const panel = $("[data-diff-panel]", root);
  panel.hidden = false;
  setHTML($("[data-diff-count]", root), `${result.diff.length} of the plan's decisions changed`);
  setHTML($("[data-diff]", root), diffTable(result.diff, { caption: "Decisions that flipped under this scenario" }));
}

function showError(root, err, retry = null) {
  const el = $("[data-form-error]", root);
  $("[data-error-text]", root).textContent = err.message;
  const btn = $("[data-retry]", root);
  btn.hidden = !retry;
  btn.onclick = retry;
  el.classList.remove("hidden");
  el.classList.add("flex");
}

function hideError(root) {
  const el = $("[data-form-error]", root);
  el.classList.add("hidden");
  el.classList.remove("flex");
}

async function execute(root, state, chart, whatIf, label) {
  hideError(root);
  const startedAt = performance.now();
  const progress = {
    state: { live: !whatIf.preset_id },
    bills: state.bill_count,
    scenarios: state.certification.n,
    check: state.certification.steps[0]?.cert_n ?? 10000,
  };
  const timer = setBusy(root, true, startedAt, progress);
  try {
    const result = await solve(whatIf, progress);
    showResult(root, state, chart, { ...result, label: result.label ?? label });
  } catch (err) {
    showError(root, err, () => execute(root, state, chart, whatIf, label));
  } finally {
    clearInterval(timer);
    setBusy(root, false);
  }
}

function customLabel(form, mode) {
  if (mode === "shock") return `Unexpected ${money(parseDollars(form.shock.value))} payment today`;
  const name = form.customer.selectedOptions[0]?.textContent ?? "Customer";
  return `${name} pays ${form.delay.value} days late`;
}

function setMode(root, view, mode) {
  view.mode = mode;
  $$("[data-mode]", root).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
  $$("[data-mode-panel]", root).forEach((p) => (p.hidden = p.dataset.modePanel !== mode));
}

/** Make the form show exactly what a preset runs, so the controls and the result never disagree. */
function syncFormToPreset(root, form, view, preset) {
  const w = preset.what_if;
  if (w.customer_id) {
    setMode(root, view, "delay");
    form.customer.value = w.customer_id;
    form.delay.value = String(w.delay_days);
    $("[data-delay-out]", root).textContent = `${w.delay_days} days`;
  } else {
    setMode(root, view, "shock");
    form.shock.value = dollarsField(w.shock_cents);
  }
}

function clearPresets(root) {
  $$("[data-preset]", root).forEach((b) => b.setAttribute("aria-pressed", "false"));
}

function wire(root, state, chart, presets) {
  const form = $("[data-form]", root);
  $("[data-dismiss-notice]", root)?.addEventListener("click", () => {
    try {
      window.localStorage.setItem(NOTICE_KEY, "1");
    } catch {
      /* private mode: the notice just comes back next time */
    }
    $("[data-notice]", root)?.remove();
  });
  const view = { mode: "delay" };
  $$("[data-mode]", root).forEach((btn) =>
    btn.addEventListener("click", () => {
      setMode(root, view, btn.dataset.mode);
      clearPresets(root);
    }),
  );
  form.delay.addEventListener("input", () => {
    $("[data-delay-out]", root).textContent = `${form.delay.value} days`;
    clearPresets(root);
  });
  form.customer.addEventListener("change", () => clearPresets(root));
  form.shock.addEventListener("input", () => clearPresets(root));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const { whatIf, error } = readRequest(form, view.mode);
    clearPresets(root);
    if (error) return showError(root, { message: error });
    execute(root, state, chart, whatIf, customLabel(form, view.mode));
  });
  $$("[data-preset]", root).forEach((btn) =>
    btn.addEventListener("click", () => {
      const preset = presets.presets.find((p) => p.id === btn.dataset.preset);
      if (preset) syncFormToPreset(root, form, view, preset);
      $$("[data-preset]", root).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      execute(root, state, chart, { preset_id: btn.dataset.preset }, btn.textContent);
    }),
  );
}
