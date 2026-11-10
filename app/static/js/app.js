// Entry point: header, left navigation, hash router (#/screen?param=value), drawer launchers.
import { $, $$, html, hydrateIcons, icon, setHTML } from "./dom.js";
import { weekdayDate } from "./format.js";
import { loadingScreen, errorBlock } from "./states.js";
import { invalidate, loadState, STATE_CHANGED } from "./store.js";
import { openAuditDrawer, openNegotiateDrawer } from "./drawers.js";
import * as overview from "./overview.js";
import * as run from "./run.js";
import * as review from "./review.js";
import * as whatif from "./whatif.js";
import * as proof from "./proof.js";

const SCREENS = [
  { id: "overview", label: "Overview", icon: "layout-dashboard", view: overview },
  { id: "run", label: "Payment run", icon: "list-checks", view: run },
  { id: "review", label: "Needs review", icon: "inbox", view: review },
  { id: "whatif", label: "What-if", icon: "sliders-horizontal", view: whatif },
  { id: "proof", label: "Proof", icon: "shield-check", view: proof },
];

let cleanup = null;
let firstRender = true;

function parseRoute() {
  const hash = location.hash.startsWith("#/") ? location.hash.slice(2) : "overview";
  const [id, query = ""] = hash.split("?");
  const screen = SCREENS.find((s) => s.id === id) ?? SCREENS[0];
  return { screen, params: Object.fromEntries(new URLSearchParams(query)) };
}

function renderNav(activeId, reviewCount) {
  setHTML(
    $("#nav"),
    html`${SCREENS.map(
      (s) => html`<li><a class="nav-item" href="#/${s.id}" ${s.id === activeId ? html`aria-current="page"` : ""}>
        ${icon(s.icon)}<span>${s.label}</span>
        ${s.id === "review" && reviewCount ? html`<span class="nav-badge num" aria-label="${reviewCount} bills need review">${reviewCount}</span>` : ""}
      </a></li>`,
    )}`,
  );
}

function renderHeader(state) {
  const { company, provider, provenance } = state;
  setHTML(
    $("#header"),
    html`<div class="mx-auto flex max-w-[1280px] items-center justify-between gap-4 px-6 py-3 max-[1100px]:px-4">
      <div class="min-w-0">
        <p class="truncate text-base font-semibold">${company.name}</p>
        <p class="text-xs text-ink-2">Plan as of ${weekdayDate(company.as_of)} (synthetic)</p>
      </div>
      <span class="chip max-w-[46%] truncate" title="AI provider: ${provider.name}, model: ${provider.model}">
        ${icon("lock")}<span class="truncate">AI: ${provider.label}</span>
      </span>
    </div>`,
  );
  if (!provenance.hash_ok) {
    setHTML(
      $("#banner"),
      html`<div class="border-b border-[#ecd9b0] bg-review-tint">
        <div class="mx-auto flex max-w-[1280px] items-start gap-2 px-6 py-2 text-sm text-review max-[1100px]:px-4" role="status">
          ${icon("history", "icon mt-0.5")}
          <p><span class="font-medium">Results from build ${provenance.input_hash}.</span>
          The data or assumptions changed since these results were computed (current inputs hash ${provenance.current_hash}). Every number shown comes from that committed build.</p>
        </div>
      </div>`,
    );
  }
}

function renderHeaderError(err) {
  setHTML($("#header"), html`<div class="px-6 py-3">${errorBlock(err, "the company and plan")}</div>`);
  $("#header [data-retry]")?.addEventListener("click", boot);
}

async function route() {
  if (location.hash && !location.hash.startsWith("#/")) return; // in-page anchors such as #main
  const { screen, params } = parseRoute();
  cleanup?.();
  cleanup = null;
  const main = $("#main");
  setHTML(main, loadingScreen(`Loading ${screen.label}`));
  document.title = `${screen.label}: Tempo`;
  loadState()
    .then((state) => renderNav(screen.id, state.review_count))
    .catch(() => renderNav(screen.id, 0));
  if (!firstRender) main.focus({ preventScroll: true });
  firstRender = false;
  window.scrollTo(0, 0);
  try {
    cleanup = (await screen.view.render(main, params)) ?? null;
  } catch (err) {
    console.error(err);
    setHTML(main, errorBlock(err, screen.label));
    main.querySelector("[data-retry]")?.addEventListener("click", route);
  }
}

function wireLaunchers() {
  $$("[data-open]").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.open === "negotiate") openNegotiateDrawer();
      if (el.dataset.open === "audit") openAuditDrawer();
    });
  });
  $('a[href="#main"]')?.addEventListener("click", (event) => {
    event.preventDefault();
    $("#main").focus();
  });
}

async function boot() {
  try {
    renderHeader(await loadState());
  } catch (err) {
    renderHeaderError(err);
  }
}

/** Refetch /api/state and redraw the nav so the Needs review badge reflects accepted items. */
function refreshNav() {
  invalidate("state");
  const { screen } = parseRoute();
  loadState()
    .then((state) => renderNav(screen.id, state.review_count))
    .catch((err) => console.error(err));
}

hydrateIcons(document.body);
wireLaunchers();
window.addEventListener("hashchange", route);
window.addEventListener(STATE_CHANGED, refreshNav);
boot();
route();
