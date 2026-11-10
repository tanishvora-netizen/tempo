// Needs review: parser vs model side by side with the quoted evidence, the reconciliation
// reason, suggested terms, and Accept or Edit. After a change the plan is re-solved and the
// effect (value change and flipped decisions) is shown.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { longDate, money, moneyExact, sentence, termsText } from "./format.js";
import { EXPECTED_NOTE, modelCheckText, STATUS_LABEL, valueCell } from "./labels.js";
import { documentView, evidenceLegend, highlight, sourceLabel } from "./evidence.js";
import { emptyBlock, errorBlock } from "./states.js";
import { invalidate, loadReview, loadState, STATE_CHANGED } from "./store.js";
import { uploadControl, wireUpload } from "./upload.js";
import { diffTable } from "./widgets.js";
import { reviewForm, readTerms, wireAnchorField } from "./reviewform.js";
import * as api from "./api.js";

function listItem(item, selected, accepted) {
  return html`<li>
    <button type="button" class="flex w-full flex-col gap-0.5 border-b border-line px-4 py-3 text-left transition-colors ${selected ? "bg-sunken shadow-[inset_3px_0_0_var(--color-ink)]" : "hover:bg-[#faf9f6]"}"
      data-item="${item.bill_id}" data-status="${item.status}" data-tag="${item.tag ?? ""}" aria-current="${selected ? "true" : "false"}">
      <span class="flex items-center justify-between gap-2">
        <span class="truncate font-medium">${item.vendor}</span>
        <span class="num text-sm" title="${moneyExact(item.amount_cents)}">${money(item.amount_cents)}</span>
      </span>
      <span class="flex items-center justify-between gap-2 text-xs text-ink-2">
        <span class="truncate">${item.invoice_number}: ${sentence(item.review_reason)}</span>
        ${accepted ? html`<span class="chip chip-solid">${icon("user-check")}Accepted</span>` : ""}
      </span>
    </button>
  </li>`;
}

function quoteList(spans, documentData) {
  if (!spans.length) return html`<p class="text-sm text-ink-3">No quote.</p>`;
  return html`<ul class="flex flex-col gap-2">${spans.map(
    (s) => html`<li class="text-sm"><span class="label block">${sourceLabel(s.source, documentData)}</span>
      ${highlight(s.text, [{ start: 0, end: s.text.length, origin: s.origin }])}</li>`,
  )}</ul>`;
}

function readersView(item) {
  const r = item.reconciliation;
  const regexSpans = item.evidence.filter((e) => e.origin === "regex");
  const modelSpans = item.evidence.filter((e) => e.origin === "model");
  const regexTerms = r.regex_values?.length ? r.regex_values.map(termsText) : [];
  return html`<div class="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line max-[1180px]:grid-cols-1">
    <div class="flex flex-col gap-2 bg-surface p-4">
      <h3 class="flex items-center gap-2 text-sm font-semibold"><mark class="ev ev-regex text-xs">Aa</mark>Parser (rules)</h3>
      <p class="text-sm">${regexTerms.length ? html`Read <span class="font-medium">${regexTerms.join(" and ")}</span>` : "Found no terms"}${regexTerms.length > 1 ? " (more than one set)" : ""}</p>
      ${quoteList(regexSpans, item.document)}
    </div>
    <div class="flex flex-col gap-2 bg-surface p-4">
      <h3 class="flex items-center gap-2 text-sm font-semibold"><mark class="ev ev-model text-xs">Aa</mark>Local model</h3>
      <p class="text-sm">${r.model_value ? html`Read <span class="font-medium">${termsText(r.model_value)}</span>` : "Gave no reading"}</p>
      <p class="text-xs text-ink-2">${modelCheckText(r)}</p>
      ${quoteList(modelSpans, item.document)}
    </div>
  </div>`;
}

function effectView(result, baseValue) {
  if (result.source === "precomputed") {
    const e = result.effect;
    return { delta: e.value_delta_cents, diff: e.diff, note: "Re-solve precomputed for this item." };
  }
  const delta = result.kpis.value_vs_pay_on_due_cents - baseValue;
  return {
    delta,
    diff: result.diff,
    note: `Re-solved live in ${result.total_seconds.toFixed(2)} s with every accepted change so far. Value change is against the committed plan.`,
  };
}

