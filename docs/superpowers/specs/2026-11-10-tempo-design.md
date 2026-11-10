# Tempo design (approved spec)

Status: approved. Source of truth is `docs/BUILD_DIRECTIVE.md`; the team opted out of brainstorming questions. This file restates the design in build order and answers every open question the directive leaves to the lead engineer (see "Q / A (from directive)").

## 1. What Tempo is
Tempo decides the best day and rail to pay every open bill, so a company captures early-payment discounts and card rewards while keeping the probability that end-of-day cash drops below its safety buffer under a target (default 5%), certified on fresh forecast scenarios. Target Balance moves cash to fit the bills; Tempo moves the bills to fit the cash.

## 2. Architecture
```
data/demo (seeded synthetic company)          data/cache (local-model outputs, committed)
        |                                               |
        v                                               v
tempo.extract: regex parser ──► reconcile ◄── tempo.llm provider (Ollama | Cached | Anthropic-off)
        |                          |
        |                  Needs review queue
        v
tempo.forecast: pooled lognormal + truncation + common factor ──► scenario inflows (seeds A/B/C)
        v
tempo.optimize: options per bill ─► reduced SAA MILP (scipy milp / HiGHS) ─► certification loop on B
        |            ├─ baselines (pay_on_due, weekly_run, greedy_discount, deterministic_p50)
        |            ├─ evaluation on seed C, ablations, cash value (forward difference)
        |            └─ templated explanations with binding reason
        v
tempo.agent: negotiation pricing + verified offer, number guard, reply parsing
tempo.audit (hash chain) ─ tempo.ramp.payloads (preview only, never sent)
        v
scripts/precompute ─► data/precomputed (committed, keyed by input hash)
        v
app (FastAPI routes only) ─► static one-page UI (vanilla ES modules, Tailwind compiled, vendored assets)
```
`tempo/` never imports FastAPI. `app/main.py` holds routes only; `app/schemas.py` holds Pydantic response models; `app/state.py` loads precomputed results.

## 3. Build order
P0 skeleton and deploy files; P1 data, parser, providers, reconciliation, extraction eval; P2 forecast; P3 options, MILP, certification, baselines, evaluation, cash value, explanations, RESULTS.md; P4 API and UI; P5 negotiation, number guard, autonomy, audit, payload preview, security review; P6 docs, e2e, demo video. Gates per directive section 12.

## 4. Q / A (from directive)
Each answer is also logged as a ruling in `docs/DECISIONS.md`.

**Q: What is "today"?** A fixed `AS_OF = 2026-11-10` in the generated dataset, never the system clock, so the plan hash is reproducible. Horizon: 91 days (day 0 = Nov 10, 2026 through Feb 8, 2027).

**Q: "~200 open bills over 13 weeks" when most real invoices arrive later?** The dataset holds bills issued from about 25 days before `AS_OF` to about 55 days after it. Future-dated bills are recurring or PO-backed invoices already entered in Bill Pay (ASSUMPTION, stated in the UI and README). Bills whose due date falls after the horizon are excluded from the run. No bill is overdue at `AS_OF`.

**Q: Which payment option is the baseline?** `BANK_DUE`: arrives on the due date. Every option's value uses one formula, `v = (A_base - c) + rewards + YIELD_ON_CASH * c * (t_base - t) / 365 - fees`, where `A_base` is the full amount and `t_base` the `BANK_DUE` cash-out day. `BANK_DUE` therefore has value `-fee` (zero from Ramp Checking).

**Q: Does every vendor accept RTP?** No. Each vendor has an `rtp_eligible` flag (ASSUMPTION: about 70% of receiving banks). Non-RTP vendors are paid by standard ACH sent 3 business days before arrival; the cash leaves on the send date. US federal holidays are not business days.

**Q: Card cash-out after the horizon ends?** Counted on the last horizon day for constraint purposes (conservative), shown with its true statement date in the UI.

**Q: How does the common factor interact with truncation?** It shifts the log-mean: in scenario s every customer's log days-to-pay mean becomes `mu_i + SIGMA_MACRO * Z_s` (exactly "multiply every delay by exp(SIGMA_MACRO * Z_s)"), then outstanding receivables are sampled from that lognormal conditional on days-to-pay > elapsed days, by inverse CDF. Truncating after scaling keeps every sampled payment in the future.

**Q: What is the P50 path for `deterministic_p50` and `greedy_discount`?** The pointwise median of cumulative inflows over the seed-A scenarios.

**Q: Which days carry the chance constraint?** Day 0 and every day on which any option or fixed outflow can occur. Between those days the end-of-day balance only rises, so the minimum is on a checked day (proof in `docs/MATH.md`).

**Q: Footer conflicts are across blocks, not "in one block".** The regex candidate set is taken over the authoritative source (all invoice blocks, or the overriding email). Two or more distinct values there mean `ambiguous_document`. This is a strict superset of the table's single-block rule.

**Q: What does LATE look like?** Paid 15 days after the due date (ASSUMPTION), plus the vendor's late fee (one month's charge or the flat fee, or a default if the invoice states none) and a relationship penalty that only enters the objective (ASSUMPTION: 2% of the amount). Flagged loudly when chosen.

**Q: Backstop credit cost?** `CREDIT_COST = 0.50` per dollar drawn (ASSUMPTION; deliberately punitive so credit only appears when the chance constraint is otherwise infeasible). Any draw becomes a headline warning.

**Q: How are certification seeds chosen?** `SEED_A = seed`, `SEED_B = seed + 1_000_003`, `SEED_C = seed + 2_000_029`, asserted distinct in a test.

**Q: Which "early option" does the binding-reason check use?** The best-value discount-taking option for that bill (`BANK_EARLY`, `CARD_EARLY`, or `FINANCE_EARLY`).

**Q: Annualized return for card options?** Not shown as a rate (card value is cashback plus float, not a discount); the table shows cashback and float days instead.

**Q: Subagent policy?** Superpowers subagent-driven development is used for isolated modules (parser, UI screens) and for every review; the tightly coupled math core (generator, forecast, optimizer, evaluation) is written by the lead session for coherence, then reviewed by a fresh `python-reviewer` subagent (spec, then code quality) as the directive requires.

**Q: Tailwind version?** The setup script installed Tailwind v4 CLI (`@tailwindcss/cli`). Build with `./node_modules/.bin/tailwindcss` per the directive; v4 uses CSS-first config in `app/static/css/input.css`.
