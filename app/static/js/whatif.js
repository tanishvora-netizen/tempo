// What-if: delay a large customer or apply a cash shock, re-forecast and re-solve.
// Presets are precomputed (instant, certified); custom runs solve live and are labeled as an
// out-of-sample estimate on seed B that is not re-certified.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, dollarsField, money, moneyExact, parseDollars, pct, seconds, shortDate } from "./format.js";
import { valueCell } from "./labels.js";
import { fanChart, PALETTE, updateSeries } from "./charts.js";
import { diffTable, riskMeter } from "./widgets.js";
import { loadForecast, loadPresets, loadState } from "./store.js";
import { runWhatIf } from "./api.js";

const MAX_DELAY_DAYS = 60;
const MAX_SHOCK_DOLLARS = 2_000_000;
const DEFAULT_DELAY_DAYS = 14;
const DEFAULT_SHOCK_DOLLARS = 150_000;
const TICK_MS = 100;

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
      <p class="hidden basis-full text-sm risk" role="alert" data-form-error></p>
    </form>
    <div class="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-3">
      <span class="mr-1 text-xs text-ink-2">Precomputed, instant:</span>
      ${presets.presets.map((p) => html`<button type="button" class="filter" data-preset="${p.id}" aria-pressed="false">${p.label}</button>`)}
    </div>
  </section>`;
}

function compareRow(label, before, after, fmt, { tone = "value" } = {}) {
  const delta = after - before;
  let deltaText = "";
  if (tone === "value") deltaText = valueCell(delta);
  if (tone === "rate") deltaText = html`<span class="num ${delta > 0 ? "risk" : "text-ink-2"}">${delta > 0 ? "+" : delta < 0 ? "−" : ""}${Math.abs(delta * 100).toFixed(2)} pts</span>`;
  if (tone === "balance") deltaText = html`<span class="num ${delta < 0 ? "risk" : "text-ink-2"}">${money(delta, { signed: true })}</span>`;
  return html`<tr><td class="text-ink-2">${label}</td>
    <td class="r num text-ink-2">${fmt(before)}</td><td class="r num font-medium">${fmt(after)}</td><td class="r">${deltaText}</td></tr>`;
}

function resultSummary(base, result) {
  const k = result.kpis;
  const live = result.source === "live";
  const rate = live ? result.estimate.rate : k.breach_rate;
  const upper = live ? result.estimate.upper : k.breach_upper;
  const over = upper > base.epsilon;
  const exact = (c) => html`<span title="${moneyExact(c)}">${money(c)}</span>`;
  return html`<div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      ${live
        ? html`<span class="chip chip-review">${icon("circle-alert")}Not re-certified</span>
          <span class="text-sm text-ink-2">Out-of-sample estimate on seed B; not re-certified. Re-solved live in <span class="num font-medium text-ink">${seconds(result.total_seconds)}</span>.</span>`
        : html`<span class="chip chip-solid">${icon("shield-check")}Certified</span>
          <span class="text-sm text-ink-2">Precomputed: certified on seed B, reported on ${count(result.certification.reported.n)} fresh seed-C scenarios. Solved in <span class="num">${seconds(result.solver.solve_seconds)}</span>.</span>`}
    </div>
    <table class="tbl">
      <thead><tr><th scope="col">Measure</th><th scope="col" class="r">Current plan</th><th scope="col" class="r">What-if plan</th><th scope="col" class="r">Change</th></tr></thead>
      <tbody>
        ${compareRow("Value vs paying on due date", base.value_vs_pay_on_due_cents, k.value_vs_pay_on_due_cents, exact)}
        ${compareRow("Discounts captured", base.discounts_captured_cents, k.discounts_captured_cents, exact)}
        ${compareRow("Card rewards", base.card_rewards_cents, k.card_rewards_cents, exact)}
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
  </div>`;
}

/** Late by choice (to stay above the buffer) is reported apart from bills that cannot arrive in time. */
function latenessNotice(k) {
  const byChoice = k.late_count ?? 0;
  const arriving = k.arrive_after_due_count ?? 0;
  if (!byChoice && !arriving) return "";
  const parts = [
    byChoice && html`<span class="num font-medium">${count(byChoice)}</span> ${byChoice === 1 ? "bill is" : "bills are"} paid late by choice to stay above the buffer`,
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
  if (cents === null || cents < 100 || cents > MAX_SHOCK_DOLLARS * 100) {
    return { error: `Enter a payment between $1 and ${money(MAX_SHOCK_DOLLARS * 100)}.` };
  }
  return { whatIf: { shock_cents: cents } };
}

function setBusy(root, busy, startedAt) {
  const btn = $("[data-run]", root);
  btn.disabled = busy;
  $$("[data-preset]", root).forEach((b) => (b.disabled = busy));
  $("[data-results]", root).setAttribute("aria-busy", String(busy));
  $("[data-results]", root).classList.toggle("opacity-60", busy);
  if (!busy) {
    setHTML(btn, html`${icon("play")}Re-solve plan`);
    return null;
  }
  const tick = () => setHTML(btn, html`${icon("loader-circle", "icon spin")}Re-forecasting and solving <span class="num">${((performance.now() - startedAt) / 1000).toFixed(1)} s</span>`);
  tick();
  return setInterval(tick, TICK_MS);
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
          <p class="text-sm text-ink-2">Pick a preset for an instant, certified answer, or set your own scenario and re-solve. A custom run takes a second or two.</p>
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
  setHTML($("[data-summary]", root), html`<h2 id="wi-summary" class="panel-title mb-3">${result.label ?? "Custom scenario"}</h2>${resultSummary(state.kpis, result)}`);
  const panel = $("[data-diff-panel]", root);
  panel.hidden = false;
  setHTML($("[data-diff-count]", root), `${result.diff.length} of the plan's decisions changed`);
  setHTML($("[data-diff]", root), diffTable(result.diff, { caption: "Decisions that flipped under this scenario" }));
}

function showError(root, err) {
  const el = $("[data-form-error]", root);
  el.textContent = err.message;
  el.classList.remove("hidden");
}

async function execute(root, state, chart, whatIf, label) {
  $("[data-form-error]", root).classList.add("hidden");
  const startedAt = performance.now();
  const timer = setBusy(root, true, startedAt);
  try {
    const result = await runWhatIf(whatIf);
    showResult(root, state, chart, { ...result, label: result.label ?? label });
  } catch (err) {
    showError(root, err);
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
