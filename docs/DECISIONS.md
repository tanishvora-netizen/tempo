# Decisions

Format for quick rulings: `Ruling: <what> | <why> | <cost if wrong>`. Longer ADR-style entries (context, decision, alternatives, tradeoff, with more time) are added in P6 under "Architecture decisions".

## Rulings log

- Ruling: The repo had no Round 1 code or README, so nothing was folded in | `tanishvora-netizen/tempo` was created fresh on Nov 10, 2026 with only the setup-script output | Low: if Round 1 material exists elsewhere, the humans can link it from the README.
- Ruling: `AS_OF = 2026-11-10` is fixed in the dataset, never the system clock | the plan hash must be reproducible (rule 6) | Low.
- Ruling: Bills issued up to ~55 days after `AS_OF` are treated as recurring or PO-backed invoices already in Bill Pay | a 13-week plan needs bills across the horizon | Medium: a judge may ask why future invoices have text; the README says so plainly.
- Ruling: Same-day ACH ($10) and wires ($15) are excluded from the option set | from Ramp Checking, RTP is free and instant, so both are dominated; from an external bank they cost more than any float they buy on a typical bill | Low.
- Ruling: Per-vendor `rtp_eligible` flag (~70% of vendors) | not every receiving bank is on RTP; makes the rail choice real | Low.
- Ruling: Card cash-outs past the horizon count on the last horizon day in the constraint | conservative; avoids an end-of-horizon cliff that would make late-horizon card payments look free | Low.
- Ruling: Common factor applied as a log-mean shift before truncation | keeps truncated samples in the future and is exactly "multiply every delay by exp(SIGMA_MACRO * Z)" | Low.
- Ruling: `ambiguous_document` triggers on 2+ distinct regex values across the authoritative source, not only within one block | the `footer_conflict` hard case spans blocks | Low.
- Ruling: `CREDIT_COST = 0.50` per dollar | must exceed any per-dollar value the plan could earn by reusing headroom across several discount windows | Low.
- Ruling: Subagents build isolated modules (parser, UI) and run every review; the lead session writes the math core | coherence across generator, forecast, optimizer, and evaluation matters more than parallelism there | Medium: slower core build; mitigated by background subagents on independent modules.
- Ruling: `/ecc:plan` and `/orch-build-mvp` not used | both block on human approval (directive section 4) | None.
- Ruling: find-skills results reviewed; nothing installed tonight | everything reputable in `tooling/find-skills.txt` overlaps what is installed (ECC already ships `fastapi-patterns`, `e2e-testing`, `browser-qa`; Superpowers covers TDD); `anthropics/skills@webapp-testing` (201.6K installs) overlaps ECC `e2e-testing` plus our Playwright setup | Low: listed under Human actions as optional.
- Ruling: Council C1 rulings (all 13 accepted, one in part) are recorded in `docs/council/C1.md` | three FIX verdicts, no BLOCK | see that file.
- Ruling: Sixth policy `greedy_p05` (due-date-order greedy that takes an option when its return beats the cost of cash and the pointwise P5 balance path stays above the buffer) | the strongest simple alternative a judge would propose (C1, judge) | Low.
- Ruling: Certification on seed B uses a Bonferroni-adjusted one-sided Wilson bound, z = 2.394 (0.05 split over the 6 possible ladder steps); seed C is reported with z = 1.645 | the ladder tests several plans, so an uncorrected test passes a 5% plan about 27% of the time (C1, quant) | Medium: costs some value because certification is stricter.
- Ruling: Certification fallback is N = 1,000 with K = 5, not K = 20 | K/N = 2% is looser than K = 0 at N = 200 (C1, quant) | Low.
- Ruling: Discount-window ACH payments use the 4-business-day upper bound; due-date ACH uses 3 | missing a discount window forfeits the discount, while one day late on a due date rarely costs anything | Low.
- Ruling: Starting cash is calibrated on a separate seed D, never on the reported seed C | the calibration must not reuse the numbers we report (C1, quant) | Low.
- Ruling: Drop the "only 10% of AP teams fully automate discount capture" claim | the research pass read the State of ePayables 2025 report and found no such figure (docs/SOURCES.md, claim 2) | None: never stated.
- Ruling: Say "Ramp's bill and vendor objects have no field for discount terms (vendors and purchase orders carry only `net_payment_terms`)" | the vendor object also has `net_payment_terms`, so the directive's "only on purchase orders" is wrong (docs/ramp_api_snapshot.md) | Low.
- Ruling: The payload preview uses Ramp's request enum (`ACH`, `CARD`, ...) and notes RTP as "chosen in Ramp when funded from Ramp Checking" | `RTP` and `EARLY_PAYMENT_DISCOUNT` are response-only values | Low.
- Ruling: Revenue raised from $3.4M to $4.0M per month in the generator | the first draft's company spent more than it billed (outflows ~$3.7M/month), so even paying on due dates breached in 83% of scenarios; a mid-market manufacturer runs at a positive margin (now ~8%) | Low.
- Ruling: Discount terms go mostly to materials suppliers (score = materials + uniform noise, top scores take the discount terms) | with terms assigned at random, freight carriers and staffing agencies offered 2/10 while large steel and resin suppliers did not, and only 41% of AP dollars carried discounts (now 74%). Disclosure: this change was made after a first exploration showed little tension (greedy 3.2% vs pay-on-due 1.8% breach); it changes realism, not the evaluation | Medium: a reviewer could call it tuning; it is disclosed here and in the README.
- Ruling (pre-registered before running): starting-cash calibration sweeps exactly six values, $3.0M to $4.0M in $0.2M steps, on seed D. Pick the first value meeting the directive's three thresholds (greedy_discount >= 15%, pay_on_due <= 2%, Tempo certified with >= 60% of greedy's value). If none does, pick the first value with pay_on_due <= 2%, greedy_discount above EPSILON (unsafe), and Tempo certified with >= 60% of greedy's value, and disclose the miss. SIGMA_MACRO, customer behavior, and every other parameter stay untouched | exploration showed the common factor (SIGMA_MACRO = 0.15) doubles the forecast spread, so reaching 15% would require narrowing the forecast, which would make the risk bound less honest | Medium: the demo's greedy breach rate is less dramatic than the directive's target.

