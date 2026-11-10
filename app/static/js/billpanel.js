// Side panel for one bill: the decision and why it won, every option's value, and the
// invoice text with highlighted evidence.
import { html, icon, setHTML } from "./dom.js";
import { longDate, money, moneyExact, perYear, sentence, shortDate, termsText } from "./format.js";
import { chip, OPTION_LABEL, RAIL_LABEL, STATUS_LABEL, valueCell } from "./labels.js";
import { documentView, evidenceLegend, methodsText } from "./evidence.js";
import { openDrawer } from "./drawer.js";
import { errorBlock, loadingBlock } from "./states.js";
import { loadBill } from "./store.js";
import { openNegotiateDrawer } from "./drawers.js";

function decisionSection(b) {
  const late = b.option === "LATE";
  return html`<section class="flex flex-col gap-3" aria-labelledby="bp-decision">
    <h3 id="bp-decision" class="section-title">Decision</h3>
    <div class="grid grid-cols-4 gap-px overflow-hidden rounded-md border border-line bg-line">
      ${[
        ["Pay", html`<span class="${late ? "risk font-medium" : ""}">${OPTION_LABEL[b.option] ?? b.option}</span>`],
        ["Send", html`<span class="num">${longDate(b.send_date)}</span>`],
        ["Cash leaves", html`<span class="num">${longDate(b.cash_out_date)}</span>`],
        ["Rail", RAIL_LABEL[b.rail] ?? b.rail],
        ["Cash out", html`<span class="num" title="${moneyExact(b.cash_out_cents)}">${money(b.cash_out_cents)}</span>`],
        ["Value vs due date", valueCell(b.value_cents)],
        ["Annualized return", html`<span class="num">${perYear(b.annualized_return)}</span>`],
        ["Due date", html`<span class="num">${longDate(b.due_date)}</span>`],
      ].map(([k, v]) => html`<div class="bg-surface px-3 py-2"><p class="label">${k}</p><p class="text-sm">${v}</p></div>`)}
    </div>
    <div class="callout ${late ? "callout-risk" : ""} items-start">
      ${icon("info", "icon mt-0.5 flex-none")}
      <div>
        <p class="font-medium text-ink">Why this option won</p>
        <p class="mt-0.5">${b.reason}</p>
        ${b.binding_day ? html`<p class="mt-1 text-xs">The cash limit binds: paying earlier would add a breach on ${longDate(b.binding_day)}.</p>` : ""}
      </div>
    </div>
  </section>`;
}

function optionRow(o, chosen) {
  const parts = [
    o.discount_cents ? `discount ${money(o.discount_cents)}` : "",
    o.rewards_cents ? `rewards ${money(o.rewards_cents)}` : "",
    o.yield_cents ? `yield ${money(o.yield_cents, { signed: true })}` : "",
    o.fee_cents ? `fee ${money(-o.fee_cents)}` : "",
    o.surcharge_cents ? `surcharge ${money(-o.surcharge_cents)}` : "",
  ].filter(Boolean);
  return html`<tr class="${chosen ? "is-selected font-medium" : ""}">
    <td>
      <div class="flex items-center gap-1.5">
        ${chosen ? html`${icon("circle-check", "icon text-ink")}<span class="sr-only">Chosen:</span>` : html`<span class="inline-block w-4"></span>`}
        <span class="whitespace-nowrap ${o.kind === "LATE" ? "risk" : ""}">${OPTION_LABEL[o.kind] ?? o.kind}</span>
      </div>
    </td>
    <td>${RAIL_LABEL[o.rail] ?? o.rail}</td>
    <td class="num">${shortDate(o.send_date)}</td>
    <td class="num">${shortDate(o.cash_out_date)}</td>
    <td class="r num" title="${moneyExact(o.cash_out_cents)}">${money(o.cash_out_cents)}</td>
    <td class="text-xs text-ink-2">${parts.join(", ") || "none"}</td>
    <td class="r">${valueCell(o.value_cents)}</td>
  </tr>`;
}

