// Negotiate drawer: vendors without discount terms ranked by verified dollar opportunity,
// the drafted offer (numbers filled by code, never by the model), a simulated vendor reply
// parsed back into terms, and a human Accept. Nothing is ever sent.
import { html, icon, raw, esc, setHTML } from "./dom.js";
import { count, longDate, money, moneyExact, pct, perYear, sentence, termsText } from "./format.js";
import { STATUS_LABEL } from "./labels.js";
import { openDrawer } from "./drawer.js";
import { emptyBlock, errorBlock, loadingBlock } from "./states.js";
import * as api from "./api.js";

const REPLY_KINDS = [
  ["accept", "Vendor accepts"],
  ["counter", "Vendor counters"],
  ["decline", "Vendor declines"],
  ["ambiguous", "Unclear reply"],
];
const READ_OK = new Set(["verified", "regex_only", "model_verified"]);
const ANCHORS = new Set(["invoice_date", "eom", "prox", "receipt"]);
const NUMBER_TOKEN = /[A-Z]{2,}-\d+|\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?%|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:, \d{4})?|\b\d[\d,]*(?:\.\d+)?\b/g;

const offerPct = (o) => pct(o.offer_bps / 10_000);

/** Escape the email text and mark every number: the number guard guarantees code filled each one. */
function markVerified(text) {
  const escaped = esc(text);
  return raw(escaped.replace(NUMBER_TOKEN, (m) => `<span class="verified-num" title="Filled in by Tempo's code from the computed offer">${m}</span>`));
}

function rankedTable(offers, negotiated) {
  return html`<div class="overflow-hidden rounded-md border border-line">
    <table class="tbl">
      <caption class="sr-only">Offers Tempo would take, ranked by value to the plan</caption>
      <thead><tr><th scope="col">Vendor</th><th scope="col" class="r">Bill</th><th scope="col" class="r">Offer</th><th scope="col" class="r">If accepted</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead>
      <tbody>${offers.map(
        (o) => html`<tr>
          <td><div class="font-medium">${o.vendor_name}</div><div class="meta">${o.invoice_number}, pay ${longDate(o.proposed_date)} (${count(o.days_early)} days early)</div></td>
          <td class="r num" title="${moneyExact(o.amount_cents)}">${money(o.amount_cents)}</td>
          <td class="r num">${offerPct(o)}</td>
          <td class="r num gain" title="${moneyExact(o.value_delta_cents)}">${money(o.value_delta_cents, { signed: true })}</td>
          <td class="r">${negotiated[o.vendor_id]
            ? html`<span class="chip chip-solid">${icon("user-check")}Terms saved</span>`
            : html`<button type="button" class="btn btn-sm" data-vendor="${o.vendor_id}" data-name="${o.vendor_name}">Draft offer</button>`}</td>
        </tr>`,
      )}</tbody>
    </table>
  </div>`;
}

function declinedList(offers) {
  if (!offers.length) return "";
  return html`<details class="rounded-md border border-line">
    <summary class="px-4 py-2.5 text-sm font-medium">Tempo would not take these (${offers.length})</summary>
    <ul class="flex flex-col border-t border-line">${offers.map(
      (o) => html`<li class="border-b border-line px-4 py-2.5 text-sm last:border-b-0">
        <span class="font-medium">${o.vendor_name}</span> <span class="text-ink-3">${o.invoice_number}, offer ${offerPct(o)}</span>
        <p class="text-ink-2">${o.verdict}</p>
      </li>`,
    )}</ul>
  </details>`;
}

function listView(data) {
  const offers = data.offers ?? [];
  if (!offers.length) {
    return emptyBlock("No offers yet", "Tempo prices an early-payment offer for each vendor without discount terms when the plan is precomputed. None are in this build.");
  }
  const ranked = offers.filter((o) => o.tempo_takes_it).sort((a, b) => b.value_delta_cents - a.value_delta_cents);
  const rest = offers.filter((o) => !o.tempo_takes_it);
  return html`<div class="flex flex-col gap-4">
    <p class="text-sm text-ink-2">Vendors without discount terms, ranked by what an accepted offer adds to the plan. Each offer is priced from your
      <span class="num font-medium text-ink">${perYear(data.cost_of_cash, 2)}</span> cost of cash, then re-solved to confirm Tempo would take it.</p>
    ${ranked.length ? rankedTable(ranked, data.negotiated ?? {}) : html`<p class="callout">Tempo would not take any of the priced offers.</p>`}
    ${declinedList(rest)}
  </div>`;
}