function effectPanel(result, baseValue) {
  const { delta, diff, note } = effectView(result, baseValue);
  return html`<section class="panel" aria-labelledby="effect-title" tabindex="-1" data-effect>
    <div class="panel-head">
      <div><h3 id="effect-title" class="section-title">Plan re-solved with terms ${termsText(result.terms)}</h3><p class="meta">${note}</p></div>
      <dl class="flex gap-6 text-right">
        <div><dt class="label">Value change</dt><dd class="font-semibold">${valueCell(delta)}</dd></div>
        <div><dt class="label">Decisions changed</dt><dd class="num font-semibold">${diff.length}</dd></div>
      </dl>
    </div>
    ${diffTable(diff, { caption: "Decisions that changed after accepting these terms", compact: true })}
  </section>`;
}

function detailView(item, accepted) {
  const r = item.reconciliation;
  const suggested = item.suggested;
  return html`<div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">${item.vendor} <span class="font-normal text-ink-2">${item.invoice_number}</span></h2>
        <p class="text-sm text-ink-2"><span class="num font-medium text-ink" title="${moneyExact(item.amount_cents)}">${money(item.amount_cents)}</span>, currently planned with ${item.terms}</p>
      </div>
      <span class="chip chip-review">${icon("circle-alert")}${STATUS_LABEL[r.status] ?? r.status}</span>
    </div>
    ${readersView(item)}
    <dl class="dl">
      <dt>Why it is here</dt><dd>${sentence(r.reason)}.</dd>
      ${item.prior_terms ? html`<dt>Terms on file</dt><dd>${termsText(item.prior_terms)}</dd>` : ""}
      ${r.overridden_in_email ? html`<dt>Email thread</dt><dd>A later vendor email changes the invoice's terms.</dd>` : ""}
      ${item.expected ? html`<dt>Expected bill</dt><dd>Issues ${longDate(item.issued_at)}. ${EXPECTED_NOTE}</dd>` : ""}
    </dl>
    <section class="flex flex-col gap-3 rounded-md border border-line-strong p-4" aria-labelledby="suggest-title">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id="suggest-title" class="label">Suggested terms</h3>
          <p class="text-lg font-semibold">${suggested ? termsText(suggested) : "None"}</p>
        </div>
        <div class="flex gap-2">
          <button type="button" class="btn" data-edit ${accepted ? html`disabled` : ""}>${icon("square-pen")}Edit terms</button>
          <button type="button" class="btn btn-primary" data-accept ${accepted || !suggested ? html`disabled` : ""}>${icon("check")}${accepted ? "Accepted" : "Accept and re-solve"}</button>
        </div>
      </div>
      <div data-form hidden>${reviewForm(suggested ?? item.prior_terms)}</div>
      <p class="hidden text-sm risk" role="alert" data-action-error></p>
    </section>
    <div data-effect-slot></div>
    <section class="flex flex-col gap-2" aria-labelledby="doc-title">
      <div class="flex flex-wrap items-center justify-between gap-2"><h3 id="doc-title" class="section-title">Document</h3>${evidenceLegend()}</div>
      ${documentView(item.document, item.evidence, r.authoritative_source)}
    </section>
  </div>`;
}

async function submit(button, item, action, ctx) {
  const errorEl = $("[data-action-error]", ctx.detail);
  const label = button.innerHTML;
  button.disabled = true;
  setHTML(button, html`${icon("loader-circle", "icon spin")}Re-solving`);
  errorEl.classList.add("hidden");
  try {
    const result = await action();
    ctx.accepted.add(item.bill_id);
    invalidate("review", "state", "bills");
    window.dispatchEvent(new CustomEvent(STATE_CHANGED)); // app.js refreshes the nav badge from /api/state
    loadState()
      .then((s) => {
        const el = document.querySelector("[data-review-subhead]");
        if (el) el.textContent = subhead(s.review_count);
      })
      .catch((err) => console.error(err));
    ctx.results.set(item.bill_id, result);
    ctx.select(item.bill_id);
    $("[data-effect]", ctx.detail)?.focus();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
    button.disabled = false;
    button.innerHTML = label;
  }
}

function wireDetail(item, ctx) {
  const form = $("[data-form]", ctx.detail);
  $("[data-accept]", ctx.detail).addEventListener("click", (e) => submit(e.currentTarget, item, () => api.acceptReview(item.bill_id), ctx));
  $("[data-edit]", ctx.detail).addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) $("input", form)?.focus();
  });
  wireAnchorField(form);
  $("form", form).addEventListener("submit", (e) => {
    e.preventDefault();
    const terms = readTerms(e.currentTarget);
    if (!terms) return;
    submit($("[type=submit]", form), item, () => api.editReview(item.bill_id, terms), ctx);
  });
}

function subhead(count) {
  if (!count) return "Nothing left to review. Accepted items stay listed with their effect.";
  return `${count} ${count === 1 ? "bill" : "bills"} whose terms Tempo would not accept on its own. Check the quotes, then accept or edit the terms.`;
}

/** The count comes from /api/state review_count, the same number as the nav badge and the run filter. */
function header(count) {
  return html`<div class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 class="text-xl">Needs review</h1>
      <p class="text-sm text-ink-2" data-review-subhead aria-live="polite">${subhead(count)}</p>
    </div>
    ${uploadControl()}
  </div>`;
}

/** After choosing from the list: keep focus on the chosen item (the list was re-rendered) and bring the
 * detail's top into view if the page was scrolled past it. */
function keepInView(main, detail, billId) {
  main.querySelector(`[data-item="${CSS.escape(billId)}"]`)?.focus({ preventScroll: true });
  if (detail.getBoundingClientRect().top < 0) detail.scrollIntoView({ block: "start" });
}

export async function render(main) {
  const [review, state] = await Promise.all([loadReview(), loadState()]);
  const items = review.items;
  if (!items.length) {
    setHTML(main, html`<div class="flex flex-col gap-4">${header(0)}<section class="panel">${emptyBlock("Nothing needs review", "Every bill's terms were read the same way by the parser and the model, or a reviewer already accepted them.")}</section></div>`);
    wireUpload(main);
    return null;
  }
  setHTML(
    main,
    html`<div class="flex flex-col gap-4">
      ${header(state.review_count)}
      <div class="grid grid-cols-[300px_minmax(0,1fr)] items-start gap-4 max-[1100px]:grid-cols-[240px_minmax(0,1fr)]">
        <nav class="panel sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto" aria-label="Bills needing review"><ul data-list></ul></nav>
        <section class="panel p-5" data-detail aria-live="polite"></section>
      </div>
    </div>`,
  );
  const ctx = {
    detail: $("[data-detail]", main),
    accepted: new Set(review.accepted),
    results: new Map(),
    select: null,
  };
  ctx.select = (id, { fromList = false } = {}) => {
    const item = items.find((i) => i.bill_id === id) ?? items[0];
    setHTML($("[data-list]", main), html`${items.map((i) => listItem(i, i.bill_id === item.bill_id, ctx.accepted.has(i.bill_id)))}`);
    $$("[data-item]", main).forEach((btn) => btn.addEventListener("click", () => ctx.select(btn.dataset.item, { fromList: true })));
    setHTML(ctx.detail, detailView(item, ctx.accepted.has(item.bill_id)));
    const result = ctx.results.get(item.bill_id);
    if (result) setHTML($("[data-effect-slot]", ctx.detail), effectPanel(result, state.kpis.value_vs_pay_on_due_cents));
    wireDetail(item, ctx);
    if (fromList) keepInView(main, ctx.detail, item.bill_id);
  };
  wireUpload(main);
  try {
    ctx.select(items[0].bill_id);
  } catch (err) {
    setHTML(ctx.detail, errorBlock(err, "this review item"));
  }
  return null;
}
