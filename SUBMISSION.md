# Submission: Tempo (Team Hopeful)

Form: https://forms.gle/FxUVTm6Z75f121ov5 (the team submits; nothing here is sent automatically).

- **Repository:** https://github.com/tanishvora-netizen/tempo
- **Live demo:** _paste the Render URL from PROGRESS.md once deployed_
- **Demo video:** _upload docs/demo/tempo-demo.webm with voiceover and paste the link here_
- **Team:** Tanish Vora, Anthony Olakangil, Namith Tatipigari

## Description (150 words)

<!-- description:start -->
_Filled by the lead from docs/RESULTS.md._
<!-- description:end -->

## Stack

- **Optimizer:** Python 3.12, `scipy.optimize.milp` (HiGHS), NumPy. A chance-constrained MILP with exact row reductions and out-of-sample certification.
- **Forecast:** a censored, partially pooled lognormal model of customer payment timing, with a common factor and Monte Carlo scenarios.
- **AI:** qwen3:8b served locally by Ollama, with structured outputs. Its answers are replayed from a committed cache on the hosted demo. A hosted-model adapter exists but is disabled unless explicitly allowed.
- **API:** FastAPI with Pydantic, behind security headers, with a throttle on live solves.
- **Frontend:** vanilla ES modules, Tailwind CSS compiled locally, Chart.js, IBM Plex Sans and Lucide icons, all vendored. No CDN, no build step on the host.
- **Tests:** pytest with Hypothesis, plus Playwright for the end-to-end demo path. CI runs on GitHub Actions with no network and no Ollama.
- **Deploy:** a Render blueprint (`render.yaml`, Python 3.12.8) and a keep-warm workflow.
- **How we built it:** Claude Code ran the build autonomously with ECC, Superpowers, ui-ux-pro-max, frontend-design, and find-skills. A five-member reviewer council checked each gate; every verdict is in `docs/council/`.

## The decisions behind our tools and workflows

1. **An optimizer, not a prompt.** Paying bills is a constrained allocation problem with money on the line, so the core is a MILP. The model only reads documents. It never computes or changes a number, and every number on screen traces to the data, `tempo/assumptions.py`, or the solver.
2. **A chance constraint, certified out of sample.** "Keep cash above the buffer in 95% of scenarios" is the CFO's real requirement. Sample-average approximation is optimistic, so every plan is tested on 10,000 fresh scenarios with a Bonferroni-corrected Wilson bound, and we report on a third set. We also report under the generator's true payment model and name the forecast model as our main weakness.
3. **Exact reductions instead of a bigger machine.** Checking only outflow days, a quantile cut, and the tightest big-M shrink the model about 20 times with the same optimum. That keeps solves under a second and what-ifs interactive.
4. **Locate-and-quote AI with a deterministic cross-check.** The local model quotes where the terms are. Code verifies that each quote is in the document, re-parses it, and reconciles it with a regex parser in a fixed table. Anything uncertain goes to Needs review with the evidence highlighted, in status buckets rather than confidence scores, as in Ramp's agent playbook. The prompt-injection invoice is caught.
5. **A local model and committed caches.** Invoice and cash data never leave the company, the demo works with no network, and the hosted version replays exactly what the local model produced.
6. **Suggestions first, autonomy by policy.** "Suggest only" is the default; "auto-schedule Verified bills under $X" is the next step. Every approval is written to a hash-chained audit log, and the Ramp API payload preview shows the exact requests without sending them.
7. **Councils and written decisions.** Each phase was reviewed by independent agents playing a quant, an AP controller, a Ramp engineer, a designer, and a judge. Their findings changed the product: censored forecasting, multiple-testing correction, credit caps, business-day sends. Every ruling is recorded in `docs/DECISIONS.md` and `docs/council/`.
