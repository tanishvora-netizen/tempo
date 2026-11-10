// The small Edit terms form on Needs review. Bounds mirror app/schemas.py TermsInput.
import { $, html, icon } from "./dom.js";

const LIMITS = {
  discount_pct: { min: 0, max: 5, step: 0.25, label: "Discount %" },
  discount_days: { min: 0, max: 60, step: 1, label: "Discount days" },
  net_days: { min: 0, max: 120, step: 1, label: "Net days" },
  prox_day: { min: 1, max: 31, step: 1, label: "Day of next month" },
};
const ANCHORS = [
  ["invoice_date", "From invoice date"],
  ["eom", "From end of month"],
  ["prox", "Fixed day next month (prox)"],
  ["receipt", "Due on receipt"],
];

function numberField(name, value) {
  const l = LIMITS[name];
  return html`<label class="flex flex-col gap-1 text-xs text-ink-2" data-field="${name}">
    ${l.label}
    <input type="number" name="${name}" min="${l.min}" max="${l.max}" step="${l.step}" value="${value ?? ""}" class="field w-28 num" inputmode="decimal">
  </label>`;
}

export function reviewForm(terms) {
  const t = terms ?? {};
  const pctValue = t.discount_bps ? t.discount_bps / 100 : "";
  return html`<form class="flex flex-col gap-3 border-t border-line pt-3" novalidate>
    <div class="flex flex-wrap items-end gap-3">
      ${numberField("discount_pct", pctValue)}
      ${numberField("discount_days", t.discount_days)}
      ${numberField("net_days", t.net_days)}
      <label class="flex flex-col gap-1 text-xs text-ink-2">
        Counted from
        <select name="anchor" class="field">
          ${ANCHORS.map(([v, label]) => html`<option value="${v}" ${v === (t.anchor ?? "invoice_date") ? html`selected` : ""}>${label}</option>`)}
        </select>
      </label>
      ${numberField("prox_day", t.prox_day)}
      <button type="submit" class="btn btn-primary">${icon("check")}Save and re-solve</button>
    </div>
    <p class="text-xs text-ink-2">Leave the discount empty if there is none. Tempo re-solves the plan with these terms.</p>
    <p class="hidden text-sm risk" role="alert" data-form-error></p>
  </form>`;
}

export function wireAnchorField(container) {
  const form = $("form", container);
  const sync = () => {
    const prox = form.anchor.value === "prox";
    form.querySelector('[data-field="prox_day"]').hidden = !prox;
  };
  form.anchor.addEventListener("change", sync);
  sync();
}

function readNumber(form, name) {
  const raw = form[name].value.trim();
  if (raw === "") return { value: null };
  const value = Number(raw);
  const l = LIMITS[name];
  if (!Number.isFinite(value) || value < l.min || value > l.max) {
    return { error: `${l.label} must be between ${l.min} and ${l.max}.` };
  }
  if (name !== "discount_pct" && !Number.isInteger(value)) return { error: `${l.label} must be a whole number.` };
  return { value };
}

/** Validate and return a TermsInput payload, or null after showing the error. */
export function readTerms(form) {
  const errorEl = form.querySelector("[data-form-error]");
  const fields = ["discount_pct", "discount_days", "net_days", "prox_day"].map((n) => [n, readNumber(form, n)]);
  const firstError = fields.find(([, r]) => r.error);
  const values = Object.fromEntries(fields.map(([n, r]) => [n, r.value ?? null]));
  const anchor = form.anchor.value;
  let message = firstError ? firstError[1].error : "";
  if (!message && values.discount_pct && values.discount_days === null) message = "A discount needs discount days.";
  if (!message && values.discount_pct && values.net_days !== null && values.discount_days >= values.net_days) message = "Discount days must be fewer than net days.";
  if (!message && anchor === "prox" && values.prox_day === null) message = "Choose the day of next month the bill is due.";
  if (!message && anchor !== "receipt" && anchor !== "prox" && values.net_days === null) message = "Enter the net days.";
  errorEl.textContent = message;
  errorEl.classList.toggle("hidden", !message);
  if (message) return null;
  return {
    discount_pct: values.discount_pct || null,
    discount_days: values.discount_pct ? values.discount_days : null,
    net_days: values.net_days,
    anchor,
    prox_day: anchor === "prox" ? values.prox_day : null,
  };
}
