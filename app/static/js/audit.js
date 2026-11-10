// Audit drawer: hash-chain status, approval entries, and the Ramp payload preview
// (filterable, downloadable as JSON). Tempo never calls Ramp's API.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, money, moneyExact, pct } from "./format.js";
import { OPTION_SHORT } from "./labels.js";
import { openDrawer } from "./drawer.js";
import { errorBlock, loadingBlock } from "./states.js";
import * as api from "./api.js";

const PAYLOAD_FILTERS = [
  ["all", "All bills"],
  ["requests", "With API requests"],
  ["hold", "Holds"],
  ["auto", "Auto-scheduled"],
  ["none", "No API lever"],
];
const HASH_SHORT = 12;

const short = (hash) => (hash ? hash.slice(0, HASH_SHORT) : "—");

function timestamp(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function chainStatus(chain) {
  if (chain.ok) {
    return html`<div class="flex items-center gap-3 rounded-md border border-line-strong px-4 py-3">
      ${icon("shield-check", "icon h-5 w-5")}
      <div><p class="font-semibold">Verified chain</p>
        <p class="text-xs text-ink-2"><span class="num">${count(chain.entries)}</span> ${chain.entries === 1 ? "entry" : "entries"}; every hash recomputes and links to the one before. Head <span title="${chain.head}">${short(chain.head)}</span></p></div>
    </div>`;
  }
  return html`<div class="callout callout-risk items-center" role="alert">
    ${icon("triangle-alert", "icon h-5 w-5")}
    <div><p class="font-semibold">Broken at entry ${chain.first_bad}</p><p class="text-xs">An entry was changed after it was written. Entries from there on cannot be trusted.</p></div>
  </div>`;
}

function autonomyText(a) {
  return a?.mode === "auto" ? html`Auto under <span class="num">${money(a.threshold_cents)}</span>` : "Suggest only";
}

function entriesTable(entries, highlightHash) {
  if (!entries.length) return html`<p class="rounded-md border border-dashed border-line-strong px-4 py-5 text-center text-sm text-ink-2">No approvals yet. Approving this week's run writes the first entry.</p>`;
  const rows = [...entries].reverse();
  return html`<div class="overflow-hidden rounded-md border border-line"><table class="tbl">
    <caption class="sr-only">Approval entries, newest first</caption>
    <thead><tr><th scope="col">When</th><th scope="col">Approver</th><th scope="col">Autonomy</th><th scope="col">Plan</th><th scope="col">Hash</th><th scope="col">Previous</th></tr></thead>
    <tbody>${rows.map(
      (e) => html`<tr class="${e.hash === highlightHash ? "is-selected" : ""}">
        <td class="num whitespace-nowrap">${timestamp(e.timestamp)}</td>
        <td>${e.approver}</td>
        <td class="whitespace-nowrap">${autonomyText(e.autonomy)}</td>
        <td title="${e.plan_hash}">${short(e.plan_hash)}</td>
        <td title="${e.hash}" class="font-medium">${short(e.hash)}</td>
        <td title="${e.prev_hash}" class="text-ink-3">${short(e.prev_hash)}</td>
      </tr>`,
    )}</tbody>
  </table></div>`;
}

function newEntryNotice(entry) {
  const m = entry.metrics ?? {};
  return html`<div class="callout items-start" role="status">${icon("circle-check", "icon mt-0.5 flex-none text-ink")}
    <p><span class="font-medium text-ink">Approved by ${entry.approver}.</span> Entry ${short(entry.hash)} records plan ${short(entry.plan_hash)}
    (value <span class="num">${money(m.value_vs_pay_on_due_cents, { signed: true })}</span>, breach <span class="num">${pct(m.breach_rate)}</span>, bound <span class="num">${pct(m.breach_upper)}</span>). Nothing was sent to Ramp.</p></div>`;
}

function requestView(r) {
  const body = r.body ? JSON.stringify(r.body) : "";
  return html`<div class="text-xs"><span class="font-semibold">${r.method}</span> <span class="break-all">${r.path}</span>${body ? html`<div class="break-all text-ink-2">${body}</div>` : ""}</div>`;
}

function matches(b, filter, query) {
  const q = query.trim().toLowerCase();
  if (q && !b.vendor.toLowerCase().includes(q) && !b.invoice_number.toLowerCase().includes(q)) return false;
  if (filter === "requests") return b.requests.length > 0;
  if (filter === "hold") return b.requests.some((r) => r.path.endsWith("/hold"));
  if (filter === "auto") return b.auto_scheduled;
  if (filter === "none") return b.requests.length === 0;
  return true;
}

function payloadRows(bills) {
  if (!bills.length) return html`<p class="px-4 py-5 text-center text-sm text-ink-2">No bills match.</p>`;
  return html`<ul>${bills.map(
    (b) => html`<li class="flex flex-col gap-1 border-b border-line px-4 py-2.5 last:border-b-0">
      <div class="flex items-center justify-between gap-3 text-sm">
        <span><span class="font-medium">${b.vendor}</span> <span class="text-ink-3">${b.invoice_number}</span></span>
        <span class="flex items-center gap-2">${b.auto_scheduled ? html`<span class="chip chip-solid">Auto-scheduled</span>` : ""}
          <span class="text-xs text-ink-2">${OPTION_SHORT[b.option] ?? b.option}</span>
          <span class="num" title="${moneyExact(b.amount_cents)}">${money(b.amount_cents)}</span></span>
      </div>
      ${b.requests.map(requestView)}
      ${b.notes.map((n) => html`<p class="text-xs text-ink-3">${n}</p>`)}
    </li>`,
  )}</ul>`;
}

function payloadView(p) {
  const c = p.counts;
  const stat = (label, value) => html`<div class="bg-surface px-3 py-2"><p class="label">${label}</p><p class="num font-semibold">${count(value)}</p></div>`;
  return html`<div class="flex flex-col gap-3">
    <p class="callout">${icon("lock", "icon mt-0.5 flex-none")}${p.note}</p>
    <div class="grid grid-cols-6 gap-px overflow-hidden rounded-md border border-line bg-line max-[700px]:grid-cols-3">
      ${stat("Bills", c.bills)}${stat("Requests", c.requests)}${stat("PATCH", c.patch)}${stat("Hold", c.hold)}${stat("Release", c.release)}${stat("Auto-scheduled", c.auto_scheduled)}
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex flex-wrap gap-1.5" role="group" aria-label="Filter the payload">${PAYLOAD_FILTERS.map(
        ([id, label], i) => html`<button type="button" class="filter" data-pfilter="${id}" aria-pressed="${i === 0}">${label}</button>`,
      )}</div>
      <input type="search" class="field ml-auto w-48" placeholder="Search vendor" aria-label="Search the payload by vendor or invoice" data-psearch>
    </div>
    <p class="text-xs text-ink-2" data-pcount aria-live="polite"></p>
    <div class="max-h-[420px] overflow-y-auto rounded-md border border-line" data-plist></div>
    <div><button type="button" class="btn" data-download>${icon("download")}Download JSON</button></div>
  </div>`;
}

function downloadJson(data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `tempo-payment-run-${data.plan_hash.slice(0, 8)}.json` });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function wirePayload(el, p) {
  const view = { filter: "all", query: "" };
  const paint = () => {
    const rows = p.bills.filter((b) => matches(b, view.filter, view.query));
    $("[data-pcount]", el).textContent = `Showing ${rows.length} of ${p.bills.length} bills`;
    setHTML($("[data-plist]", el), payloadRows(rows));
  };
  $$("[data-pfilter]", el).forEach((btn) =>
    btn.addEventListener("click", () => {
      view.filter = btn.dataset.pfilter;
      $$("[data-pfilter]", el).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      paint();
    }),
  );
  $("[data-psearch]", el).addEventListener("input", (e) => {
    view.query = e.target.value;
    paint();
  });
  $("[data-download]", el).addEventListener("click", () => downloadJson(p));
  paint();
}

