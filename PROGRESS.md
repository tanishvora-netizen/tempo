BUILD STATUS: IN PROGRESS (final fix pass)

# Tempo build progress

Built autonomously on Nov 10, 2026 (about 01:50 to 05:35 PT) from `docs/BUILD_DIRECTIVE.md`. Every phase (P0 to P6) is complete, councils C1 to C4 are recorded in `docs/council/`, and C4 closed with no open BLOCK.

## Human actions (the remaining steps, in order)
1. **Record the voiceover** for `docs/demo/tempo-demo.webm` (silent, 1440x900, follows `docs/DEMO_SCRIPT.md`; re-record with `make demo-video`).
2. **Submit the form** at https://forms.gle/FxUVTm6Z75f121ov5 using `SUBMISSION.md` (repo link, description, stack, tool decisions; paste the live and video links first).
3. Before rehearsals and the live demo, reset shared state: `curl -X POST https://tempo-kor8.onrender.com/api/reset`.
4. Live demo on Render's free plan (kept awake by UptimeRobot every 5 minutes). Presets are instant; custom what-ifs solve live and run as background jobs (see the What-if notice for measured times).

## Final fix pass (Nov 10, afternoon)
Items 1 to 8 and sections A to C of the final fix pass are done; rulings are at the end of `docs/DECISIONS.md` and the reviewer round is `docs/council/C5.md`.
- Starting-cash sweep: no value met both breach thresholds; cash kept at $3.6M (disclosed).
- Certification ladder starts at K = 10 (5% of N) and walks down to 0 (Bonferroni z over nine steps).
- Financing toggle on Overview (FLEX_LIMIT caps outstanding financing); what-ifs use financing before any late payment, with a three-way tradeoff box.
- Risk-vs-value frontier on Proof; the five lowest scenarios on the Overview chart.
- Sends and Arrives columns, merged identical policies, whole-dollar tooltips, date-like invoice numbers labeled.
- Annual value if accepted on Negotiate.
- Custom what-ifs run as background jobs (one at a time, cached, 40 s solver limit), with a hosting notice and footer.

## What works end to end
- **Synthetic company:** Kestrel Ridge Manufacturing, with 212 bills from 40 vendors and 25 customers. Invoice documents include tagged hard cases, among them a prompt-injection invoice, with ground truth. Starting cash comes from a pre-registered calibration rule.
- **Extraction:**
  - deterministic parser;
  - a local model (qwen3:8b via Ollama) that quotes, with code verifying every quote;
  - a reconciliation table that feeds Needs review;
  - 312 committed model outputs (212 extractions, 20 offer drafts, 80 reply parses);
  - PDF upload.
- **Forecast:** censored, partially pooled lognormal fit with a common factor; a 1,000-scenario fan with P1/P10/P50/P90/P99 bands.
- **Optimizer:**
  - reduced chance-constrained MILP (630 rows vs 18,413 naive, about 0.9 s);
  - feasibility-only backstop credit;
  - card and financing caps;
  - certification on seed B with Bonferroni Wilson bounds, reported on seed C, under the true model, and under a common-factor stress.
- **Evaluation:** six policies, ablations, cash value, and binding-reason explanations.
- **Agent and controls:**
  - negotiation agent with offers verified by re-solve and model drafts behind number and wording guards;
  - reply parsing;
  - scoped approvals in a hash-chained audit log;
  - Ramp payload preview (PATCH, hold, release, manual-RTP bucket), never sent.
- **UI:** five screens plus the Negotiate and Audit drawers. Zero external requests and zero console errors (Playwright), usable at 1440 and 1024 px.

## Headline numbers
Generated, never hand-edited: see the README results block and `docs/RESULTS.md` (`make results` renders both from `data/precomputed/`).

## What is stubbed or simplified
- **No real integrations:** the Ramp API is previewed, never called, and there are no bank, Ramp, or email connections (out of scope).
- **Hosted demo AI:** it replays cached local-model outputs, and live AI runs on the local install (`make demo`). A PDF uploaded on the host gets a parser-only reading.
- **No authentication:** approvals record an attested name, not an authenticated user.
- **Assumed parameters:** the Flex-style option is off by default, with an assumed fee. Card statement timing, cashback, card limit, and yield are assumptions, each labeled in `tempo/assumptions.py`.

## Open risks (named in the README "Limits" section)
- **Forecast model risk.** Certification covers sampling error only. Every policy breaches more under a doubled common factor; Tempo stays near pay-on-due.
- **The certified bound is under the fitted model.** The ladder now starts at K = 10, so the plan sits closer to 5%; under the generator's true model its bound can exceed 5% (RESULTS.md).
- **Manual RTP sends.** 12 of this week's 24 bills can only meet their dates by RTP, which Ramp's API cannot request.
- **The extraction eval is synthetic** and flatters the parser.

## Definition of done (directive section 14)
- [x] Host mode loads in under 3 s and shows the default plan immediately (server ready 1.0 s; KPIs visible 0.1 s).
- [x] Presets are instant (0.13 s); a custom what-if re-solves in 2.5 s locally and shows a diff.
- [x] The out-of-sample breach upper bound is at or below 5% (2.43%) and the proof panel shows it.
- [x] CI is green, ruff is clean, and every required test is present.
- [x] RESULTS.md is generated by script; README, DEMO_SCRIPT, and SUBMISSION numbers are rendered from the same files.
- [x] Every number on screen traces to data, assumptions.py, or the solver (automated Overview check; C3 and C4 fixes).
- [x] Zero external network calls in host mode (e2e test and screenshot runs log every request).
- [x] Deployable as-is from render.yaml (fresh-clone check with runtime requirements only).
- [x] Council C4 has no open BLOCK (round 2).
- [x] Backup video recorded; DEMO_SCRIPT and SUBMISSION complete.
- [x] PROGRESS.md lists the exact remaining human steps (above).

## Commands
```bash
make test        # pytest, no network, no Ollama
make dev         # http://127.0.0.1:8000 (replays committed model outputs)
make demo        # offline, local model live for drafting and reply parsing
make e2e         # Playwright demo path
make lint
make precompute  # regenerate data/precomputed (commit the output), then: make cache-negotiation && make results
make demo-video  # docs/demo/tempo-demo.webm
make verify-live URL=https://tempo-kor8.onrender.com
```
