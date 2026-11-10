// Approve this week's run: the autonomy setting on Overview, then a dialog for the attested name.
// Approval writes a hash-chained audit entry; nothing is sent to Ramp.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, dollarsField, money, moneyExact, shortDate } from "./format.js";
import { approvePlan, getPayloadPreview } from "./api.js";
import { invalidate, STATE_CHANGED, ui } from "./store.js";
import { openAuditDrawer } from "./drawers.js";
import { autonomyFields, autoSummary, currentAutonomy, wireAutonomy } from "./autonomy.js";

const APPROVER_PATTERN = /^[\w .,'@-]{1,80}$/;
const GATE_NOTE = "Ramp's own approval chain and vendor bank verification still gate payment; Tempo only sets date and rail.";

export function approvalPanel(state, rows, allBills) {
  const autonomy = currentAutonomy(state);
  return html`<aside class="flex w-[300px] flex-none flex-col gap-4 border-l border-line p-4 max-[1180px]:grid max-[1180px]:w-full max-[1180px]:grid-cols-2 max-[1180px]:gap-x-8 max-[1180px]:border-l-0 max-[1180px]:border-t" aria-labelledby="approve-title" data-approval>
    <div>
      <h3 id="approve-title" class="section-title">Approve and schedule</h3>
      <p class="mt-0.5 text-xs text-ink-2">Approval writes an audit entry and builds the Ramp bill updates. Nothing is sent.</p>
    </div>
    ${autonomyFields(autonomy, "panel")}
    <p class="text-xs text-ink-2" data-auto-summary aria-live="polite">${autoSummary(rows, allBills, autonomy)}</p>
    <div class="mt-auto flex flex-col gap-2">
      <button type="button" class="btn btn-primary h-9 justify-center" data-approve>${icon("check")}Approve this week's run</button>
      <button type="button" class="btn btn-quiet btn-sm justify-center" data-open-audit>${icon("scroll-text")}View audit log</button>
    </div>
  </aside>`;
}

/** The ACH date the payload preview uses for an RTP bill that can still meet its target by ACH. */
function achDates(preview) {
  const dates = new Map();
  preview.bills.forEach((b) => {
    const patch = b.requests.find((r) => r.method === "PATCH");
    if (patch?.body?.payment_date) dates.set(b.bill_id, patch.body.payment_date);
  });
  return dates;
}

function rtpRow(b, dates) {
  const action = b.rtp_dependent
    ? html`<span class="text-review">Send by RTP in Ramp (Ramp's API cannot request RTP; ACH would arrive late)</span>`
    : dates
      ? html`ACH sent ${dates.has(b.bill_id) ? shortDate(dates.get(b.bill_id)) : "earlier"} instead, arriving in time`
      : html`<span class="text-ink-3">Loading the ACH date</span>`;
  return html`<li class="flex flex-col gap-0.5 py-1.5">
    <span class="flex justify-between gap-3"><span class="font-medium">${b.vendor}</span>
      <span class="num" title="${moneyExact(b.cash_out_cents)}">${money(b.cash_out_cents)}, send ${shortDate(b.send_date)}</span></span>
    <span class="text-ink-2">${action}</span>
  </li>`;
}

function rtpList(rtpRows, dates) {
  return html`${rtpRows.map((b) => rtpRow(b, dates))}`;
}

function rtpNotice(rows) {
  const rtpRows = rows.filter((b) => b.rail === "RTP");
  if (!rtpRows.length) return "";
  const manual = rtpRows.filter((b) => b.rtp_dependent).length;
  const split =
    manual === rtpRows.length
      ? html`${rtpRows.length === 1 ? "it" : "all"} must be sent by RTP in Ramp.`
      : manual === 0
        ? html`all can go by ACH sent earlier instead.`
        : html`<span class="num font-medium">${count(manual)}</span> must be sent by RTP in Ramp; the rest go by ACH sent earlier.`;
  return html`<details class="group rounded-md border border-[#ecd9b0] bg-review-tint text-sm" data-rtp-details>
    <summary class="flex items-start gap-2 px-3 py-2 text-review">${icon("zap", "icon mt-0.5 flex-none")}
      <span class="flex-1"><span class="num font-medium">${count(rtpRows.length)}</span> ${rtpRows.length === 1 ? "bill relies" : "bills rely"} on RTP from Ramp Checking: ${split}
      <span class="font-medium underline underline-offset-2">Show the list</span></span>${icon("chevron-down", "icon mt-0.5 flex-none transition-transform group-open:rotate-180")}</summary>
    <ul class="max-h-48 divide-y divide-[#ecd9b0] overflow-y-auto border-t border-[#ecd9b0] bg-surface px-3 text-xs" data-rtp-list>${rtpList(rtpRows, null)}</ul>
  </details>`;
}

function dialogMarkup(state, rows) {
  const value = rows.reduce((s, b) => s + b.value_cents, 0);
  const total = rows.reduce((s, b) => s + b.cash_out_cents, 0);
  return html`<form method="dialog" class="flex flex-col gap-4 p-5" novalidate>
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-lg font-semibold" id="approve-dialog-title">Approve this week's run</h2>
        <p class="text-sm text-ink-2">This approves <span class="num font-medium text-ink">${count(rows.length)}</span> bills,
          <span class="num font-medium text-ink" title="${moneyExact(total)}">${money(total)}</span> paid out,
          value <span class="num gain" title="${moneyExact(value)}">${money(value, { signed: true })}</span>. Plan ${state.plan_hash.slice(0, 12)}.</p>
      </div>
      <button type="button" class="btn btn-quiet btn-icon" data-cancel aria-label="Cancel">${icon("x")}</button>
    </div>
    <label class="flex flex-col gap-1 text-sm font-medium">Attested name (not authenticated in this demo)
      <input type="text" name="approver" class="field" maxlength="80" autocomplete="name" placeholder="Your name" required>
      <span class="text-xs font-normal text-ink-2">Letters, digits, spaces, and . , ' @ - only. Recorded in the audit log as typed.</span>
    </label>
    ${autonomyFields(ui.autonomy, "dialog")}
    ${rtpNotice(rows)}
    <p class="text-xs text-ink-2">${GATE_NOTE}</p>
    <p class="hidden text-sm risk" role="alert" data-dialog-error></p>
    <div class="flex justify-end gap-2 border-t border-line pt-4">
      <button type="button" class="btn" data-cancel>Cancel</button>
      <button type="submit" class="btn btn-primary" data-confirm>${icon("check")}Approve and record</button>
    </div>
  </form>`;
}

function showDialogError(dialog, message) {
  const el = $("[data-dialog-error]", dialog);
  el.textContent = message;
  el.classList.remove("hidden");
}

async function confirmApproval(dialog, rows, isAutonomyValid, onApproved) {
  const name = dialog.querySelector('[name="approver"]').value.trim();
  if (!APPROVER_PATTERN.test(name)) {
    showDialogError(dialog, "Enter the approver's name (letters, digits, spaces, and . , ' @ - only, up to 80 characters).");
    dialog.querySelector('[name="approver"]').focus();
    return;
  }
  if (!isAutonomyValid()) return;
  const button = $("[data-confirm]", dialog);
  button.disabled = true;
  setHTML(button, html`${icon("loader-circle", "icon spin")}Recording`);
  try {
    const result = await approvePlan(name, ui.autonomy, rows.map((b) => b.bill_id));
    invalidate("state");
    window.dispatchEvent(new CustomEvent(STATE_CHANGED));
    dialog.close();
    onApproved();
    openAuditDrawer({ entry: result.entry });
  } catch (err) {
    showDialogError(dialog, err.message);
    button.disabled = false;
    setHTML(button, html`${icon("check")}Approve and record`);
  }
}

/** Fill the RTP list's ACH dates from the payload preview (the same dates the Ramp requests would carry). */
async function fillAchDates(dialog, rows) {
  const list = $("[data-rtp-list]", dialog);
  if (!list) return;
  const rtpRows = rows.filter((b) => b.rail === "RTP");
  try {
    setHTML(list, rtpList(rtpRows, achDates(await getPayloadPreview())));
  } catch (err) {
    console.error(err);
    setHTML(list, html`${rtpList(rtpRows, new Map())}<li class="py-1.5 text-ink-3">The payload preview did not load; ACH dates are in the Audit log.</li>`);
  }
}

function openApproveDialog(state, rows, onApproved) {
  const dialog = document.createElement("dialog");
  dialog.className = "modal m-auto max-h-[calc(100vh-32px)] w-[min(520px,calc(100vw-32px))] overflow-y-auto rounded-lg border border-line-strong bg-surface p-0 text-ink shadow-2xl";
  dialog.setAttribute("aria-labelledby", "approve-dialog-title");
  setHTML(dialog, dialogMarkup(state, rows));
  document.body.append(dialog);
  const isAutonomyValid = wireAutonomy(dialog, "dialog", () => {});
  $$("[data-cancel]", dialog).forEach((b) => b.addEventListener("click", () => dialog.close()));
  $("form", dialog).addEventListener("submit", (event) => {
    event.preventDefault();
    confirmApproval(dialog, rows, isAutonomyValid, onApproved);
  });
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  dialog.querySelector('[name="approver"]').focus();
  fillAchDates(dialog, rows);
}

export function wireApproval(root, state, rows, allBills) {
  const panel = $("[data-approval]", root);
  const refresh = () => setHTML($("[data-auto-summary]", panel), autoSummary(rows, allBills, ui.autonomy));
  wireAutonomy(panel, "panel", refresh);
  const syncPanel = () => {
    $$('input[name="panel-autonomy"]', panel).forEach((r) => (r.checked = r.value === ui.autonomy.mode));
    const input = $("[data-threshold]", panel);
    input.value = dollarsField(ui.autonomy.threshold_cents);
    input.disabled = ui.autonomy.mode !== "auto";
    refresh();
  };
  $("[data-approve]", panel).addEventListener("click", () => openApproveDialog(state, rows, syncPanel));
  $("[data-open-audit]", panel).addEventListener("click", () => openAuditDrawer());
}
