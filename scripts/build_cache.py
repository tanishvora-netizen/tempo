"""Fill data/cache/ with local-model outputs for every invoice (run with `make cache`).

Calls the local Ollama model only (no external network). Existing entries are skipped, so the script can be
re-run after an interruption. Failures are cached as failures so the host replays them faithfully.
"""

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from tempo.agent.negotiation import REPLY_KINDS, Offer, reply_model_call
from tempo.data.store import load_dataset
from tempo.llm.cached_provider import CACHE_DIR, read_entry, write_entry
from tempo.llm.ollama_provider import OllamaProvider
from tempo.llm.provider import ModelCall, ProviderError, draft_call, extraction_call
from tempo.llm.schemas import OfferTemplate, TermsExtraction
from tempo.serde import from_jsonable

OFFERS = Path(__file__).resolve().parents[1] / "data" / "precomputed" / "offers.json"


def run_one(provider: OllamaProvider, call: ModelCall, schema: type[BaseModel] = TermsExtraction) -> str:
    started = time.perf_counter()
    try:
        completion = provider.complete(call, schema)
        schema.model_validate_json(completion.raw)
        write_entry(CACHE_DIR, call, provider.name, provider.model, completion.raw, None)
        status = "ok"
    except ProviderError as exc:
        write_entry(CACHE_DIR, call, provider.name, provider.model, None, str(exc))
        status = "failed"
    except ValueError as exc:
        write_entry(CACHE_DIR, call, provider.name, provider.model, None, f"invalid output: {exc}")
        status = "failed"
    return f"{status} {time.perf_counter() - started:.1f}s"


def extraction_calls() -> list[tuple[ModelCall, type[BaseModel]]]:
    dataset = load_dataset("demo")
    domains = {v.id: v.domain for v in dataset.vendors}
    return [
        (extraction_call(inv, domains[inv.vendor_id], dataset.company.domain), TermsExtraction)
        for inv in dataset.invoices
    ]


def negotiation_calls() -> list[tuple[ModelCall, type[BaseModel]]]:
    """Offer drafts and simulated-reply parses for every vendor with a priced offer (run after precompute)."""
    offers = [from_jsonable(Offer, o) for o in json.loads(OFFERS.read_text())["offers"]]
    calls: list[tuple[ModelCall, type[BaseModel]]] = []
    for o in offers:
        calls.append((draft_call(o.vendor_name), OfferTemplate))
        calls += [(reply_model_call(o, kind), TermsExtraction) for kind in REPLY_KINDS]
    return calls


def write_manifest() -> None:
    models: Counter[str] = Counter()
    tasks: Counter[str] = Counter()
    failures = 0
    for path in CACHE_DIR.glob("*/*.json"):
        d = json.loads(path.read_text())
        models[d["model"]] += 1
        tasks[d["task"]] += 1
        failures += d.get("error") is not None
    manifest = {
        "models": dict(models),
        "tasks": dict(tasks),
        "failures": failures,
        "entries": sum(tasks.values()),
    }
    (CACHE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print("manifest:", manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--negotiation", action="store_true", help="draft offers and parse replies for ranked vendors"
    )
    args = parser.parse_args()
    provider = OllamaProvider()
    if not provider.is_available():
        sys.exit(f"Ollama model {provider.model} is not available; run `ollama pull {provider.model}`.")
    calls = negotiation_calls() if args.negotiation else extraction_calls()
    todo = [(c, schema) for c, schema in calls if read_entry(CACHE_DIR, c) is None]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(calls)} calls, {len(todo)} to run with {provider.model}", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, provider, c, schema): c for c, schema in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            print(f"[{i}/{len(todo)}] {fut.result()}", flush=True)
    write_manifest()


if __name__ == "__main__":
    main()
