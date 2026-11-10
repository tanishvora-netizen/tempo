// Invoice and email text with highlighted evidence spans. Parser (regex) spans and model
// quotes use different fills and rule styles so they read apart without color alone.
import { html, raw, esc } from "./dom.js";
import { longDate } from "./format.js";

const BLOCK_LABEL = { header: "Invoice header", body: "Invoice body", payment_box: "Payment box", footer: "Invoice footer" };
const ORIGIN_TITLE = { regex: "Found by the parser", model: "Quoted by the local model", both: "Found by the parser and quoted by the model" };

export function sourceLabel(source, documentData) {
  if (BLOCK_LABEL[source]) return BLOCK_LABEL[source];
  const email = documentData?.emails?.find((e) => e.id === source);
  if (email) return `Email from ${email.sender}, ${longDate(email.sent_at)}`;
  return source;
}

function boundaries(spans, length) {
  const points = new Set([0, length]);
  spans.forEach((s) => {
    points.add(Math.max(0, Math.min(length, s.start)));
    points.add(Math.max(0, Math.min(length, s.end)));
  });
  return [...points].sort((a, b) => a - b);
}

/** Split text at span edges and wrap covered pieces in <mark> by origin. */
export function highlight(text, spans) {
  if (!spans.length) return raw(esc(text));
  const cuts = boundaries(spans, text.length);
  let out = "";
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const [a, b] = [cuts[i], cuts[i + 1]];
    const piece = esc(text.slice(a, b));
    const origins = new Set(spans.filter((s) => s.start <= a && s.end >= b).map((s) => s.origin));
    if (!origins.size) {
      out += piece;
      continue;
    }
    const kind = origins.size > 1 ? "both" : [...origins][0];
    out += `<mark class="ev ev-${kind}" title="${ORIGIN_TITLE[kind]}">${piece}</mark>`;
  }
  return raw(out);
}

const LEGEND = { regex: "Parser (rules)", model: "Local model quote", both: "Both" };

/** Legend for the highlight styles; pass kinds to show only the ones on screen. */
export function evidenceLegend(kinds = ["regex", "model", "both"]) {
  return html`<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
    ${kinds.map((k) => html`<span class="inline-flex items-center gap-1.5"><mark class="ev ev-${k}" aria-hidden="true">Aa</mark>${LEGEND[k]}</span>`)}
  </div>`;
}

const METHOD_LABEL = { ACH: "ACH", CARD: "Card", CHECK: "Check", WIRE: "Wire", RTP: "RTP" };

/** ["ACH", "CARD"] -> "ACH, Card" */
export function methodsText(methods) {
  return (methods ?? []).map((m) => METHOD_LABEL[m] ?? m).join(", ") || "Not stated";
}

function blockView(block, spans) {
  return html`<div class="doc-block px-4 py-3">
    <p class="label mb-1">${BLOCK_LABEL[block.kind] ?? block.kind}</p>
    <div class="doc">${highlight(block.text, spans)}</div>
  </div>`;
}

function emailView(email, spans, authoritative) {
  return html`<div class="doc-block px-4 py-3">
    <div class="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
      <p class="label">Email from ${email.sender}, ${longDate(email.sent_at)}</p>
      ${authoritative ? html`<span class="chip chip-solid">Terms taken from this message</span>` : ""}
    </div>
    <p class="mb-1 text-sm font-medium">${email.subject}</p>
    <div class="doc">${highlight(email.text, spans)}</div>
  </div>`;
}

/** The whole document: invoice blocks then the email thread, each with its own spans. */
export function documentView(documentData, evidence, authoritativeSource = null) {
  const spansFor = (id) => evidence.filter((e) => e.source === id);
  return html`<div class="rounded-md border border-line bg-surface">
    ${documentData.blocks.map((b) => blockView(b, spansFor(b.id)))}
    ${documentData.emails.length
      ? html`<div class="border-t border-line-strong bg-[#faf9f6] px-4 py-2 text-xs font-medium text-ink-2">Email thread (${documentData.emails.length})</div>
        ${documentData.emails.map((e) => emailView(e, spansFor(e.id), e.id === authoritativeSource))}`
      : ""}
  </div>`;
}
