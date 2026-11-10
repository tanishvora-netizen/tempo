// Small shared view pieces: the risk meter and the flipped-decisions diff table.
import { html } from "./dom.js";
import { money, moneyExact, pct, shortDate } from "./format.js";
import { OPTION_SHORT, valueCell } from "./labels.js";

const METER_HEADROOM = 1.5; // the scale runs to 1.5x the target so the target line sits at two thirds

/** Measured breach rate (bar), one-sided 95% upper bound (tick), target (dashed line). */
export function riskMeter({ rate, upper, target }) {
  const scale = Math.max(target * METER_HEADROOM, upper * 1.1);
  const at = (x) => `${Math.min(100, (x / scale) * 100).toFixed(2)}%`;
  const over = upper > target;
  return html`<div class="flex flex-col gap-1.5">
    <div class="meter" role="img" aria-label="Breach probability ${pct(rate)}, upper bound ${pct(upper)}, target ${pct(target, 0)}">
      <div class="meter-fill ${over ? "over" : ""}" style="width:${at(rate)}"></div>
      <div class="meter-bound" style="left:${at(upper)}" title="95% upper bound ${pct(upper)}"></div>
      <div class="meter-target" style="left:${at(target)}" title="Target ${pct(target, 0)}"></div>
    </div>
    <div class="relative h-4 text-2xs text-ink-3">
      <span class="absolute left-0">0%</span>
      <span class="absolute -translate-x-1/2" style="left:${at(target)}">Target ${pct(target, 0)}</span>
    </div>
  </div>`;
}

function optionChange(side) {
  const late = side.option === "LATE";
  return html`<span class="whitespace-nowrap ${late ? "risk font-medium" : ""}">${OPTION_SHORT[side.option] ?? side.option}</span>
    <span class="num whitespace-nowrap text-ink-3"> ${shortDate(side.send_date)}</span>`;
}

function diffRow(d, compact) {
  const reason = html`<p class="line-clamp-2 text-ink-2 ${compact ? "mt-0.5 text-xs" : ""}" title="${d.reason}">${d.reason}</p>`;
  return html`<tr>
    <td class="${compact ? "max-w-[340px]" : ""}"><div class="font-medium">${d.vendor} <span class="meta whitespace-nowrap font-normal">${d.invoice_number}</span></div>${compact ? reason : ""}</td>
    <td class="r num" title="${moneyExact(d.amount_cents)}">${money(d.amount_cents)}</td>
    <td class="text-ink-2">${optionChange(d.before)}</td>
    <td>${optionChange(d.after)}</td>
    <td class="r">${valueCell(d.after.value_cents - d.before.value_cents)}</td>
    ${compact ? "" : html`<td class="max-w-[440px]">${reason}</td>`}
  </tr>`;
}

/** Decisions that changed between two plans, with the new reason (compact: reason under the vendor). */
export function diffTable(diff, { caption = "Decisions that changed", compact = false } = {}) {
  if (!diff.length) {
    return html`<p class="px-4 py-6 text-center text-sm text-ink-2">No decisions changed. The plan is the same as before.</p>`;
  }
  const swing = (d) => Math.abs(d.after.value_cents - d.before.value_cents);
  const sorted = [...diff].sort((a, b) => swing(b) - swing(a));
  return html`<div class="max-h-[480px] overflow-y-auto"><table class="tbl">
    <caption class="sr-only">${caption}</caption>
    <thead><tr>
      <th scope="col">Vendor</th>
      <th scope="col" class="r">Amount</th>
      <th scope="col">Before</th>
      <th scope="col">After</th>
      <th scope="col" class="r">Value change</th>
      ${compact ? "" : html`<th scope="col">Why</th>`}
    </tr></thead>
    <tbody>${sorted.map((d) => diffRow(d, compact))}</tbody>
  </table></div>`;
}
