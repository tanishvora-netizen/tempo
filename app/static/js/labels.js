// Plain-English labels for solver enums, and the shared status chip / money cell renderers.
import { html, icon } from "./dom.js";
import { money, moneyExact } from "./format.js";

export const OPTION_LABEL = {
  BANK_DUE: "Pay on due date",
  BANK_EARLY: "Pay early for discount",
  CARD: "Pay by card",
  CARD_EARLY: "Card early for discount",
  FINANCE_EARLY: "Finance early for discount",
  LATE: "Pay late",
};

export const OPTION_SHORT = {
  BANK_DUE: "On due date",
  BANK_EARLY: "Early, discount",
  CARD: "Card",
  CARD_EARLY: "Card, discount",
  FINANCE_EARLY: "Financed, discount",
  LATE: "Late",
};

export const RAIL_LABEL = { RTP: "RTP", ACH: "ACH", CARD: "Card", FINANCE: "Financing" };
const RAIL_ICON = { RTP: "zap", ACH: "landmark", CARD: "credit-card", FINANCE: "banknote" };

export const STATUS_LABEL = {
  verified: "Parser and model agree",
  regex_only: "Parser only (one clear match)",
  model_verified: "Model quote verified by parser",
  conflict: "Parser and model disagree",
  hallucination_flag: "Model quote not found in the document",
  ambiguous_document: "Document states more than one set of terms",
  sanity_fail: "Terms fail a sanity rule",
  history_mismatch: "Differs from this vendor's terms on file",
};

const CHIP = {
  Verified: { icon: "badge-check", cls: "chip-solid" },
  "Model verified": { icon: "badge-check", cls: "chip-solid" },
  "Regex only": { icon: "scan-text", cls: "" },
  "Needs review": { icon: "circle-alert", cls: "chip-review" },
  "Accepted by reviewer": { icon: "user-check", cls: "chip-solid" },
};

const CHIP_TEXT = { "Regex only": "Parser only" };

export function chip(label) {
  const spec = CHIP[label] ?? { icon: "info", cls: "" };
  return html`<span class="chip ${spec.cls}">${icon(spec.icon)}${CHIP_TEXT[label] ?? label}</span>`;
}

export function railCell(rail) {
  const name = RAIL_ICON[rail];
  return html`<span class="inline-flex items-center gap-1.5 text-ink-2">${name ? icon(name, "icon text-ink-3") : ""}${RAIL_LABEL[rail] ?? rail}</span>`;
}

/** Value relative to paying on the due date: green when gained, red when lost. */
export function valueCell(cents) {
  const cls = cents > 0 ? "gain" : cents < 0 ? "risk" : "text-ink-3";
  return html`<span class="num ${cls}" title="${moneyExact(cents)}">${cents === 0 ? "$0" : money(cents, { signed: true })}</span>`;
}

export function optionCell(row) {
  const label = OPTION_SHORT[row.option] ?? row.option;
  if (row.option === "LATE") return html`<span class="chip chip-risk">${icon("triangle-alert")}Late</span>`;
  return html`<span>${label}</span>`;
}
