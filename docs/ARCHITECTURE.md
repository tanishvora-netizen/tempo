# Architecture

Tempo is a small Python library (`tempo/`) with a thin FastAPI layer (`app/`) and a no-build static frontend (`app/static/`). The library never imports FastAPI. Everything the hosted demo shows is precomputed and committed, so the server only loads files.

```mermaid
flowchart LR
    subgraph Ingest
        D[(data/demo<br/>synthetic invoices,<br/>emails, customers)] --> P[Deterministic parser<br/>regex_parser + numwords]
        D --> M[Local model via Ollama<br/>locate and quote only]
        M -.replayed from.-> C[(data/cache<br/>committed outputs)]
        P --> R{Reconcile<br/>verify quotes,<br/>sanity, history}
        M --> R
        R -->|accepted| T[Terms]
        R -->|conflict, ambiguous,<br/>hallucination, injection| NR[Needs review]
    end
    subgraph Forecast
        D --> F[Censored, pooled lognormal fit<br/>+ common factor]
        F --> S[Scenarios: A optimize,<br/>B certify, C report]
    end
    subgraph Optimize
        T --> O[Options per bill:<br/>date x rail]
        NR -->|no discount until confirmed| O
        O --> X[Reduced chance-constrained MILP<br/>HiGHS via scipy]
        S --> X
        X --> Q{Certify on seed B<br/>Bonferroni Wilson bound}
        Q -->|fail: lower K| X
        Q -->|pass| PL[Plan]
        PL --> E[Templated explanations<br/>binding reason]
        PL --> V[Proof: 6 policies on seed C<br/>+ true model, ablations]
    end
    subgraph Act
        PL --> N[Negotiation agent<br/>break-even offer, verified by re-solve,<br/>number-guarded email]
        PL --> AP[CFO approval<br/>hash-chained audit log]
        AP --> RP[Ramp payload preview<br/>PATCH, hold, release<br/>never sent]
    end
    PL --> PC[(data/precomputed<br/>keyed by input hash)]
    V --> PC
    PC --> API[FastAPI routes] --> UI[Static UI]
```

## Layers

| Layer | Path | Role |
|---|---|---|
| Assumptions | `tempo/assumptions.py` | Every parameter, labeled SOURCED or ASSUMPTION |
| Data | `tempo/data/` | Seeded synthetic generator (company, vendors, invoices with hard cases, customers) and loader |
| Extraction | `tempo/extract/` | Parser, number words, due dates (EOM/prox), quote verification, reconciliation table, extraction eval |
| AI providers | `tempo/llm/` | One interface: Ollama (local), Cached (replay), Anthropic (disabled unless explicitly allowed) |
| Forecast | `tempo/forecast/` | Censored pooled fit; Monte Carlo inflows with a common factor and truncated sampling |
| Optimizer | `tempo/optimize/` | Options, capacity caps, MILP with exact reductions, certification, baselines, evaluation, cash value, explanations |
| Agent | `tempo/agent/` | Negotiation pricing and verification; number guard for model-written prose |
| Controls | `tempo/audit.py`, `tempo/ramp/payloads.py` | Tamper-evident approval log; Ramp request preview |
| Glue | `tempo/pipeline.py`, `tempo/precompute.py`, `tempo/live.py`, `tempo/report.py`, `tempo/views.py` | Ingest to plannable bills, precompute, live re-solves, JSON views |
| API | `app/` | Routes only; strict request schemas; security headers; throttle on live solves |
| UI | `app/static/` | Vanilla ES modules, Tailwind compiled locally, vendored Chart.js, fonts, and icons |

## Runtime modes

| Mode | Command | Model | Solves at startup |
|---|---|---|---|
| Hosted demo (Render) | `uvicorn app.main:app` with `TEMPO_PROVIDER=cached` | none; committed cache replayed | none; precomputed files loaded |
| Local dev | `make dev` | cached extractions; drafts and replies use Ollama if running | none |
| Live final | `make demo` | Ollama local model for live drafting and reply parsing | none |

## Determinism

One seed (`assumptions.SEED`) derives the scenario seeds A, B, C, D, and the fan seed. HiGHS runs with a time limit, a node limit, and a 0.01% gap. The plan hash is SHA-256 over float-free canonical JSON of each bill's option, dates, and cents. `tests/unit/test_planning.py` checks that two solves give the same hash and that the committed precomputed files match the current inputs.

## Zero external calls

The running app talks only to its own origin. Fonts, Chart.js, and icons are vendored into `app/static/vendor/`. The local model runs on `127.0.0.1`. Ramp is never called: the payload preview is built and shown, never sent. The hosted-model adapter refuses to start unless `TEMPO_ALLOW_EXTERNAL_LLM=1` and a key are both set.
