// Safe HTML templating and small DOM helpers. Every interpolated value is escaped
// unless it is wrapped with raw(); invoice and email text is untrusted content.
import { ICONS } from "/static/vendor/icons/icons.js";

class Raw {
  constructor(value) {
    this.value = value;
  }
  toString() {
    return this.value;
  }
}

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

export function raw(value) {
  return new Raw(value);
}

function renderValue(value) {
  if (value === null || value === undefined || value === false) return "";
  if (value instanceof Raw) return value.value;
  if (Array.isArray(value)) return value.map(renderValue).join("");
  return esc(value);
}

/** Tagged template: html`<td>${text}</td>` escapes text; nested html`` results pass through. */
export function html(strings, ...values) {
  let out = "";
  strings.forEach((chunk, i) => {
    out += chunk;
    if (i < values.length) out += renderValue(values[i]);
  });
  return new Raw(out);
}

export function setHTML(el, template) {
  el.innerHTML = template instanceof Raw ? template.value : esc(template);
  hydrateIcons(el);
}

/** Inline Lucide icon markup (vendored, no network). */
export function icon(name, cls = "icon") {
  const inner = ICONS[name];
  if (!inner) throw new Error(`unknown icon: ${name}`);
  return raw(`<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${inner}</svg>`);
}

/** Replace <span data-icon="name"> placeholders in static markup. */
export function hydrateIcons(root) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.outerHTML = icon(el.dataset.icon).value;
  });
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Click or Enter/Space on a focusable row-like element runs fn. */
export function onActivate(el, fn) {
  el.addEventListener("click", fn);
  el.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fn();
    }
  });
}

export function toast(message) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = "rounded-md bg-ink px-4 py-2 text-sm text-white shadow-lg";
  el.textContent = message;
  root.replaceChildren(el);
  setTimeout(() => el.remove(), 3200);
}