function offerFacts(o) {
  const fact = (label, value, title = "") => html`<div class="bg-surface px-3 py-2"><p class="label">${label}</p><p class="num text-sm font-medium" title="${title}">${value}</p></div>`;
  return html`<div class="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line bg-line">
    ${fact("Break-even discount", pct(o.break_even, 3), "The discount at which paying early exactly matches your cost of cash")}
    ${fact("Offer", offerPct(o))}
    ${fact("Savings on this bill", money(o.savings_cents), moneyExact(o.savings_cents))}
    ${fact("Pay on", `${longDate(o.proposed_date)}`, `${count(o.days_early)} days before ${longDate(o.due_date)}`)}
    ${fact("Annualized return", perYear(o.annualized_return))}
    ${fact("Cost of cash", perYear(o.cost_of_cash, 2))}
  </div>
  <p class="callout ${o.tempo_takes_it ? "" : "callout-review"}">${icon(o.tempo_takes_it ? "circle-check" : "circle-alert", "icon mt-0.5 flex-none")}
    <span title="Plan value change if accepted: ${moneyExact(o.value_delta_cents)}">${o.verdict}</span></p>`;
}

function emailView(email) {
  return html`<div class="rounded-md border border-line">
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
      <p class="text-sm font-medium">${email.subject}</p>
      <span class="chip chip-solid">${icon("lock")}Never sent</span>
    </div>
    <div class="doc px-4 py-3">${markVerified(email.body)}</div>
    <div class="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-xs text-ink-3">
      <span>Wording: ${email.used_fallback ? "deterministic template (the model draft was rejected)" : email.source}</span>
      <span><span class="verified-num">Dotted</span> numbers were filled in by code, not written by the model.</span>
    </div>
    ${email.problems?.length ? html`<ul class="border-t border-line px-4 py-2 text-xs text-review">${email.problems.map((p) => html`<li>${p}</li>`)}</ul>` : ""}
  </div>`;
}

function toTermsInput(t) {
  return {
    discount_pct: t.discount_bps ? t.discount_bps / 100 : null,
    discount_days: t.discount_bps ? t.discount_days : null,
    net_days: t.net_days ?? null,
    anchor: ANCHORS.has(t.anchor) ? t.anchor : "invoice_date",
    prox_day: t.anchor === "prox" ? t.prox_day : null,
  };
}

function replyView(reply) {
  const ok = reply.terms && READ_OK.has(reply.status);
  return html`<div class="flex flex-col gap-3">
    <div class="rounded-md border border-line">
      <p class="border-b border-line px-4 py-2 text-xs text-ink-2">Simulated reply (${reply.kind})</p>
      <div class="doc px-4 py-3">${reply.text}</div>
    </div>
    <dl class="dl">
      <dt>Read as</dt><dd class="font-medium">${reply.terms ? termsText(reply.terms) : "No terms"}</dd>
      <dt>Status</dt><dd>${ok ? html`<span class="chip chip-solid">${icon("badge-check")}${STATUS_LABEL[reply.status] ?? reply.status}</span>` : html`<span class="chip chip-review">${icon("circle-alert")}${STATUS_LABEL[reply.status] ?? reply.status}</span>`}</dd>
      <dt>Why</dt><dd class="text-ink-2">${sentence(reply.reason)}</dd>
      <dt>Model check</dt><dd class="text-ink-2">${reply.model_check}</dd>
    </dl>
    ${reply.terms
      ? html`<div class="flex items-center gap-3"><button type="button" class="btn btn-primary" data-accept-terms>${icon("check")}Accept these terms</button>
          <span class="text-xs text-ink-2">Terms are saved only when a person accepts them.</span></div>`
      : ""}
    <p data-accept-result></p>
  </div>`;
}