## Architecture decisions

Each entry: context, decision, alternatives, tradeoff, with more time. Measured numbers come from `docs/RESULTS.md` and `data/precomputed/benchmark.json` (`scripts/benchmark_formulation.py`).

### ADR-1. A MILP, not a greedy rule
- **Context.** Every bill's date and rail interact through one shared cash balance: paying one bill early leaves less room for the next, and payroll days are hard walls.
- **Decision.** Solve all ~210 bills jointly as a mixed-integer program (`scipy.optimize.milp`, HiGHS).
- **Alternatives.** Greedy in due-date order on the median forecast (`greedy_discount`); greedy that checks the P5 path and the cost of cash (`greedy_p05`, the "smart spreadsheet" the C1 judge asked for).
- **Tradeoff.** A solver dependency and a formulation to explain. In return, RESULTS.md shows every greedy variant breaches the 5% limit on fresh scenarios, because order-dependent choices can't see the joint risk. Tempo stays under it with most of the value.
- **With more time.** Warm-start the re-solves from the previous plan.

### ADR-2. A few candidate options per bill, not every day
- **Context.** A bill can be paid on any of ~90 days by several rails.
- **Decision.** Each bill gets 2 to 6 economically distinct options: on the due date, at the discount deadline, card, card at the deadline, Flex-style financing (off by default), and late.
- **Alternatives.** A variable per bill per day (about 19,000 binaries).
- **Tradeoff.** Paying on any day strictly between the deadline and the due date is dominated: it forfeits the discount and loses yield. So the candidate set loses nothing under this value model, and the problem shrinks to ~600 binaries.
- **With more time.** Partial payments and split rails.

### ADR-3. Sample-average approximation with an exact row reduction
- **Context.** "Balance above the buffer every day in 95% of scenarios" is a joint chance constraint.
- **Decision.** SAA over N = 200 scenarios with binary protection variables, made small by three exact reductions (MATH.md section 4):
  - check only days where an outflow can occur;
  - a quantile cut;
  - drop dominated rows, with the tightest big-M (q - R).
  We then never trust z: breaches are recounted from the payments in integer cents.
- **Measured** (demo data, K = 4, same machine, same caps):

  | Formulation | Rows | Nonzeros | Solve time | Status |
  |---|---:|---:|---:|---|
  | Every scenario on every check day | 12,538 | 38,313 | 2.9 s | optimal |
  | Reduced (quantile cut and tight big-M) | 630 | 2,341 | 0.64 s | optimal |

  Both reach the same objective within the 0.01% gap. Peak memory is ~250 MB in both cases, dominated by the Python scientific stack. Both builds already use check days and the cumulative-outflow recurrence. A fully dense formulation (every option in every scenario row, all 91 days) would have about 18,400 rows and millions of nonzeros; the directive's benchmark of that design hit a 60 s limit.
