// Overview: KPI strip, fan chart with the any-day breach probability, and this week's run.
import { $, $$, html, icon, onActivate, setHTML } from "./dom.js";
import { addDays, count, longDate, money, moneyExact, moneyShort, pct, perYear, shortDate } from "./format.js";
import { chip, OPTION_SHORT, railCell, valueCell } from "./labels.js";
import { applyVisibility, fanChart, PALETTE } from "./charts.js";
import { riskMeter } from "./widgets.js";
import { loadBills, loadEvaluate, loadForecast, loadState } from "./store.js";
import { approvalPanel, wireApproval } from "./approval.js";
import { openBillPanel } from "./billpanel.js";
import { openNegotiateDrawer } from "./drawers.js";

const RUN_WINDOW_DAYS = 7;
const WORST_LOOKBACK_DAYS = 6;
const DEFAULT_FAN_VIEW = "both";
const COMPARED_POLICIES = [
  ["weekly_run", "Weekly AP run (today)"],
  ["greedy_discount", "Take every discount"],
  ["tempo", "Tempo"],
];

function assumption(state, name) {
  return state.assumptions.find((a) => a.name === name)?.value ?? null;
}

function kpiCell({ label, value, title, sub, href, tone = "" }) {
  return html`<a class="kpi border-line [&:not(:first-child)]:border-l max-[1180px]:[&:nth-child(4)]:border-l-0 max-[1180px]:[&:nth-child(n+4)]:border-t" href="${href}">
    <span class="label">${label}</span>
    <span class="kpi-value num ${tone}" title="${title}">${value}</span>
    <span class="kpi-sub">${sub}</span>
  </a>`;
}

