// Left sidebar: a status block (company, cash today, buffer, certified risk), grouped navigation with counts,
// this week's run, and a quiet footer (synthetic data, AI provider, build). Every number comes from responses the
// app already loads (/api/state, /api/bills, presets, /api/audit); a part whose response failed is left out.
import { html, icon, setHTML } from "./dom.js";
import { addDays, count, money, moneyExact, moneyShort, pct } from "./format.js";
import { riskMeter } from "./widgets.js";

const RUN_WINDOW_DAYS = 7; // same window as Overview's "This week's run"

const GROUPS = [
  { label: "Plan", items: ["overview", "run", "review"] },
  { label: "Analyze", items: ["whatif", "proof"] },
];

function badge(id, data) {
  if (id === "run" && data.state?.bill_count) {
    return html`<span class="nav-count num" aria-label="${data.state.bill_count} bills">${count(data.state.bill_count)}</span>`;
  }
  if (id === "review" && data.state?.review_count) {
    return html`<span class="nav-badge num" aria-label="${data.state.review_count} bills need review">${count(data.state.review_count)}</span>`;
  }
  if (id === "whatif" && data.presets?.presets?.length) {
    return html`<span class="nav-count num" aria-label="${data.presets.presets.length} precomputed scenarios">${count(data.presets.presets.length)}</span>`;
  }
  if (id === "proof" && data.state?.certification) {
    return data.state.certification.passed
      ? html`<span class="nav-count inline-flex items-center gap-1" title="Plan certified on seed B">${icon("shield-check", "icon h-3 w-3")}Certified</span>`
      : html`<span class="nav-count risk" title="Certification failed">Not certified</span>`;
  }
  return "";
}

function navLink(screen, activeId, data) {
  return html`<li><a class="nav-item" href="#/${screen.id}" ${screen.id === activeId ? html`aria-current="page"` : ""}>
    ${icon(screen.icon)}<span class="truncate">${screen.label}</span>${badge(screen.id, data)}
  </a></li>`;
}

function navGroups(screens, activeId, data) {
  const byId = Object.fromEntries(screens.map((s) => [s.id, s]));
  return html`${GROUPS.map(
    (g) => html`<div class="nav-group" role="group" aria-label="${g.label}">
      <p class="nav-group-label">${g.label}</p>
      <ul class="flex flex-col gap-0.5">${g.items.map((id) => navLink(byId[id], activeId, data))}</ul>
    </div>`,
  )}
  <div class="nav-group" role="group" aria-label="Agent">
    <p class="nav-group-label">Agent</p>
    <ul class="flex flex-col gap-0.5">
      <li><button type="button" class="nav-item w-full" data-open="negotiate">${icon("handshake")}<span>Negotiate terms</span></button></li>
      <li><button type="button" class="nav-item w-full" data-open="audit">${icon("scroll-text")}<span>Audit log</span>${data.audit?.entries?.length ? html`<span class="nav-count num" aria-label="${data.audit.entries.length} audit entries">${count(data.audit.entries.length)}</span>` : ""}</button></li>
    </ul>
  </div>`;
}

function statusBlock(state) {
  const k = state.kpis;
  const c = state.certification;
  return html`<section class="side-block side-block-top" aria-label="Company status">
    <p class="text-sm font-semibold leading-snug text-ink">${state.company.name}</p>
    <dl class="side-dl">
      <dt>Cash today</dt><dd class="num" title="${moneyExact(state.company.starting_cash_cents)}">${moneyShort(state.company.starting_cash_cents)}</dd>
      <dt>Buffer</dt><dd class="num" title="${moneyExact(state.company.buffer_cents)}">${moneyShort(state.company.buffer_cents)}</dd>
    </dl>
    <div class="flex items-baseline justify-between gap-2">
      <span class="text-xs text-ink-2">Chance below buffer</span>
      <span class="num text-sm font-semibold ${k.breach_upper > k.epsilon ? "risk" : "text-ink"}" title="One-sided 95% upper bound ${pct(k.breach_upper)}">${pct(k.breach_rate)}</span>
    </div>
    ${riskMeter({ rate: k.breach_rate, upper: k.breach_upper, target: k.epsilon })}
    ${c.passed
      ? html`<span class="chip self-start" title="Seed-B bound ${pct(c.steps.find((s) => s.passed)?.cert_upper)} at most the ${pct(c.epsilon, 0)} target">${icon("shield-check")}Certified</span>`
      : html`<span class="chip chip-risk self-start">${icon("x")}Not certified</span>`}
  </section>`;
}

function weekRows(state, bills) {
  const start = state.company.as_of;
  const end = addDays(start, RUN_WINDOW_DAYS - 1);
  return bills.filter((b) => b.send_date && b.send_date >= start && b.send_date <= end);
}

function weekBlock(state, bills, audit) {
  if (!bills) return "";
  const rows = weekRows(state, bills);
  const paid = rows.reduce((s, b) => s + b.cash_out_cents, 0);
  const value = rows.reduce((s, b) => s + b.value_cents, 0);
  const approved = Boolean(audit?.entries?.some((e) => e.plan_hash === state.plan_hash));
  return html`<a class="side-block side-link" href="#/overview?section=approve" aria-label="This week's run: ${rows.length} bills, open the approval">
    <span class="flex flex-col items-start gap-1">
      <span class="text-sm font-semibold text-ink">This week's run</span>
      <span class="chip ${approved ? "chip-solid" : ""}">${approved ? html`${icon("check")}Approved` : "Awaiting approval"}</span>
    </span>
    <dl class="side-dl">
      <dt>Bills</dt><dd class="num">${count(rows.length)}</dd>
      <dt>Paid out</dt><dd class="num" title="${moneyExact(paid)}">${money(paid)}</dd>
      <dt>Value</dt><dd class="num ${value > 0 ? "gain" : value < 0 ? "risk" : ""}" title="${moneyExact(value)}">${money(value, { signed: true })}</dd>
    </dl>
  </a>`;
}

function footer(state) {
  const build = state.build_commit;
  return html`<div class="side-footer">
    <p>Synthetic data</p>
    <p title="AI provider: ${state.provider.name}, model: ${state.provider.model}">AI: local model (${state.provider.label})</p>
    ${build ? html`<p>Build <span class="num">${build}</span></p>` : ""}
  </div>`;
}

/** Render the sidebar into #sidebar-body. Navigation always renders; data-backed blocks need their response. */
export function renderSidebar(screens, activeId, data) {
  const el = document.getElementById("sidebar-body");
  if (!el) return;
  setHTML(
    el,
    html`${data.state ? statusBlock(data.state) : ""}
      <div class="flex flex-col gap-2">${navGroups(screens, activeId, data)}</div>
      ${data.state ? weekBlock(data.state, data.bills?.bills, data.audit) : ""}
      ${data.state ? footer(data.state) : ""}`,
  );
}