- **Alternatives.**
  - Scenario decomposition.
  - Robust (worst-case) constraints. Too conservative: the per-day worst case keeps far less value (see ADR-6).
- **With more time.** Luedtke's mixing inequalities, and `highspy` for warm starts and threads.

### ADR-4. Certify out of sample, and start K below EPSILON * N
- **Context.** Protecting 190 of 200 sampled scenarios (K = 10) does not give a 5% breach rate on new scenarios. SAA is optimistic.
- **Decision.**
  - Three seeds: A optimizes, B certifies, C reports. A fourth seed, D, is used only for the starting-cash calibration.
  - Walk K = 4, 3, 2, 1, 0 (then N = 1,000, K = 5), stopping at the first plan whose seed-B one-sided Wilson bound is at most 5%.
  - The bound uses a Bonferroni z = 2.394 because up to six plans are tested (C1, quant). Seed C is reported as it comes out.
- **Tradeoff.** The ladder starts at K = 4 (2%), so certification usually passes on the first rung with margin and leaves some value on the table (C2, Ramp engineer). Starting nearer K = 10 with finer steps would capture more value; with the Bonferroni correction it would remain safe.
- **Honest limit.** B and C are drawn from the fitted forecast, so certification covers sampling error, not model error. RESULTS.md therefore adds a column with every policy re-run on the generator's true payment model.

### ADR-5. A backstop credit variable
- **Decision.** A nondecreasing cumulative credit G[t] on the cash side of every constraint, priced at 0.50 per dollar. The model can never be infeasible.
- **Why.** An infeasible solve is a blank screen in a demo and a useless answer for a controller. A priced backstop turns impossibility into a statement: "you need $X of financing by <date>". Any nonzero draw becomes a headline warning.
- **Alternatives.** Soft constraints per scenario (many more variables), or reporting infeasibility.

### ADR-6. A joint chance constraint, not per-day ones
- **Evidence.** RESULTS.md ablation:
  - A per-day 5% constraint looks safe each day but breaches above 5% over the horizon, because the risk adds up across days.
  - A per-day worst case (Bonferroni at 0.05/91, which at 1,000 scenarios is the pointwise minimum) is safe but gives up a large share of the value.
  - The joint constraint is both safe and valuable.

### ADR-7. `scipy.optimize.milp` instead of `highspy`
- **Decision.** scipy's wrapper, for readability (one call, standard sparse matrices), with time and node limits and a 0.01% gap.
- **With more time.** `highspy` directly: warm starts between what-ifs, threads, and incremental row edits.

### ADR-8. Marginal value of cash by forward difference, not duals
- **Context.** A MILP has no meaningful duals. Fixing the binaries and reading LP duals gives zero on every buffer row.
- **Decision.** Re-solve with +$25,000 starting cash at the certified K and N. lambda = change in objective per dollar, annualized. Cost of cash = yield + lambda. The step is upward because a downward step can switch the backstop credit on and inflate lambda. A "credit-bound" label appears if either solve draws credit.

### ADR-9. A censored, partially pooled lognormal with a common factor
- **Decision.**
  - Fit each customer's days-to-pay as a lognormal by maximum likelihood, treating open invoices as right-censored. Paid-only fits are biased early (C2, quant).
  - Pool means and within-customer spreads with KAPPA = 5.
  - A scenario-wide common factor makes all customers pay faster or slower together. Without it the fan is too narrow and the risk bound too optimistic (tested).
- **With more time.** A survival model (Weibull AFT or Cox) with customer covariates, and a fitted common factor instead of the assumed SIGMA_MACRO = 0.15.

### ADR-10. The model never computes or changes a number
- **Decision.** The local model locates and quotes. Code checks that each quote is verbatim in the document and re-parses it with the deterministic parser, and the model's value must equal the re-parse. The deterministic reconciliation table then compares parser and model.
- Prose the model writes (offer emails) uses placeholders only. A number guard rejects any digit, number word, or unknown placeholder, fills the values from code, and checks every number in the final text. Any failure falls back to a fixed template.
- **Why.** The plan moves money. A hallucinated "2/10" that becomes a real early payment costs real cash, so every number must trace to the document or the solver.