function kpiStrip(state) {
  const k = state.kpis;
  const yieldOnCash = Number(assumption(state, "YIELD_ON_CASH"));
  const worstFrom = addDays(k.worst_p10_date, -WORST_LOOKBACK_DAYS);
  const overTarget = k.breach_upper > k.epsilon;
  return html`<section class="panel grid grid-cols-6 overflow-hidden max-[1180px]:grid-cols-3" aria-label="Key numbers">
    ${kpiCell({
      label: "Value vs pay on due date",
      value: moneyShort(k.value_vs_pay_on_due_cents, { signed: true }),
      title: `${moneyExact(k.value_vs_pay_on_due_cents)} over 13 weeks`,
      sub: "over 13 weeks",
      href: "#/run?sort=value",
      tone: k.value_vs_pay_on_due_cents > 0 ? "gain" : "",
    })}
    ${kpiCell({
      label: "Discounts captured",
      value: moneyShort(k.discounts_captured_cents),
      title: moneyExact(k.discounts_captured_cents),
      sub: `${count(k.discounts_captured_count)} bills paid early`,
      href: "#/run?filter=discount",
      tone: "gain",
    })}
    ${kpiCell({
      label: "Card rewards",
      value: moneyShort(k.card_rewards_cents),
      title: moneyExact(k.card_rewards_cents),
      sub: `${count(k.card_count)} bills on card`,
      href: "#/run?filter=card",
      tone: "gain",
    })}
    ${kpiCell({
      label: "Chance below buffer",
      value: pct(k.breach_rate),
      title: `Out-of-sample rate ${pct(k.breach_rate)}; one-sided 95% upper bound ${pct(k.breach_upper)}`,
      sub: `bound ${pct(k.breach_upper)}, target ${pct(k.epsilon, 0)}`,
      href: "#/proof?section=certification",
      tone: overTarget ? "risk" : "",
    })}
    ${kpiCell({
      label: "Lowest cash (P10)",
      value: moneyShort(k.worst_p10_balance_cents),
      title: `${moneyExact(k.worst_p10_balance_cents)} on ${longDate(k.worst_p10_date)}; buffer ${moneyExact(k.buffer_cents)}`,
      sub: `${shortDate(k.worst_p10_date)}; buffer ${moneyShort(k.buffer_cents)}`,
      href: `#/run?from=${worstFrom}&to=${k.worst_p10_date}`,
    })}
    ${kpiCell({
      label: "Cost of cash",
      value: perYear(k.cost_of_cash),
      title: `Yield on idle cash ${perYear(yieldOnCash)} plus the plan value of an extra dollar ${perYear(state.cash_value.annual_rate)}`,
      sub: k.cost_of_cash_credit_bound ? "credit-bound estimate" : `${perYear(yieldOnCash)} yield + ${perYear(state.cash_value.annual_rate)} plan`,
      href: "#/proof?section=cash",
    })}
    ${valueBreakdown(k)}
  </section>`;
}

/** The value tile as a sum the reader can check: discounts + rewards + yield - surcharges - fees. */
function valueBreakdown(k) {
  if (k.yield_cents === undefined) return "";
  const term = (cents, label) => html`<span class="num font-medium text-ink" title="${moneyExact(cents)}">${moneyShort(cents)}</span> ${label}`;
  const yieldPart = k.yield_cents < 0
    ? html` − ${term(-k.yield_cents, "yield forgone on cash paid early")}`
    : html` + ${term(k.yield_cents, "yield kept by paying later")}`;
  const costs = (k.surcharge_cents ?? 0) + (k.fees_cents ?? 0);
  return html`<p class="col-span-6 border-t border-line px-4 py-2 text-xs text-ink-2 max-[1180px]:col-span-3">
    Value <span class="num font-medium text-ink" title="${moneyExact(k.value_vs_pay_on_due_cents)}">${moneyShort(k.value_vs_pay_on_due_cents, { signed: true })}</span>
    = ${term(k.discounts_captured_cents, "discounts")} + ${term(k.card_rewards_cents, "card rewards")}${yieldPart}
    − ${term(costs, "surcharges and fees")}
  </p>`;
}

function legendItem(swatch, text) {
  return html`<span class="inline-flex items-center gap-1.5">${swatch}${text}</span>`;
}

function fanPanel(forecast) {
  const band = (color) => html`<span class="swatch" style="background:${color}"></span>`;
  const line = (color, dashed) => html`<span class="inline-block w-5 border-t-2 ${dashed ? "border-dashed" : ""}" style="border-color:${color}"></span>`;
  return html`<section class="panel col-span-8 flex flex-col max-[1180px]:col-span-12" aria-labelledby="fan-title">
    <div class="panel-head">
      <div>
        <h2 id="fan-title" class="panel-title">End-of-day cash, next 13 weeks</h2>
        <p class="meta">${count(forecast.fan.n)} forecast scenarios of when customers actually pay</p>
      </div>
      <div class="seg" role="group" aria-label="Which plan to show">
        <button type="button" data-view="after" aria-pressed="false">Tempo plan</button>
        <button type="button" data-view="before" aria-pressed="false">Pay on due date</button>
        <button type="button" data-view="both" aria-pressed="true">Compare</button>
      </div>
    </div>
    <div class="relative min-h-[340px] flex-1 px-3 pt-3">
      <canvas id="fan-canvas" role="img" aria-label="Fan chart of end-of-day cash with a pointwise 10th to 90th percentile band, the median, and the buffer line"></canvas>
    </div>
    <div class="flex flex-wrap gap-x-5 gap-y-1 border-t border-line px-4 py-2.5 text-xs text-ink-2">
      ${legendItem(band(PALETTE.dataBand), "Pointwise 10th–90th percentile")}
      ${legendItem(line(PALETTE.data), "Tempo plan, median")}
      ${legendItem(line(PALETTE.before, true), "Pay every bill on its due date, median")}
      ${legendItem(line(PALETTE.ink3, true), "Buffer")}
      ${legendItem(html`<span class="text-ink" aria-hidden="true">▼</span>`, "Large payment")}
    </div>
  </section>`;
}

function comparison(evaluate, epsilon) {
  const rows = COMPARED_POLICIES.map(([id, label]) => [label, evaluate.policies.find((p) => p.policy === id)]).filter(([, p]) => p);
  return html`<div class="border-t border-line px-4 py-3">
    <div class="mb-1 flex items-baseline justify-between">
      <h3 class="label">Same scenarios, other ways to pay</h3>
      <a class="text-xs font-medium text-ink-2 underline decoration-line-strong underline-offset-2 hover:text-ink" href="#/proof">All policies</a>
    </div>
    <table class="w-full text-sm">
      <caption class="sr-only">Value and breach chance by policy on the same fresh scenarios</caption>
      <thead class="sr-only"><tr><th scope="col">Policy</th><th scope="col">Value</th><th scope="col">Chance below buffer</th></tr></thead>
      <tbody>${rows.map(([label, p]) => html`<tr class="${p.policy === "tempo" ? "font-semibold" : ""}">
        <td class="py-0.5">${label}</td>
        <td class="num py-0.5 text-right ${p.value_cents > 0 ? "gain" : ""}" title="${moneyExact(p.value_cents)}">${moneyShort(p.value_cents, { signed: true })}</td>
        <td class="num w-16 py-0.5 text-right ${p.breach_upper > epsilon ? "risk" : ""}" title="95% upper bound ${pct(p.breach_upper)}">${pct(p.breach_rate)}</td>
      </tr>`)}</tbody>
    </table>
  </div>`;
}

function riskPanel(state, evaluate, vendorsWithoutTerms) {
  const k = state.kpis;
  const c = state.certification;
  const over = k.breach_upper > k.epsilon;
  return html`<section class="panel col-span-4 flex flex-col max-[1180px]:col-span-12" aria-labelledby="risk-title">
    <div class="flex flex-col gap-3 p-4">
      <h2 id="risk-title" class="section-title">Chance cash drops below the buffer on any day in the 13 weeks</h2>
      <p class="text-[34px] font-semibold leading-none tracking-[-0.02em] num ${over ? "risk" : ""}">${pct(k.breach_rate)}</p>
      ${riskMeter({ rate: k.breach_rate, upper: k.breach_upper, target: k.epsilon })}
      <p class="text-sm text-ink-2">
        One-sided 95% upper bound <span class="num font-medium text-ink">${pct(k.breach_upper)}</span> on
        <span class="num">${count(c.reported.n)}</span> fresh scenarios the optimizer never saw.
        ${c.passed ? html`Certified against the ${pct(c.epsilon, 0)} target.` : html`<span class="risk font-medium">Certification failed.</span>`}
        The chart's band is pointwise, day by day; this counts a breach on any day.
      </p>
    </div>
    ${evaluate ? comparison(evaluate, k.epsilon) : ""}
    <div class="flex flex-col gap-1.5 border-t border-line px-4 py-3 text-sm">
      ${latenessLines(k)}
      ${k.credit_drawn_cents
        ? html`<p class="flex items-center gap-2 risk">${icon("triangle-alert")}You need ${money(k.credit_drawn_cents)} of financing by ${shortDate(k.credit_first_date)}.</p>`
        : html`<p class="flex items-center gap-2 text-ink-2">${icon("check", "icon text-ink-3")}No emergency credit is needed.</p>`}
    </div>
    <div class="mt-auto flex items-center justify-between gap-3 border-t border-line px-4 py-3">
      <p class="text-sm text-ink-2"><span class="num font-medium text-ink">${count(vendorsWithoutTerms)}</span> vendors offer no discount terms.</p>
      <button type="button" class="btn btn-sm" data-negotiate>${icon("handshake")}Negotiate terms</button>
    </div>
  </section>`;
}

/** Late by choice (the LATE option) is separate from bills that cannot arrive by their due date. */
function latenessLines(k) {
  const arriving = k.arrive_after_due_count ?? 0;
  const byChoice = k.late_count
    ? html`<p class="flex items-start gap-2 risk">${icon("triangle-alert", "icon mt-0.5 flex-none")}<span>${count(k.late_count)} ${k.late_count === 1 ? "bill is" : "bills are"} paid late by choice.</span></p>`
    : html`<p class="flex items-start gap-2 text-ink-2">${icon("check", "icon mt-0.5 flex-none text-ink-3")}<span>No bill is paid late${arriving ? " by choice" : ""}.</span></p>`;
  if (!arriving) return byChoice;
  return html`${byChoice}<p class="flex items-start gap-2 text-ink-2">${icon("info", "icon mt-0.5 flex-none text-ink-3")}<span>
    <a class="font-medium text-ink underline decoration-line-strong underline-offset-2" href="#/run?filter=arrives_late">${count(arriving)} ${arriving === 1 ? "arrives" : "arrive"} after the due date</a>
    because a bank payment sent today can't arrive sooner.</span></p>`;
}

