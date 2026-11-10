// Payment run: every bill with its decision. Sortable columns, combinable filters, row -> side panel.
import { $, $$, html, icon, onActivate, setHTML } from "./dom.js";
import { count, money, moneyExact, perYear, shortDate } from "./format.js";
import { arrivesLateChip, chip, expectedChip, optionCell, railCell, railIcon, valueCell } from "./labels.js";
import { openBillPanel } from "./billpanel.js";
import { emptyBlock } from "./states.js";
import { loadBills, loadState } from "./store.js";

const FILTERS = [
  { id: "discount", label: "Discount taken", test: (b) => b.takes_discount },
  { id: "card", label: "Card", test: (b) => b.is_card },
  { id: "review", label: "Needs review", test: (b) => b.needs_review && b.chip !== "Accepted by reviewer" },
  { id: "binding", label: "Held back by cash limit", test: (b) => Boolean(b.binding_day) },
  { id: "arrives_late", label: "Arrives after due date", test: (b) => Boolean(b.arrives_after_due) },
  { id: "late", label: "Late by choice", test: (b) => b.is_late },
];

const COLUMNS = [
  { id: "vendor", label: "Vendor", key: (b) => b.vendor.toLowerCase() },
  { id: "amount", label: "Amount", key: (b) => b.amount_cents, right: true },
  { id: "terms", label: "Terms", key: (b) => b.terms.toLowerCase() },
  { id: "option", label: "Decision", key: (b) => b.option },
  { id: "cash_out", label: "Cash leaves", key: (b) => b.cash_out_date },
  { id: "rail", label: "Rail", key: (b) => b.rail, narrowHide: true },
  { id: "value", label: "Value", key: (b) => b.value_cents, right: true },
  { id: "return", label: "Return", key: (b) => b.annualized_return ?? -1, right: true, narrowHide: true },
  { id: "reason", label: "Why", key: (b) => b.reason, sortable: false, narrowHide: true },
];

const DESC_FIRST = new Set(["amount", "value", "return"]);
const DEFAULT_SORT = "value"; // biggest wins first

function initialView(params) {
  const sortId = COLUMNS.some((c) => c.id === params.sort) ? params.sort : DEFAULT_SORT;
  return {
    filters: new Set(FILTERS.some((f) => f.id === params.filter) ? [params.filter] : []),
    sort: { id: sortId, dir: DESC_FIRST.has(sortId) ? "desc" : "asc" },
    query: "",
    from: params.from ?? null,
    to: params.to ?? null,
  };
}

function visibleRows(bills, view) {
  const q = view.query.trim().toLowerCase();
  const col = COLUMNS.find((c) => c.id === view.sort.id);
  const dir = view.sort.dir === "asc" ? 1 : -1;
  return bills
    .filter((b) => [...view.filters].every((id) => FILTERS.find((f) => f.id === id).test(b)))
    .filter((b) => !view.from || b.cash_out_date >= view.from)
    .filter((b) => !view.to || b.cash_out_date <= view.to)
    .filter((b) => !q || b.vendor.toLowerCase().includes(q) || b.invoice_number.toLowerCase().includes(q))
    .sort((a, b) => {
      const [ka, kb] = [col.key(a), col.key(b)];
      return (ka < kb ? -1 : ka > kb ? 1 : 0) * dir || a.cash_out_date.localeCompare(b.cash_out_date);
    });
}

function headerCell(col, sort) {
  const narrow = col.narrowHide ? "max-[1200px]:hidden" : "";
  if (col.sortable === false) return html`<th scope="col" class="${narrow}">${col.label}</th>`;
  const active = sort.id === col.id;
  const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
  const glyph = active ? (sort.dir === "asc" ? "chevron-up" : "chevron-down") : "chevrons-up-down";
  return html`<th scope="col" class="${col.right ? "r" : ""} ${narrow}" aria-sort="${ariaSort}">
    <button type="button" class="sort-btn" data-sort="${col.id}">${col.label}${icon(glyph)}</button>
  </th>`;
}

const returnText = (b) => (b.annualized_return === null || b.annualized_return === undefined ? "\u2014" : perYear(b.annualized_return));

/** Under 1200px the Rail, Return, and Why columns fold into the Decision and Value cells. */
function decisionCell(b) {
  return html`<td>
    <div class="flex flex-wrap items-center gap-1.5"><span class="whitespace-nowrap">${optionCell(b)}</span><span class="min-[1201px]:hidden">${railIcon(b.rail)}</span>${arrivesLateChip(b)}</div>
    <p class="max-w-[180px] truncate text-xs text-ink-2 min-[1201px]:hidden" title="${b.reason}">${b.reason}</p>
  </td>`;
}

function row(b) {
  return html`<tr class="clickable" tabindex="0" data-bill="${b.bill_id}" aria-label="${b.vendor} ${b.invoice_number}, open details">
    <td class="max-w-[220px] max-[1200px]:max-w-[150px]"><div class="truncate font-medium" title="${b.vendor}">${b.vendor}</div>
      <div class="meta flex flex-wrap items-center gap-1.5">${b.invoice_number}${expectedChip(b)}</div></td>
    <td class="r num" title="${moneyExact(b.amount_cents)}">${money(b.amount_cents)}</td>
    <td><div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 min-[1201px]:flex-nowrap"><span class="whitespace-nowrap">${b.terms}</span>${chip(b.chip)}</div></td>
    ${decisionCell(b)}
    <td class="num" title="Send ${shortDate(b.send_date)}">${shortDate(b.cash_out_date)}</td>
    <td class="max-[1200px]:hidden">${railCell(b.rail)}</td>
    <td class="r">${valueCell(b.value_cents)}<div class="meta num min-[1201px]:hidden">${b.annualized_return === null ? "" : returnText(b)}</div></td>
    <td class="r num text-ink-2 max-[1200px]:hidden">${returnText(b)}</td>
    <td class="max-[1200px]:hidden"><p class="max-w-[180px] truncate text-ink-2" title="${b.reason}">${b.reason}</p></td>
  </tr>`;
}

