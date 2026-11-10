// The autonomy setting ("Suggest only" or "Auto-schedule Verified bills under $X") and the preview of
// which of this week's bills it would schedule. Mirrors tempo/ramp/payloads.py auto_scheduled_ids: the
// threshold applies to each vendor's total in an ISO week, so splitting an invoice cannot slip under it.
import { $, $$, html } from "./dom.js";
import { count, dollarsField, isoWeek, money, moneyExact, parseDollars } from "./format.js";
import { ui } from "./store.js";

const DOLLARS_MAX = 2_000_000;

export function currentAutonomy(state) {
  if (!ui.autonomy) ui.autonomy = { ...state.autonomy };
  return ui.autonomy;
}

const weekKey = (b) => `${b.vendor_id}|${isoWeek(b.send_date)}`;

/** Bills Tempo would schedule without asking: Verified, not in review, vendor's weekly total under the threshold. */
export function autoScheduled(rows, allBills, thresholdCents) {
  const weekly = new Map();
  allBills
    .filter((b) => b.send_date)
    .forEach((b) => weekly.set(weekKey(b), (weekly.get(weekKey(b)) ?? 0) + b.amount_cents));
  return rows.filter((b) => b.chip === "Verified" && !b.needs_review && weekly.get(weekKey(b)) < thresholdCents);
}

export function autoSummary(rows, allBills, autonomy) {
  if (autonomy.mode !== "auto") return html`Every bill waits for your approval.`;
  const q = autoScheduled(rows, allBills, autonomy.threshold_cents);
  const total = q.reduce((s, b) => s + b.cash_out_cents, 0);
  return html`<span class="num font-medium text-ink">${count(q.length)}</span> of this week's ${count(rows.length)} bills
    (<span class="num" title="${moneyExact(total)}">${money(total)}</span>) would be scheduled without asking. The rest wait for approval.`;
}

export function autonomyFields(autonomy, idPrefix) {
  return html`<fieldset class="flex flex-col gap-2">
    <legend class="label mb-1.5">Autonomy</legend>
    <label class="flex items-start gap-2 text-sm">
      <input type="radio" name="${idPrefix}-autonomy" value="suggest" class="mt-1" ${autonomy.mode !== "auto" ? html`checked` : ""}>
      <span><span class="font-medium">Suggest only</span><span class="block text-xs text-ink-2">Tempo proposes; you approve every run.</span></span>
    </label>
    <label class="flex items-start gap-2 text-sm">
      <input type="radio" name="${idPrefix}-autonomy" value="auto" class="mt-1" ${autonomy.mode === "auto" ? html`checked` : ""}>
      <span class="flex flex-col gap-1.5">
        <span class="font-medium">Auto-schedule Verified bills under</span>
        <span class="flex items-center gap-1.5"><span class="text-ink-2">$</span>
          <input type="text" inputmode="numeric" value="${dollarsField(autonomy.threshold_cents)}" class="field w-28 num"
            aria-label="Auto-schedule threshold in dollars" data-threshold ${autonomy.mode === "auto" ? "" : html`disabled`}>
        </span>
        <span class="text-xs text-ink-2">Verified means the parser and the model agree. The threshold applies to each vendor's total for the week, so splitting an invoice does not get under it.</span>
      </span>
    </label>
    <p class="hidden text-xs risk" data-threshold-error role="alert"></p>
  </fieldset>`;
}

function readThreshold(input, errorEl) {
  const cents = parseDollars(input.value);
  const valid = cents !== null && cents >= 100 && cents <= DOLLARS_MAX * 100;
  errorEl.classList.toggle("hidden", valid);
  errorEl.textContent = valid ? "" : `Enter a dollar amount between $1 and ${money(DOLLARS_MAX * 100)}.`;
  return valid ? cents : null;
}

/** Keep ui.autonomy in sync with one set of autonomy fields; returns a validity check for submit. */
export function wireAutonomy(root, idPrefix, onChange) {
  const input = $("[data-threshold]", root);
  const errorEl = $("[data-threshold-error]", root);
  $$(`input[name="${idPrefix}-autonomy"]`, root).forEach((radio) =>
    radio.addEventListener("change", () => {
      ui.autonomy = { ...ui.autonomy, mode: radio.value };
      input.disabled = radio.value !== "auto";
      onChange();
    }),
  );
  input.addEventListener("input", () => {
    const cents = readThreshold(input, errorEl);
    if (cents === null) return;
    ui.autonomy = { ...ui.autonomy, threshold_cents: cents };
    onChange();
  });
  input.addEventListener("blur", () => {
    if (readThreshold(input, errorEl) !== null) input.value = dollarsField(ui.autonomy.threshold_cents);
  });
  return () => ui.autonomy.mode !== "auto" || readThreshold(input, errorEl) !== null;
}
