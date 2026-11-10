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
