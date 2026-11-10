BUILD STATUS: IN PROGRESS (phase P0)

# Tempo build progress

## Human actions
1. **Deploy on Render (one time, ~3 minutes).** render.com → sign in with GitHub → **New** → **Blueprint** → pick `tanishvora-netizen/tempo` → **Apply**. Render reads `render.yaml` (Python 3.12.8, `TEMPO_PROVIDER=cached`, health check `/health`). After that, every push to `main` redeploys. Paste the URL on the line below so the build can run `make verify-live URL=<url>`.
   - Live URL: _(not yet deployed)_
2. **Keep it awake for judging week (pick one).** Upgrade the service to the $7/mo `0.5c-512mb` plan (0.5 CPU, no sleep; recommended), or set the GitHub repo variable `TEMPO_URL` (Settings → Secrets and variables → Actions → Variables) so `.github/workflows/keepwarm.yml` pings it, and add a free UptimeRobot 5-minute monitor on `<url>/health`.
3. Optional skill (not installed tonight): `npx skills add anthropics/skills@webapp-testing` (201.6K installs) for Playwright-driven web app testing. It overlaps ECC `e2e-testing`, so it is not needed for the build.

## What works end to end
- P0: FastAPI skeleton with `/health` and a placeholder page; `render.yaml`, CI, keep-warm workflow, Makefile.

## What is stubbed
- Everything past P0 (data, extraction, forecast, optimizer, UI, agent, docs).

## Next
- P1: seeded data generator with hard cases and ground truth; deterministic parser; due dates; provider interface; Ollama and cached providers; evidence check; reconciliation; cache build; extraction eval.

## Commands
```bash
make test        # pytest, no network, no Ollama
make dev         # http://127.0.0.1:8000
make lint
```