async function fill(el, loader, onData, what) {
  setHTML(el, loadingBlock(`Loading ${what}`, 3));
  try {
    onData(await loader());
  } catch (err) {
    setHTML(el, errorBlock(err, what));
    el.querySelector("[data-retry]")?.addEventListener("click", () => fill(el, loader, onData, what));
  }
}

/** Open the drawer; pass {entry} right after an approval to show and highlight it. */
export function openAuditDrawer({ entry = null } = {}) {
  const body = openDrawer({ id: "audit", title: "Audit log", subtitle: "Append-only and hash-chained. Each approval records who, when, the plan, and its inputs.", wide: true });
  setHTML(
    body,
    html`<div class="flex flex-col gap-5">
      ${entry ? newEntryNotice(entry) : ""}
      <section class="flex flex-col gap-2" aria-labelledby="audit-chain"><h3 id="audit-chain" class="section-title">Chain</h3><div data-audit></div></section>
      <section class="flex flex-col gap-2" aria-labelledby="audit-payload"><h3 id="audit-payload" class="section-title">Ramp payload preview</h3><div data-payload></div></section>
    </div>`,
  );
  const auditEl = $("[data-audit]", body);
  const payloadEl = $("[data-payload]", body);
  fill(auditEl, api.getAudit, (a) => setHTML(auditEl, html`<div class="flex flex-col gap-3">${chainStatus(a.chain)}${entriesTable(a.entries, entry?.hash)}</div>`), "the audit log");
  fill(payloadEl, api.getPayloadPreview, (p) => {
    setHTML(payloadEl, payloadView(p));
    wirePayload(payloadEl, p);
  }, "the payload preview");
}
