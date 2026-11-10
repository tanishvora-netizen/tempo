// Loading, empty, error, and "next build" states shared by every screen.
import { html, icon, setHTML } from "./dom.js";

export function loadingBlock(label = "Loading", rows = 4) {
  return html`<div class="flex flex-col gap-2 p-4" role="status" aria-live="polite">
    <span class="sr-only">${label}</span>
    ${Array.from({ length: rows }, (_, i) => html`<div class="skeleton h-4" style="width:${92 - i * 9}%"></div>`)}
  </div>`;
}

export function loadingScreen(label = "Loading") {
  return html`<div class="flex flex-col gap-4" role="status" aria-live="polite">
    <span class="sr-only">${label}</span>
    <div class="skeleton h-7 w-64"></div>
    <div class="skeleton h-24 w-full"></div>
    <div class="skeleton h-80 w-full"></div>
  </div>`;
}

export function emptyBlock(title, body) {
  return html`<div class="flex flex-col items-center gap-1 px-6 py-10 text-center">
    ${icon("inbox", "icon h-6 w-6 text-ink-3")}
    <p class="mt-1 font-medium">${title}</p>
    ${body ? html`<p class="max-w-[52ch] text-sm text-ink-2">${body}</p>` : ""}
  </div>`;
}

/** Error with a retry button (data-retry). */
export function errorBlock(err, what = "this data") {
  return html`<div class="callout callout-risk m-4 items-start" role="alert">
    ${icon("circle-x", "icon mt-0.5")}
    <div class="flex flex-1 flex-col gap-2">
      <p><span class="font-medium">Could not load ${what}.</span> ${err?.message ?? "Unknown error."}</p>
      <div><button type="button" class="btn btn-sm" data-retry>${icon("refresh-cw")}Retry</button></div>
    </div>
  </div>`;
}

/** Render async content into el with loading and error states; retry re-runs. */
export async function withStates(el, { load, render, what, loading }) {
  setHTML(el, loading ?? loadingBlock(`Loading ${what}`));
  try {
    const data = await load();
    render(data);
  } catch (err) {
    console.error(err);
    setHTML(el, errorBlock(err, what));
    el.querySelector("[data-retry]")?.addEventListener("click", () => withStates(el, { load, render, what, loading }));
  }
}
