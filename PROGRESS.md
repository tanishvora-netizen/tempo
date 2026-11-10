BUILD STATUS: IN PROGRESS (phase P4/P5; P6 next)

# Tempo build progress

## Human actions
1. **Deploy on Render (one time, ~3 minutes).** render.com → sign in with GitHub → **New** → **Blueprint** → pick `tanishvora-netizen/tempo` → **Apply**. Render reads `render.yaml` (Python 3.12.8, `TEMPO_PROVIDER=cached`, health check `/health`). After that, every push to `main` redeploys. Paste the URL on the line below so the build can run `make verify-live URL=<url>`.
   - Live URL: _(not yet deployed)_
2. **Keep it awake for judging week (pick one).** Upgrade the service to the $7/mo `0.5c-512mb` plan (0.5 CPU, no sleep; recommended: custom what-ifs solve live and the free plan's 0.1 CPU is slow), or set the GitHub repo variable `TEMPO_URL` (Settings → Secrets and variables → Actions → Variables) so `.github/workflows/keepwarm.yml` pings it, and add a free UptimeRobot 5-minute monitor on `<url>/health`.
3. Optional skill (not installed tonight): `npx skills add anthropics/skills@webapp-testing` (201.6K installs) for Playwright-driven web app testing. It overlaps ECC `e2e-testing`, so it is not needed for the build.

## What works end to end (as of 03:45 PT)
- Synthetic dataset (`data/demo`, `data/ample`): 212 bills, 40 vendors, 25 customers, hard-case invoices with ground truth. Starting cash calibrated by the pre-registered rule ($3.6M, fallback rule; see DECISIONS.md and RESULTS.md).
- Extraction: deterministic parser (205+ tests), local model (qwen3:8b via Ollama) with quote verification, reconciliation table, Needs review; cache build running in the background (`logs/build_cache.log`).
- Forecast: censored, partially pooled lognormal with a common factor; fan chart data.
- Optimizer: reduced chance-constrained MILP (HiGHS via scipy), certification ladder on seed B with Bonferroni z, reporting on seed C plus the true model, six policies, ablations, cash value, explanations, card and financing caps.
- API: every route in directive 8.2 (FastAPI), live re-solve for custom what-ifs and review edits, precomputed presets.
- P5: negotiation agent (break-even pricing, optimizer-verified offers, number guard, reply parsing), hash-chained audit log, Ramp payload preview (never sent).
- Councils: C1 and C2 recorded in `docs/council/`, all rulings applied.

## In flight
- UI (subagent): `app/static/` vanilla ES modules + Tailwind, design system in `design-system/tempo/MASTER.md`, screenshots in `docs/screenshots/`.
- Security review (subagent).
- Extraction cache build (local model): when done, run the final sequence below.

## Final sequence once the cache build finishes
```bash
.venv/bin/python scripts/build_cache.py --concurrency 2          # extraction (resumes; skips existing)
TEMPO_PROVIDER=cached .venv/bin/python scripts/calibrate_cash.py  # same pre-registered rule
.venv/bin/python scripts/generate_data.py                         # applies calibrated cash
make precompute && make cache-negotiation && make results
make test
```

## Next (P6)
README, MATH.md, ARCHITECTURE.md, DEMO_SCRIPT.md, SUBMISSION.md, DECISIONS ADRs; Playwright e2e and demo video; C3 (UI) and C4 (red team).

## Commands
```bash
make test        # pytest, no network, no Ollama
make dev         # http://127.0.0.1:8000
make lint
make precompute  # regenerate data/precomputed (commit the output)
make results     # regenerate docs/RESULTS.md
```
