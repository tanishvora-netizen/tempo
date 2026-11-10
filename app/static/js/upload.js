// "Read a PDF invoice" on Needs review: upload one PDF, show the extracted text with the parser's
// spans highlighted, the status, the reading in plain words, and why. Uploads never change the plan.
import { html, icon, setHTML } from "./dom.js";
import { money, sentence, termsText } from "./format.js";
import { modelCheckText, STATUS_LABEL } from "./labels.js";
import { evidenceLegend, highlight, methodsText } from "./evidence.js";
import { openDrawer } from "./drawer.js";
import { loadingBlock } from "./states.js";
import { uploadInvoice } from "./api.js";

const MAX_BYTES = 2 * 1024 * 1024;
const AUTO_ACCEPTED = new Set(["verified", "regex_only", "model_verified"]);
const NOTE = "Reads the terms only; uploads never change the plan.";

export function uploadControl() {
  return html`<div class="flex flex-wrap items-center gap-3">
    <span class="text-xs text-ink-2">${NOTE}</span>
    <label class="btn">
      ${icon("file-text")}Read a PDF invoice
      <input type="file" accept=".pdf,application/pdf" class="sr-only" data-upload>
    </label>
  </div>`;
}

function lateFeeText(fee) {
  if (!fee) return null;
  if (fee.kind === "pct_month" && fee.pct_month_bps) return `${(fee.pct_month_bps / 100).toFixed(2).replace(/\.?0+$/, "")}% per month`;
  if (fee.flat_cents) return `${money(fee.flat_cents)} flat`;
  return null;
}

function statusChip(status) {
  const label = STATUS_LABEL[status] ?? sentence(status);
  return AUTO_ACCEPTED.has(status)
    ? html`<span class="chip chip-solid">${icon("badge-check")}${label}</span>`
    : html`<span class="chip chip-review">${icon("circle-alert")}Needs review: ${label}</span>`;
}

function readingRows(r) {
  const parser = (r.regex_values ?? []).map(termsText);
  const fee = lateFeeText(r.late_fee);
  return html`<dl class="dl">
    <dt>Terms read</dt><dd class="text-base font-semibold">${r.terms ? termsText(r.terms) : "No terms Tempo would accept"}</dd>
    <dt>Status</dt><dd>${statusChip(r.status)}</dd>
    <dt>Why</dt><dd>${sentence(r.reason)}.</dd>
    <dt>Parser</dt><dd>${parser.length ? parser.join(" and ") : "Found no terms"}</dd>
    <dt>Local model</dt><dd>${r.model_value ? termsText(r.model_value) : "No reading"}${r.model_check !== "ok" ? html`<span class="block text-xs text-ink-2">${modelCheckText(r)}</span>` : ""}</dd>
    ${fee ? html`<dt>Late fee</dt><dd>${fee}</dd>` : ""}
    <dt>Accepts</dt><dd>${methodsText(r.accepted_methods)}${r.card_surcharge_bps ? `; card surcharge ${(r.card_surcharge_bps / 100).toFixed(2)}%` : ""}</dd>
  </dl>`;
}

function resultView(r) {
  const spans = (r.evidence ?? []).map((e) => ({ ...e, origin: "regex" }));
  return html`<div class="flex flex-col gap-5">
    <p class="callout">${icon("lock", "icon mt-0.5 flex-none")}${NOTE} The file is read in memory and not stored.</p>
    ${readingRows(r)}
    <section class="flex flex-col gap-2">
      <div class="flex flex-wrap items-center justify-between gap-2"><h3 class="section-title">Text read from the PDF</h3>${evidenceLegend(["regex"])}</div>
      <div class="doc rounded-md border border-line px-4 py-3">${highlight(r.text ?? "", spans)}</div>
    </section>
  </div>`;
}

function errorView(err) {
  const throttled = err.status === 429;
  return html`<div class="callout callout-risk items-start" role="alert">${icon("circle-x", "icon mt-0.5 flex-none")}
    <div><p class="font-medium">${throttled ? "Too many uploads right now." : "Tempo could not read this file."}</p>
    <p>${sentence(err.message).replace(/([^.])$/, "$1.")}${throttled ? "" : " Upload a text-based PDF (not a scan), up to 2 MB and 10 pages."}</p></div></div>`;
}

function validate(file) {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Choose a PDF file.";
  if (file.size > MAX_BYTES) return "That PDF is larger than 2 MB.";
  return null;
}

async function readFile(file) {
  const body = openDrawer({ id: "upload", title: "Read a PDF invoice", subtitle: file.name, wide: true });
  const problem = validate(file);
  if (problem) {
    setHTML(body, errorView({ status: 422, message: problem }));
    return;
  }
  setHTML(body, loadingBlock(`Reading ${file.name}`, 6));
  try {
    setHTML(body, resultView(await uploadInvoice(file)));
  } catch (err) {
    setHTML(body, errorView(err));
  }
}

export function wireUpload(root) {
  const input = root.querySelector("[data-upload]");
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    input.value = "";
    if (file) readFile(file);
  });
}