function weekRows(state, bills) {
  const start = state.company.as_of;
  const end = addDays(start, RUN_WINDOW_DAYS - 1);
  return bills
    .filter((b) => b.send_date && b.send_date >= start && b.send_date <= end)
    .sort((a, b) => a.send_date.localeCompare(b.send_date) || b.amount_cents - a.amount_cents);
}

function weekTable(rows) {
  return html`<table class="tbl">
    <caption class="sr-only">Bills Tempo sends in the next 7 days</caption>
    <thead><tr>
      <th scope="col">Vendor</th>
      <th scope="col" class="r">Amount</th>
      <th scope="col">Terms</th>
      <th scope="col">Decision</th>
      <th scope="col">Send</th>
      <th scope="col" class="max-[1180px]:hidden">Rail</th>
      <th scope="col" class="r">Value</th>
    </tr></thead>
    <tbody>
      ${rows.map(
        (b) => html`<tr class="clickable" tabindex="0" data-bill="${b.bill_id}">
          <td><div class="font-medium">${b.vendor}</div><div class="meta">${b.invoice_number}</div></td>
          <td class="r num" title="${moneyExact(b.amount_cents)}">${money(b.amount_cents)}</td>
          <td><div class="flex flex-wrap items-center gap-1.5"><span class="whitespace-nowrap">${b.terms}</span>${chip(b.chip)}</div></td>
          <td>${b.option === "LATE" ? html`<span class="risk font-medium">Late</span>` : OPTION_SHORT[b.option]}</td>
          <td class="num">${shortDate(b.send_date)}</td>
          <td class="max-[1180px]:hidden">${railCell(b.rail)}</td>
          <td class="r">${valueCell(b.value_cents)}</td>
        </tr>`,
      )}
    </tbody>
  </table>`;
}

