"""Click every What-if preset, check it renders fast with no console errors, and screenshot it (fix pass B).

Usage:
    .venv/bin/python scripts/preset_shots.py [--base-url http://127.0.0.1:8000] [--max-seconds 1.0]
        [--custom]   # also run two custom what-ifs (late customer, unexpected payment) and a cached repeat

Saves docs/screenshots/presets/<preset-id>.png. Exits non-zero if a preset is slow, shows a console error,
or any request goes to a host other than the app's own. Prints one JSON line per check (used for timings).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "presets"
VIEWPORT = {"width": 1440, "height": 900}
CUSTOM_TIMEOUT_MS = 180_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--max-seconds", type=float, default=1.0)
    ap.add_argument("--custom", action="store_true")
    ap.add_argument("--no-shots", action="store_true")
    args = ap.parse_args()
    origin = urlparse(args.base_url).netloc
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    foreign: list[str] = []
    failed = False
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on(
            "request",
            lambda r: (
                foreign.append(r.url)
                if urlparse(r.url).netloc not in (origin, "") and not r.url.startswith("data:")
                else None
            ),
        )
        page.request.post(f"{args.base_url}/api/reset")
        page.goto(f"{args.base_url}/#/whatif", wait_until="networkidle")
        page.wait_for_selector("[data-preset]")
        page.evaluate("try { localStorage.setItem('tempo.hostingNotice.dismissed', '1') } catch (e) {}")
        ids = page.eval_on_selector_all("[data-preset]", "els => els.map(e => e.dataset.preset)")
        for pid in ids:
            label = page.eval_on_selector(f'[data-preset="{pid}"]', "e => e.textContent.trim()")
            before = len(errors)
            started = time.perf_counter()
            page.click(f'[data-preset="{pid}"]')
            page.wait_for_function(
                "label => document.querySelector('#wi-summary')?.textContent.trim() === label && !document.querySelector('[data-run]').disabled",
                arg=label,
            )
            secs = time.perf_counter() - started
            page.wait_for_timeout(450)  # let the chart animation settle before the screenshot
            if not args.no_shots:
                page.screenshot(path=str(OUT / f"{pid}.png"), full_page=True)
            ok = secs <= args.max_seconds and len(errors) == before
            failed |= not ok
            print(
                json.dumps(
                    {"preset": pid, "seconds": round(secs, 3), "console_errors": errors[before:], "ok": ok}
                ),
                flush=True,
            )
        if args.custom:
            failed |= not custom_runs(page, errors)
        browser.close()
    if foreign:
        print(json.dumps({"foreign_requests": sorted(set(foreign))}))
        failed = True
    return 1 if failed else 0


def run_custom(page, setup: str, label: str) -> float:
    page.evaluate(setup)
    started = time.perf_counter()
    page.click("[data-run]")
    page.wait_for_function(
        "label => document.querySelector('#wi-summary')?.textContent.trim() === label && !document.querySelector('[data-run]').disabled",
        arg=label,
        timeout=CUSTOM_TIMEOUT_MS,
    )
    return time.perf_counter() - started


def custom_runs(page, errors: list[str]) -> bool:
    """Two different custom what-ifs and one repeat (which must come from the cache)."""
    customer = page.eval_on_selector(
        "select[name=customer] option:nth-child(2)", "e => [e.value, e.textContent]"
    )
    delay_setup = (
        "(() => { document.querySelector('[data-mode=delay]').click(); const f = document.querySelector('[data-form]');"
        f" f.customer.value = '{customer[0]}'; f.delay.value = '23'; f.delay.dispatchEvent(new Event('input')); }})()"
    )
    shock_setup = (
        "(() => { document.querySelector('[data-mode=shock]').click(); const f = document.querySelector('[data-form]');"
        " f.shock.value = '420,000'; f.shock.dispatchEvent(new Event('input')); })()"
    )
    before = len(errors)
    t1 = run_custom(page, delay_setup, f"{customer[1]} pays 23 days late")
    print(json.dumps({"custom": "late customer", "seconds": round(t1, 1)}), flush=True)
    t2 = run_custom(page, shock_setup, "Unexpected $420,000 payment today")
    print(json.dumps({"custom": "unexpected payment", "seconds": round(t2, 1)}), flush=True)
    t3 = run_custom(page, delay_setup, f"{customer[1]} pays 23 days late")
    cached = t3 < 2.5
    print(json.dumps({"custom": "repeat (cache)", "seconds": round(t3, 2), "cached": cached}), flush=True)
    page.screenshot(path=str(OUT / "custom-late-customer.png"), full_page=True)
    return cached and len(errors) == before


if __name__ == "__main__":
    sys.exit(main())