async function runReply(el, vendorId, kind) {
  setHTML(el, loadingBlock("Reading the reply", 3));
  try {
    const reply = await api.simulateReply(vendorId, kind);
    setHTML(el, replyView(reply));
    el.querySelector("[data-accept-terms]")?.addEventListener("click", (e) => acceptTerms(e.currentTarget, el, vendorId, reply.terms));
  } catch (err) {
    setHTML(el, errorBlock(err, "the reply"));
    el.querySelector("[data-retry]")?.addEventListener("click", () => runReply(el, vendorId, kind));
  }
}

async function acceptTerms(button, el, vendorId, terms) {
  const out = el.querySelector("[data-accept-result]");
  button.disabled = true;
  try {
    await api.acceptNegotiated(vendorId, toTermsInput(terms));
    setHTML(button, html`${icon("user-check")}Accepted`);
    setHTML(out, html`<span class="callout">${icon("circle-check", "icon mt-0.5")}Saved ${termsText(terms)} as this vendor's negotiated terms.</span>`);
  } catch (err) {
    button.disabled = false;
    setHTML(out, html`<span class="text-sm risk" role="alert">${err.message}</span>`);
  }
}

function vendorView(draft) {
  return html`<div class="flex flex-col gap-5">
    <section class="flex flex-col gap-3"><h3 class="section-title">Offer for ${draft.offer.invoice_number}</h3>${offerFacts(draft.offer)}</section>
    <section class="flex flex-col gap-2"><h3 class="section-title">Email draft</h3>${emailView(draft.email)}</section>
    <section class="flex flex-col gap-3">
      <h3 class="section-title">Simulate the vendor's reply</h3>
      <div class="flex flex-wrap gap-1.5">${REPLY_KINDS.map(([k, label]) => html`<button type="button" class="btn btn-sm" data-reply="${k}">${label}</button>`)}</div>
      <div data-reply-out></div>
    </section>
  </div>`;
}

async function showVendor(body, vendorId, vendorName) {
  setHTML(body, loadingBlock(`Drafting an offer for ${vendorName}`, 6));
  try {
    const draft = await api.draftOffer(vendorId);
    setHTML(body, vendorView(draft));
    const out = body.querySelector("[data-reply-out]");
    body.querySelectorAll("[data-reply]").forEach((btn) => btn.addEventListener("click", () => runReply(out, vendorId, btn.dataset.reply)));
  } catch (err) {
    if (err.status === 404) {
      setHTML(body, emptyBlock(`No offer for ${vendorName}`, "Tempo prices offers only for vendors without discount terms whose bills leave room to pay early. This vendor has none in this build."));
      return;
    }
    setHTML(body, errorBlock(err, "the offer"));
    body.querySelector("[data-retry]")?.addEventListener("click", () => showVendor(body, vendorId, vendorName));
  }
}

async function showList(body) {
  setHTML(body, loadingBlock("Loading offers", 6));
  try {
    setHTML(body, listView(await api.getOffers()));
    body.querySelectorAll("[data-vendor]").forEach((btn) =>
      btn.addEventListener("click", () => {
        setHTML(body.closest(".drawer").querySelector("#drawer-title"), html`Negotiate with ${btn.dataset.name}`);
        showVendor(body, btn.dataset.vendor, btn.dataset.name);
      }),
    );
  } catch (err) {
    setHTML(body, errorBlock(err, "offers"));
    body.querySelector("[data-retry]")?.addEventListener("click", () => showList(body));
  }
}

export function openNegotiateDrawer({ vendorId = null, vendor = null } = {}) {
  const body = openDrawer({
    id: "negotiate",
    title: vendor ? `Negotiate with ${vendor}` : "Negotiate discount terms",
    subtitle: "Drafts only. Tempo never sends email.",
  });
  if (vendorId) showVendor(body, vendorId, vendor);
  else showList(body);
}