function weekPanel(state, rows) {
  const total = rows.reduce((s, b) => s + b.cash_out_cents, 0);
  const value = rows.reduce((s, b) => s + b.value_cents, 0);
  const start = state.company.as_of;
  const end = addDays(start, RUN_WINDOW_DAYS - 1);
  return html`<section class="panel col-span-12 flex max-[1180px]:flex-col" aria-labelledby="week-title">
    <div class="min-w-0 flex-1">
      <div class="panel-head">
        <div>
          <h2 id="week-title" class="panel-title">This week's run</h2>
          <p class="meta">Bills Tempo sends ${shortDate(start)} to ${shortDate(end)}</p>
        </div>
        <dl class="flex gap-6 text-right">
          <div><dt class="label">Bills</dt><dd class="num font-semibold">${count(rows.length)}</dd></div>
          <div><dt class="label">Paid out</dt><dd class="num font-semibold" title="${moneyExact(total)}">${money(total)}</dd></div>
          <div><dt class="label">Value</dt><dd class="num font-semibold ${value > 0 ? "gain" : ""}" title="${moneyExact(value)}">${money(value, { signed: true })}</dd></div>
        </dl>
      </div>
      <div class="max-h-[420px] overflow-y-auto">${rows.length ? weekTable(rows) : html`<p class="p-6 text-center text-sm text-ink-2">No bills go out this week.</p>`}</div>
    </div>
    ${approvalPanel(state, rows)}
  </section>`;
}

function vendorsWithoutDiscount(bills) {
  const withTerms = new Set(bills.filter((b) => b.terms.includes("/")).map((b) => b.vendor_id));
  return new Set(bills.filter((b) => !withTerms.has(b.vendor_id)).map((b) => b.vendor_id)).size;
}

function wireFan(main, forecast, state) {
  const { fan, markers } = forecast;
  const chart = fanChart($("#fan-canvas", main), {
    dates: fan.dates,
    bufferCents: fan.buffer_cents,
    markers,
    worst: { date: state.kpis.worst_p10_date, text: `Lowest P10 ${moneyShort(state.kpis.worst_p10_balance_cents)}, ${shortDate(state.kpis.worst_p10_date)}` },
    series: [
      { label: "Pay on due date", data: fan.before, style: { line: PALETTE.before, fill: PALETTE.beforeBand, dash: [5, 4], width: 1.5 } },
      { label: "Tempo plan", data: fan.after, style: { line: PALETTE.data, fill: PALETTE.dataBand } },
    ],
  });
  applyVisibility(chart, (ds) => fanVisible(ds, DEFAULT_FAN_VIEW), { animate: false });
  $$("[data-view]", main).forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("[data-view]", main).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      applyVisibility(chart, (ds) => fanVisible(ds, btn.dataset.view));
    });
  });
  return chart;
}

/** Compare shows Tempo's band with both medians; the pay-on-due band only shows on its own. */
function fanVisible(ds, view) {
  if (ds.role === "buffer") return true;
  const tempo = ds.label.startsWith("Tempo plan") || ds.role === "markers";
  if (view === "after") return tempo;
  if (view === "before") return !tempo;
  return tempo || ds.role === "median";
}

export async function render(main) {
  // The policy comparison is supplementary: if /api/evaluate fails the rest of Overview still renders.
  const [state, forecast, billsData, evaluate] = await Promise.all([
    loadState(),
    loadForecast(),
    loadBills(),
    loadEvaluate().catch(() => null),
  ]);
  const bills = billsData.bills;
  const rows = weekRows(state, bills);
  setHTML(
    main,
    html`<div class="flex flex-col gap-4">
      <div>
        <h1 class="text-xl">Overview</h1>
        <p class="text-sm text-ink-2">When and how to pay ${count(bills.length)} open bills, keeping cash above the ${money(state.company.buffer_cents)} buffer.</p>
      </div>
      ${kpiStrip(state)}
      <div class="grid grid-cols-12 gap-4">
        ${fanPanel(forecast)}
        ${riskPanel(state, evaluate, vendorsWithoutDiscount(bills))}
        ${weekPanel(state, rows)}
      </div>
    </div>`,
  );
  const chart = wireFan(main, forecast, state);
  wireApproval(main, state, rows);
  $$("[data-bill]", main).forEach((tr) => onActivate(tr, () => openBillPanel(tr.dataset.bill)));
  $("[data-negotiate]", main).addEventListener("click", () => openNegotiateDrawer());
  return () => chart.destroy();
}
