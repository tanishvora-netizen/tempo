// Entry point: header, left navigation, hash router (#/screen?param=value), drawer launchers.
import { $, $$, html, hydrateIcons, icon, setHTML } from "./dom.js";
import { weekdayDate } from "./format.js";
import { loadingScreen, errorBlock } from "./states.js";
import { invalidate, loadBills, loadPresets, loadState, STATE_CHANGED } from "./store.js";
import { getAudit } from "./api.js";
import { renderSidebar } from "./sidebar.js";
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

/** What the sidebar shows; each part is optional, so a failed call only hides its badge or block. */
async function sidebarData() {
  const [state, presets, bills, audit] = await Promise.all([
    loadState().catch(() => null),
    loadPresets().catch(() => null),
    loadBills().catch(() => null),
    getAudit().catch(() => null),
  ]);
  return { state, presets, bills, audit };
}

function renderNav(activeId) {
  sidebarData()
    .then((data) => {
      renderSidebar(SCREENS, activeId, data);
      wireLaunchers();
    })
    .catch((err) => console.error(err));
}

function renderHeader(state) {
  const { company, provenance } = state;
  // The sidebar carries the company, the AI provider, and "Synthetic data", so the header keeps only the date.
  setHTML(
    $("#header"),
    html`<div class="mx-auto flex max-w-[1280px] items-center gap-4 px-6 py-3 max-[1100px]:px-4">
      <p class="text-sm font-medium text-ink">Plan as of ${weekdayDate(company.as_of)}</p>
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
    .then(() => renderNav(screen.id))
    .catch(() => renderNav(screen.id));
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
    if (el.dataset.wired) return;
    el.dataset.wired = "1";
    el.addEventListener("click", () => {
      if (el.dataset.open === "negotiate") openNegotiateDrawer();
      if (el.dataset.open === "audit") openAuditDrawer();
    });
  });
  const skip = $('a[href="#main"]');
  if (!skip || skip.dataset.wired) return;
  skip.dataset.wired = "1";
  skip.addEventListener("click", (event) => {
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
  invalidate("state", "bills");
  const { screen } = parseRoute();
  loadState()
    .then(() => renderNav(screen.id))
    .catch((err) => console.error(err));
}

hydrateIcons(document.body);
wireLaunchers();
window.addEventListener("hashchange", route);
window.addEventListener(STATE_CHANGED, refreshNav);
boot();
route();