function optionsSection(b) {
  return html`<section class="flex flex-col gap-2" aria-labelledby="bp-options">
    <h3 id="bp-options" class="section-title">Every option Tempo considered</h3>
    <div class="overflow-hidden rounded-md border border-line">
      <table class="tbl">
        <thead><tr>
          <th scope="col">Option</th><th scope="col">Rail</th><th scope="col">Send</th><th scope="col">Cash leaves</th>
          <th scope="col" class="r">Cash out</th><th scope="col">Made of</th><th scope="col" class="r">Value</th>
        </tr></thead>
        <tbody>${b.options.map((o, i) => optionRow(o, i === b.chosen_index))}</tbody>
      </table>
    </div>
    <p class="text-xs text-ink-3">Value is measured against paying by bank on the due date. Tempo picks the mix of options across all bills that earns the most while keeping the chance of a buffer breach under the target.</p>
  </section>`;
}

function evidenceSection(b) {
  const r = b.reconciliation;
  return html`<section class="flex flex-col gap-2" aria-labelledby="bp-evidence">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 id="bp-evidence" class="section-title">Invoice and evidence</h3>
      ${evidenceLegend()}
    </div>
    <dl class="dl">
      <dt>Terms used</dt><dd><span class="font-medium">${r.accepted ? termsText(r.accepted) : b.terms}</span> ${chip(b.chip)}</dd>
      <dt>Reconciliation</dt><dd>${STATUS_LABEL[r.status] ?? sentence(r.status)}${r.reason && r.reason.toLowerCase() !== (STATUS_LABEL[r.status] ?? "").toLowerCase() ? html`<span class="text-ink-2">. ${sentence(r.reason)}.</span>` : ""}</dd>
      ${r.card_surcharge_bps ? html`<dt>Card surcharge</dt><dd class="num">${(r.card_surcharge_bps / 100).toFixed(2)}%</dd>` : ""}
      <dt>Accepts</dt><dd>${methodsText(r.accepted_methods)}</dd>
    </dl>
    ${documentView(b.document, b.evidence, r.authoritative_source)}
  </section>`;
}

function vendorSection(b) {
  const hasDiscount = b.terms.includes("/");
  if (hasDiscount) return "";
  return html`<section class="flex items-center justify-between gap-3 rounded-md border border-line px-4 py-3">
    <p class="text-sm text-ink-2">${b.vendor} offers no early-payment discount on this bill.</p>
    <button type="button" class="btn btn-sm" data-negotiate="${b.vendor_id}">${icon("handshake")}Negotiate with vendor</button>
  </section>`;
}

export async function openBillPanel(billId) {
  const body = openDrawer({ id: "bill", title: "Bill", wide: true });
  const drawer = body.closest(".drawer");
  setHTML(body, loadingBlock("Loading bill", 8));
  try {
    const b = await loadBill(billId);
    setHTML(drawer.querySelector("#drawer-title"), html`${b.vendor} <span class="font-normal text-ink-2">${b.invoice_number}</span>`);
    setHTML(
      body,
      html`<div class="flex flex-col gap-6">
        <p class="text-sm text-ink-2"><span class="num text-lg font-semibold text-ink" title="${moneyExact(b.amount_cents)}">${money(b.amount_cents)}</span>
          issued ${longDate(b.issued_at)}, terms ${b.terms}</p>
        ${decisionSection(b)}
        ${optionsSection(b)}
        ${vendorSection(b)}
        ${evidenceSection(b)}
      </div>`,
    );
    body.querySelector("[data-negotiate]")?.addEventListener("click", (e) =>
      openNegotiateDrawer({ vendorId: e.currentTarget.dataset.negotiate, vendor: b.vendor }),
    );
  } catch (err) {
    setHTML(body, errorBlock(err, "this bill"));
    body.querySelector("[data-retry]")?.addEventListener("click", () => openBillPanel(billId));
  }
}