function tableView(rows, view) {
  if (!rows.length) return emptyBlock("No bills match these filters", "Turn off a filter or clear the search to see more bills.");
  return html`<table class="tbl">
    <caption class="sr-only">Every open bill and Tempo's decision. Select a row for details.</caption>
    <thead><tr>${COLUMNS.map((c) => headerCell(c, view.sort))}</tr></thead>
    <tbody>${rows.map(row)}</tbody>
  </table>`;
}

/** Filter counts; Needs review uses /api/state review_count so the badge, filter, and subhead agree. */
function toolbar(bills, view, reviewCount) {
  const range = view.from || view.to;
  return html`<div class="flex flex-wrap items-center gap-2">
    <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filters (combine)">
      ${FILTERS.map((f) => {
        const n = f.id === "review" ? reviewCount : bills.filter(f.test).length;
        return html`<button type="button" class="filter" data-filter="${f.id}" aria-pressed="${view.filters.has(f.id)}">${f.label}<span class="count num">${count(n)}</span></button>`;
      })}
      ${range
        ? html`<button type="button" class="filter" aria-pressed="true" data-clear-range title="Remove date filter">
            Cash leaves ${view.from ? shortDate(view.from) : "start"} to ${view.to ? shortDate(view.to) : "end"}${icon("x", "icon h-3 w-3")}</button>`
        : ""}
    </div>
    <label class="ml-auto flex items-center gap-2">
      <span class="sr-only">Search vendor or invoice</span>
      <input type="search" class="field w-60" placeholder="Search vendor or invoice" value="${view.query}" data-search>
    </label>
  </div>`;
}

function summary(rows, total) {
  const amount = rows.reduce((s, b) => s + b.cash_out_cents, 0);
  const value = rows.reduce((s, b) => s + b.value_cents, 0);
  return html`<p class="text-sm text-ink-2" aria-live="polite">
    Showing <span class="num font-medium text-ink">${count(rows.length)}</span> of <span class="num">${count(total)}</span> bills,
    <span class="num font-medium text-ink" title="${moneyExact(amount)}">${money(amount)}</span> paid out,
    value <span class="num font-medium ${value > 0 ? "gain" : value < 0 ? "risk" : "text-ink"}" title="${moneyExact(value)}">${money(value, { signed: true })}</span>
  </p>`;
}

function nextSort(sort, id) {
  if (sort.id === id) return { id, dir: sort.dir === "asc" ? "desc" : "asc" };
  return { id, dir: DESC_FIRST.has(id) ? "desc" : "asc" };
}

/** Render rows for ctx.view; every interaction replaces ctx.view with a new object and repaints. */
function paint(root, bills, ctx) {
  const rows = visibleRows(bills, ctx.view);
  setHTML($("[data-summary]", root), summary(rows, bills.length));
  setHTML($("[data-table]", root), tableView(rows, ctx.view));
  $$("[data-filter]", root).forEach((b) => b.setAttribute("aria-pressed", String(ctx.view.filters.has(b.dataset.filter))));
  $$("[data-sort]", root).forEach((b) =>
    b.addEventListener("click", () => {
      const id = b.dataset.sort;
      ctx.view = { ...ctx.view, sort: nextSort(ctx.view.sort, id) };
      paint(root, bills, ctx);
      $(`[data-sort="${id}"]`, root)?.focus();
    }),
  );
  $$("[data-bill]", root).forEach((tr) =>
    onActivate(tr, () => {
      $$("tr.is-selected", root).forEach((r) => r.classList.remove("is-selected"));
      tr.classList.add("is-selected");
      openBillPanel(tr.dataset.bill);
    }),
  );
}

function toggled(set, id) {
  return new Set(set.has(id) ? [...set].filter((f) => f !== id) : [...set, id]);
}

export async function render(main, params) {
  const [{ bills }, state] = await Promise.all([loadBills(), loadState()]);
  const ctx = { view: initialView(params) };
  const view = ctx.view;
  setHTML(
    main,
    html`<div class="flex flex-col gap-4">
      <div>
        <h1 class="text-xl">Payment run</h1>
        <p class="text-sm text-ink-2">Every open bill, the day and rail Tempo chose, and why. Select a row to see the invoice and every option.</p>
      </div>
      <div data-toolbar>${toolbar(bills, view, state.review_count)}</div>
      <div data-summary></div>
      <section class="panel overflow-clip max-[1200px]:overflow-x-auto" data-table></section>
    </div>`,
  );
  const root = main;
  $$("[data-filter]", root).forEach((btn) =>
    btn.addEventListener("click", () => {
      ctx.view = { ...ctx.view, filters: toggled(ctx.view.filters, btn.dataset.filter) };
      paint(root, bills, ctx);
    }),
  );
  $("[data-clear-range]", root)?.addEventListener("click", (e) => {
    ctx.view = { ...ctx.view, from: null, to: null };
    e.currentTarget.remove();
    paint(root, bills, ctx);
  });
  $("[data-search]", root).addEventListener("input", (e) => {
    ctx.view = { ...ctx.view, query: e.target.value };
    paint(root, bills, ctx);
  });
  paint(root, bills, ctx);
  return null;
}
