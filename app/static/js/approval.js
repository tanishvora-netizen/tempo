// Approve this week's run: the autonomy setting on Overview, then a small dialog for the
// approver's name. Approval writes a hash-chained audit entry; nothing is sent to Ramp.
import { $, $$, html, icon, setHTML } from "./dom.js";
import { count, dollarsField, money, moneyExact, parseDollars } from "./format.js";
import { approvePlan } from "./api.js";
import { invalidate, STATE_CHANGED, ui } from "./store.js";
import { openAuditDrawer } from "./drawers.js";

const VERIFIED_CHIPS = new Set(["Verified", "Model verified", "Accepted by reviewer"]);
const DOLLARS_MAX = 2_000_000;
const APPROVER_PATTERN = /^[\w .,'@-]{1,80}$/;

function currentAutonomy(state) {
  if (!ui.autonomy) ui.autonomy = { ...state.autonomy };
  return ui.autonomy;
}

function qualifying(rows, thresholdCents) {
  return rows.filter((b) => VERIFIED_CHIPS.has(b.chip) && b.amount_cents < thresholdCents);
}

function autoSummary(rows, autonomy) {
  if (autonomy.mode !== "auto") return html`Every bill waits for your approval.`;
  const q = qualifying(rows, autonomy.threshold_cents);
  const total = q.reduce((s, b) => s + b.cash_out_cents, 0);
  return html`<span class="num font-medium text-ink">${count(q.length)}</span> of this week's ${count(rows.length)} bills
    (<span class="num" title="${moneyExact(total)}">${money(total)}</span>) would be scheduled without asking. The rest wait for approval.`;
}

function autonomyFields(autonomy, idPrefix) {
  const dollars = dollarsField(autonomy.threshold_cents);
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
          <input type="text" inputmode="numeric" value="${dollars}" class="field w-28 num"
            aria-label="Auto-schedule threshold in dollars" data-threshold ${autonomy.mode === "auto" ? "" : html`disabled`}>
        </span>
        <span class="text-xs text-ink-2">Verified means the parser and the model agree, or a reviewer accepted the terms.</span>
      </span>
    </label>
    <p class="hidden text-xs risk" data-threshold-error role="alert"></p>
  </fieldset>`;
}

export function approvalPanel(state, rows) {
  const autonomy = currentAutonomy(state);
  return html`<aside class="flex w-[300px] flex-none flex-col gap-4 border-l border-line p-4 max-[1180px]:grid max-[1180px]:w-full max-[1180px]:grid-cols-2 max-[1180px]:gap-x-8 max-[1180px]:border-l-0 max-[1180px]:border-t" aria-labelledby="approve-title" data-approval>
    <div>
      <h3 id="approve-title" class="section-title">Approve and schedule</h3>
      <p class="mt-0.5 text-xs text-ink-2">Approval writes an audit entry and builds the Ramp bill updates. Nothing is sent.</p>
    </div>
    ${autonomyFields(autonomy, "panel")}
    <p class="text-xs text-ink-2" data-auto-summary aria-live="polite">${autoSummary(rows, autonomy)}</p>
    <div class="mt-auto flex flex-col gap-2">
      <button type="button" class="btn btn-primary h-9 justify-center" data-approve>${icon("check")}Approve this week's run</button>
      <button type="button" class="btn btn-quiet btn-sm justify-center" data-open-audit>${icon("scroll-text")}View audit log</button>
    </div>
  </aside>`;
}

function readThreshold(input, errorEl) {
  const cents = parseDollars(input.value);
  const valid = cents !== null && cents >= 100 && cents <= DOLLARS_MAX * 100;
  errorEl.classList.toggle("hidden", valid);
  errorEl.textContent = valid ? "" : `Enter a dollar amount between $1 and ${money(DOLLARS_MAX * 100)}.`;
  return valid ? cents : null;
}

/** Keep ui.autonomy in sync with one set of autonomy fields; onChange runs after each valid change. */
function wireAutonomy(root, idPrefix, onChange) {
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

function rtpNotice(rows) {
  const k = rows.filter((b) => b.rtp_dependent).length;
  if (!k) return "";
  return html`<p class="callout callout-review items-start">${icon("zap", "icon mt-0.5 flex-none")}<span>
    <span class="num font-medium">${count(k)}</span> ${k === 1 ? "bill relies" : "bills rely"} on RTP from Ramp Checking; as standard ACH ${k === 1 ? "it" : "they"} would miss ${k === 1 ? "its date" : "their dates"}.</span></p>`;
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

function openApproveDialog(state, rows, onApproved) {
  const dialog = document.createElement("dialog");
  dialog.className = "modal m-auto w-[min(480px,calc(100vw-32px))] rounded-lg border border-line-strong bg-surface p-0 text-ink shadow-2xl";
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
}

export function wireApproval(root, state, rows) {
  const panel = $("[data-approval]", root);
  const refresh = () => setHTML($("[data-auto-summary]", panel), autoSummary(rows, ui.autonomy));
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
