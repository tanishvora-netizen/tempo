// Proof > Extraction accuracy on the synthetic labeled set: three readers, holdout vs all,
// routing buckets, hallucination catch, and results by difficulty tag.
import { $, $$, html, setHTML } from "./dom.js";
import { count, pct } from "./format.js";

const READERS = [
  ["regex", "Parser only"],
  ["model", "Model only (unverified)"],
  ["reconciled", "Reconciled (Tempo)"],
];

const BUCKET = {
  verified: "Parser and model agree",
  regex_only: "Parser only, one clear match",
  model_verified: "Model quote verified",
  conflict: "Parser and model disagree",
  hallucination_flag: "Model quote not found",
  ambiguous_document: "More than one set of terms",
  sanity_fail: "Fails a sanity rule",
  history_mismatch: "Differs from terms on file",
};
const AUTO_ACCEPTED = new Set(["verified", "regex_only", "model_verified"]);

const TAG = {
  clean: "Clean layout",
  date_lookalike: "Date that looks like terms (#2/10/2026)",
  email_only: "Terms only in an email",
  email_override: "Email changes the terms",
  eom_prox: "End-of-month and prox terms",
  footer_conflict: "Footer contradicts the header",
  fraction: "Fractions such as 1/2%",
  injection: "Prompt injection in the invoice",
  ocr_noise: "Scanning noise",
  prose_terms: "Terms written in words",
  surcharge_text: "Card surcharge wording",
};

function readerTable(split) {
  return html`<table class="tbl">
    <caption class="sr-only">Accuracy by reader</caption>
    <thead><tr><th scope="col">Reader</th><th scope="col" class="r">Answered</th><th scope="col" class="r">Accuracy (all invoices)</th>
      <th scope="col" class="r">Precision (answered)</th><th scope="col" class="r">Discount precision</th><th scope="col" class="r">Discount recall</th></tr></thead>
    <tbody>${READERS.map(([key, label]) => {
      const r = split[key];
      return html`<tr class="${key === "reconciled" ? "is-selected font-medium" : ""}">
        <td>${label}</td>
        <td class="r num">${count(r.answered)} / ${count(r.n)}</td>
        <td class="r num">${pct(r.accuracy, 1)}</td>
        <td class="r num">${pct(r.precision, 1)}</td>
        <td class="r num">${pct(r.discount_precision, 1)}</td>
        <td class="r num">${pct(r.discount_recall, 1)}</td>
      </tr>`;
    })}</tbody>
  </table>`;
}

function bucketTable(split) {
  const rows = Object.entries(split.buckets).sort((a, b) => b[1].n - a[1].n);
  return html`<table class="tbl">
    <caption class="sr-only">Accuracy by routing bucket</caption>
    <thead><tr><th scope="col">Bucket</th><th scope="col">Route</th><th scope="col" class="r">n</th><th scope="col" class="r">Correct</th></tr></thead>
    <tbody>${rows.map(([id, b]) => html`<tr>
      <td>${BUCKET[id] ?? id}</td>
      <td class="text-ink-2">${AUTO_ACCEPTED.has(id) ? "Auto-accepted" : "Needs review"}</td>
      <td class="r num">${count(b.n)}</td>
      <td class="r num">${AUTO_ACCEPTED.has(id) ? `${count(b.correct)} (${pct(b.n ? b.correct / b.n : null, 1)})` : html`<span class="text-ink-3">sent to a person</span>`}</td>
    </tr>`)}</tbody>
  </table>`;
}

function tagTable(byTag) {
  const rows = Object.entries(byTag).sort((a, b) => b[1].reconciled.n - a[1].reconciled.n);
  return html`<table class="tbl">
    <caption class="sr-only">Results by difficulty tag</caption>
    <thead><tr><th scope="col">Difficulty</th><th scope="col" class="r">Invoices</th><th scope="col" class="r">Auto-accepted</th>
      <th scope="col" class="r">Correct when accepted</th><th scope="col" class="r">Parser accuracy</th><th scope="col" class="r">Model answered</th></tr></thead>
    <tbody>${rows.map(([tag, t]) => html`<tr>
      <td>${TAG[tag] ?? tag}</td>
      <td class="r num">${count(t.reconciled.n)}</td>
      <td class="r num">${count(t.reconciled.answered)}</td>
      <td class="r num">${count(t.reconciled.correct)}</td>
      <td class="r num">${pct(t.regex.accuracy, 1)}</td>
      <td class="r num">${count(t.model.answered)}</td>
    </tr>`)}</tbody>
  </table>`;
}

function headline(split) {
  const r = split.reconciled;
  const h = split.hallucination_catch;
  const routed = split.expected_reviews_routed;
  const stat = (value, label) => html`<div class="flex flex-col gap-0.5 px-4 py-3"><span class="text-xl font-semibold num">${value}</span><span class="text-xs text-ink-2">${label}</span></div>`;
  return html`<div class="grid grid-cols-4 divide-x divide-line border-b border-line max-[1180px]:grid-cols-2">
    ${stat(pct(r.coverage, 1), html`auto-accepted at <span class="num">${pct(r.precision, 1)}</span> precision; the rest go to Needs review`)}
    ${stat(pct(split.invoice_all_correct_rate, 1), "of invoices have every field right and auto-accepted")}
    ${stat(`${count(routed.routed)} of ${count(routed.n)}`, "documents a careful clerk would escalate were routed to review")}
    ${stat(`${count(h.kept_out_of_plan)} of ${count(h.wrong_model_readings)}`, html`wrong model readings kept out of the plan (<span class="num">${count(h.rejected_by_verification)}</span> rejected by quote check)`)}
  </div>`;
}

function splitBody(ex, which) {
  const split = ex[which];
  return html`${headline(split)}
    <div class="overflow-x-auto">${readerTable(split)}</div>
    <div class="grid grid-cols-12 border-t border-line">
      <div class="col-span-5 border-r border-line max-[1180px]:col-span-12 max-[1180px]:border-r-0 max-[1180px]:border-b">
        <h3 class="section-title px-4 pt-3">Routing buckets</h3>${bucketTable(split)}
      </div>
      <div class="col-span-7 max-[1180px]:col-span-12">
        <h3 class="section-title px-4 pt-3">By difficulty (all invoices)</h3>${tagTable(ex.by_tag)}
      </div>
    </div>`;
}

export function extractionSection(ex) {
  const toggle = html`<div class="seg" role="group" aria-label="Which invoices">
    <button type="button" data-split="holdout" aria-pressed="true">Held-out split (${count(ex.holdout.reconciled.n)})</button>
    <button type="button" data-split="all" aria-pressed="false">All invoices (${count(ex.all.reconciled.n)})</button>
  </div>`;
  return html`<section class="panel" id="extraction" aria-labelledby="extraction-title" tabindex="-1">
    <div class="panel-head">
      <div>
        <h2 id="extraction-title" class="panel-title">Reading payment terms</h2>
        <p class="meta">Synthetic labeled set. Core terms: discount, discount days, net days, anchor, prox day.</p>
      </div>
      ${toggle}
    </div>
    ${ex.has_model_outputs ? "" : html`<p class="callout m-4">No cached model outputs in this build: the model column shows nothing answered.</p>`}
    <div data-extraction-body>${splitBody(ex, "holdout")}</div>
  </section>`;
}

export function wireExtraction(root, ex) {
  $$("[data-split]", root).forEach((btn) =>
    btn.addEventListener("click", () => {
      $$("[data-split]", root).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      setHTML($("[data-extraction-body]", root), splitBody(ex, btn.dataset.split));
    }),
  );
}
