# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Tempo
**Generated:** 2026-11-10 03:20:06 (ui-ux-pro-max), revised 2026-11-10 with the frontend-design pass
**Category:** Analytics Dashboard (a working app for an AP manager, not a marketing page)
**Design Dials:** Motion 3/10 (Subtle) | Density 8/10 (Dense / Dashboard)

The generated palette (navy foreground, amber CTA) and Fira Code/Fira Sans pairing were replaced:
the build directive (section 9.1) asks for a warm off-white page, near-black text, one restrained
accent, and IBM Plex Sans with tabular numerals. The landing-page sections (page pattern, CTA
placement, scroll-reveal motion) were deleted: Tempo is an app.

---

## Tempo app decisions

- **Numbers are the interface.** Every number is tabular (`font-variant-numeric: tabular-nums`, set on `html`), money is right-aligned in tables with thousands separators, and no number is invented: everything on screen comes from the API.
- **Money format.** Integer cents in, `$1,234` in tables (cents only under $100), `$48.8K` / `$1.48M` for KPI headlines with the exact amount (`$48,750.14`) in the tooltip. Percentages to two decimals for risk (`2.44%`), one decimal for annualized returns (`37.2%/yr`). Dates as `Nov 21`; long form `Nov 21, 2026` in detail panels.
- **Color means money.** Green only for money gained, red only for money lost or risk over the target (a breach bound above 5%, late payments, credit drawn). Everything else is ink on white.
- **One action color.** Cobalt `#2E4BB8` appears only on the button that commits (Approve, Accept and re-solve, Re-solve plan, Save) and on the keyboard focus ring. Selected states (nav, filters, segmented controls) use ink and the sunken surface, never the accent.
- **Status chips, not confidence scores.** Verified / Model verified / Accepted by reviewer are neutral outlined chips; Parser only is a quiet chip; Needs review is the only tinted (ochre) chip.
- **Show the source.** Every decision opens to its reason sentence, every option's value, and the invoice text with the evidence highlighted. Parser spans: blue tint with a solid underline. Model quotes: sand tint with a dashed underline. Both: blue tint plus a dashed outline. The rule style differs, so the distinction does not rely on color alone.
- **Risk meter.** One component reused on Overview, What-if, and (as a bar chart) Proof: measured rate as a bar, the one-sided 95% upper bound as a tick, the target as a dashed line. The fan chart's band is labeled pointwise; the any-day breach probability sits beside it.
- **Structure.** One flat white surface per section with a 1px border; sections are split by rules, never by cards inside cards. The KPI strip is one surface divided into cells. Radii encode level: chips 4px, controls 6px, panels 8px.
- **Wordmark.** Lowercase `tempo` in Plex Sans 600 next to a metronome mark (an ink rounded square with a white pendulum arm). No Ramp logo, wordmark, or yellow.
- **Copy.** Sentence case, plain verbs, no all-caps labels, no emoji, no arrows appended to buttons. Errors say what failed and offer Retry. Empty states say what would fill them.
- **Offline.** Chart.js, the IBM Plex Sans woff2 files, and the Lucide icons are vendored under `app/static/vendor/` by `scripts/vendor_assets.py`. The page makes no external requests (`scripts/screenshots.py` checks this).

---

## Global Rules

### Color Palette

| Role | Hex | Token (`@theme` in `app/static/css/input.css`) | Use |
|------|-----|--------------|-----|
| Page | `#F5F4F0` | `--color-page` | Warm off-white page background |
| Surface | `#FFFFFF` | `--color-surface` | Panels, tables, drawers |
| Sunken | `#F0EEE8` | `--color-sunken` | Selected nav, segmented control track, callouts |
| Line | `#E4E2DC` | `--color-line` | 1px borders and row rules |
| Line strong | `#CDCAC1` | `--color-line-strong` | Control borders, table header rule |
| Ink | `#1C1C1A` | `--color-ink` | Primary text (15.5:1 on page) |
| Ink 2 | `#55534D` | `--color-ink-2` | Secondary text (7.0:1 on page) |
| Ink 3 | `#6B6862` | `--color-ink-3` | Tertiary text, axis labels (5.05:1 on page) |
| Accent | `#2E4BB8` | `--color-accent` | Primary action buttons and focus ring only (white text 7.5:1) |
| Accent hover | `#243C96` | `--color-accent-hover` | Primary button hover |
| Gain | `#1D7A45` | `--color-gain` | Money gained (5.4:1 on white) |
| Risk | `#B3261E` | `--color-risk` | Money lost, risk over target (6.5:1 on white) |
| Review | `#875200` on `#FBF1DD` | `--color-review` | Needs review chip and banner (5.8:1) |
| Data | `#41618C` | `--color-data` | Tempo plan median line and band (18% alpha), parser evidence |
| Model | `#7A5A2A` on `#F3EBDD` | `--color-model` | Model-quote evidence |
| Before | `#8F8A7F` | charts.js `PALETTE.before` | Pay-on-due-date series, comparison bars |