### ADR-11. Status buckets, not confidence scores
- **Decision.** The UI shows Verified, Regex only, Model verified, Accepted by reviewer, and Needs review, each with a reason. The proof panel reports each bucket's measured accuracy and n.
- **Why.** Ramp's agent playbook routes uncertainty to a review queue. A raw 0.83 confidence invites people to pick their own thresholds.

### ADR-12. A local open-weights model; hosted models only by explicit opt-in
- **Decision.** qwen3:8b via Ollama on 127.0.0.1, with structured outputs at temperature 0. The hosted adapter refuses unless `TEMPO_ALLOW_EXTERNAL_LLM=1` and a key are both set.
- **Why.** The event may not allow external APIs, and a pitch point follows: invoice and cash data never leave the company.
- **Measured.** A flat schema (one quote per field group) beat nested per-field objects on the 8B model. The nested version returned all nulls on a plain "Net 60" invoice.

### ADR-13. Caching and offline mode
- **Decision.** Model outputs are cached by sha256(prompt version | schema version | document) and committed, including failures, so the host replays exactly what the local run saw.
- Solver results are precomputed and committed under an input hash. The host never solves at startup, and a test fails if the committed hash is stale.
- **Tradeoff.** The hosted demo cannot extract new invoices live; the UI says so.

### ADR-14. Integer cents
Storage and APIs use integer minor units, as Ramp does. Floats appear only inside the solver and charts. Plan hashes are float-free.

### ADR-15. No-build frontend
Vanilla ES modules and Tailwind compiled once with the local CLI; Chart.js, fonts, and icons are vendored. Nothing to install on the host, no CDN, nothing to break on the demo day.

### ADR-16. Render
The `render.yaml` blueprint pins Python 3.12.8 because the newest default can lack scientific wheels. The free plan sleeps and has 0.1 CPU. Precomputed presets keep the demo instant, live re-solves are throttled and cached, and PROGRESS.md recommends the $7 plan for judging week.

### ADR-17. Tooling
- Claude Code ran the build autonomously from `docs/BUILD_DIRECTIVE.md`:
  - Superpowers wrote the spec and per-phase plans and enforced TDD on the math.
  - ECC's reviewer agents ran the phase gates (`python-reviewer`, `code-reviewer`, `security-reviewer`).
  - ui-ux-pro-max generated the design system, refined by the frontend-design skill.
  - The find-skills results were reviewed (nothing new installed).
- A five-member council of read-only reviewer agents (quant, controller, Ramp engineer, designer, judge) red-teamed each gate. Every verdict and ruling is in `docs/council/`.

## Rulings after C2 (P4 to P6)
- Ruling: Security review findings fixed before judges click: per-IP throttle (6 per minute) and an LRU cache on live re-solves; shared demo state (review acceptances, negotiated terms, autonomy) resets after 30 idle minutes and via `POST /api/reset`; CSP and security headers; generic error bodies; audit log capped at 1,000 entries and fsynced, described as tamper-evident (not tamper-proof); the hosted-model adapter refuses unless explicitly enabled | a public no-auth demo on 0.1 CPU is shared by every visitor | Low.
- Ruling: Built two cut-line items because the schedule allowed: the hosted-model adapter (`tempo/llm/anthropic_provider.py`, gated) and PDF upload (`POST /api/extract/upload`, pypdf in memory, 2 MB / 10 pages, never changes the plan) | both were optional; neither is on the demo path | Low.
- Ruling: Demo script, submission description, and README results are rendered by `make results` from the precomputed files | numbers in prose can never drift from RESULTS.md | None.
- Ruling: UI design calls (frontend-design over ui-ux-pro-max's proposal): IBM Plex Sans with tabular numerals, warm off-white page #F5F4F0, white panels with #E4E2DC borders, ink #1C1C1A, one cobalt accent #2E4BB8 only on commit actions, green #1D7A45 and red #B3261E only for money gained or at risk, ochre #875200 only for Needs review; rejected the generated blue/amber scheme and Fira fonts (`design-system/tempo/MASTER.md`) | directive 9.1 direction; avoids the generic AI-fintech look | Low.
- Ruling: Live re-solves keep the base plan's certified K and report a seed-B estimate labeled "not re-certified"; presets carry full certification | a full ladder per click is too slow on the host (C1, judge) | Low.
