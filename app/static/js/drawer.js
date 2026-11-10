// Generic right-side drawer: backdrop, Esc to close, focus moved in and restored on close.
import { $, html, icon, setHTML } from "./dom.js";

let active = null;

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, [tabindex]:not([tabindex="-1"])';

function trapFocus(event, panel) {
  if (event.key !== "Tab") return;
  const items = Array.from(panel.querySelectorAll(FOCUSABLE)).filter((el) => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function closeDrawer() {
  if (!active) return;
  const { root, opener, onClose, keyHandler } = active;
  document.removeEventListener("keydown", keyHandler);
  root.replaceChildren();
  active = null;
  onClose?.();
  if (opener && document.contains(opener)) opener.focus();
}

/** Open a drawer and return its body element for the caller to fill. */
export function openDrawer({ id, title, subtitle = "", wide = false, onClose }) {
  closeDrawer();
  const root = $("#drawer-root");
  const opener = document.activeElement;
  setHTML(
    root,
    html`<div class="drawer-backdrop" data-close></div>
      <section class="drawer ${wide ? "drawer-wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="drawer-title" data-drawer="${id}">
        <header class="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div class="min-w-0">
            <h2 id="drawer-title" class="text-lg font-semibold">${title}</h2>
            ${subtitle ? html`<p class="mt-0.5 text-sm text-ink-2">${subtitle}</p>` : ""}
          </div>
          <button type="button" class="btn btn-quiet btn-icon" data-close aria-label="Close">${icon("x")}</button>
        </header>
        <div class="drawer-body flex-1 overflow-y-auto px-5 py-4"></div>
      </section>`,
  );
  const panel = root.querySelector(".drawer");
  const keyHandler = (event) => {
    if (event.key === "Escape") closeDrawer();
    else trapFocus(event, panel);
  };
  document.addEventListener("keydown", keyHandler);
  root.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeDrawer));
  active = { root, opener, onClose, keyHandler };
  panel.querySelector("[data-close]").focus();
  return panel.querySelector(".drawer-body");
}