All text pairs were checked at 4.5:1 or better.

### Typography

- **Family:** IBM Plex Sans (400, 500, 600), vendored woff2, `font-display: swap`. One family; hierarchy comes from size and weight.
- **Numerals:** tabular everywhere (verified in the browser: `1111` and `0000` render at equal width).
- **Scale (px):** 11 chips, 12 labels and meta, 13 tables and dense body, 14 body, 16 panel titles, 20 screen titles, 26 KPI values, 34 the breach headline.
- **Weights:** 400 body, 500 labels, buttons and emphasized cells, 600 titles and KPI values.
- **Line height:** 1.45 body, 1.6 for invoice and email text.

### Spacing

*Density: 8/10 (Dense / Dashboard).* Tailwind's 4px scale. Table cells 7px x 10px; panel headers 12px x 16px; page gutter 24px (16px under 1100px); 16px between sections.

### Elevation

Flat. Panels use a 1px border and no shadow. Only overlays lift: drawers (`-12px 0 32px rgb(28 28 26 / 0.10)`) and the approve dialog.

---

## Component Specs

- **Buttons:** 32px tall, 6px radius, 13px/500. Default is white with a strong line border; `.btn-primary` is the accent; `.btn-quiet` is borderless for tertiary actions. Busy state swaps the icon for a spinning loader and disables the button.
- **Segmented control (`.seg`):** sunken track, the pressed option is a white chip with a strong line ring. Used for view toggles (Tempo plan / Pay on due date / Compare, fitted vs true model, holdout vs all).
- **Filter toggles (`.filter`):** pill, count inside, pressed state is ink with white text. Filters combine.
- **Tables (`.tbl`):** sticky header, 13px body, right-aligned numbers, clickable rows are focusable (`tabindex=0`, Enter opens), sortable headers expose `aria-sort`.
- **Drawers:** right side, 640px (760px for bill detail and audit), backdrop, Esc closes, focus moves to Close and returns to the opener.
- **Dialog:** native `<dialog>` with `showModal()`, centered, 480px.
- **Loading / empty / error:** skeleton bars; an inbox icon with one sentence of direction; a red callout with the server's message and a Retry button.

---

## Motion

Subtle and only in answer to an action: drawers slide 24px and fade (200ms), the what-if fan animates from the current plan to the scenario (650ms ease-out), risk meters ease to their new width (400ms). No scroll reveals, no hover lifts. `prefers-reduced-motion: reduce` turns all of it off (CSS durations to 0.01ms; Chart.js animation disabled).

---

## Anti-Patterns (Do NOT Use)

- Dark OLED theme, neon green accent, monospace body or monospace data labels
- Ramp's logo, wordmark, or yellow
- Purple gradients, glassmorphism, decorative gradients
- Cards inside cards; one radius on everything
- Status dots without meaning; confidence percentages instead of status buckets
- Emojis as icons (Lucide SVG only)
- All-caps eyebrow labels; arrows appended to button text
- Accent color on anything that is not a primary action
- Green or red for anything other than money gained or at risk

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from Lucide, vendored
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms), no layout shift
- [ ] Text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation (2px accent outline)
- [ ] `prefers-reduced-motion` respected
- [ ] Usable at 1024px and 1440px (screenshots in `docs/screenshots/`)
- [ ] Every number tabular, money right-aligned, exact amount in tooltips
- [ ] Every screen has loading, empty, and error states
- [ ] Zero external network requests (`scripts/screenshots.py` reports them)
