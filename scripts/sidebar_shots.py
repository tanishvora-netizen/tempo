"""Screenshot Overview and Payment run with the sidebar at 1440x900 and 1024x768 (design pass).

Usage: .venv/bin/python scripts/sidebar_shots.py [--base-url http://127.0.0.1:8000]
Saves docs/screenshots/design-sidebar/final-<screen>-<width>.png and fails on any console error or any
request to a host other than the app's own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots" / "design-sidebar"
VIEWPORTS = {1440: 900, 1024: 768}
VARIANTS = {"final": ""}
SCREENS = {"overview": "#fan-canvas", "run": "tr[data-bill]"}
SETTLE_MS = 700


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    origin = urlparse(args.base_url).netloc
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    foreign: set[str] = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in VIEWPORTS.items():
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: (
                    foreign.add(r.url)
                    if urlparse(r.url).netloc not in (origin, "") and not r.url.startswith("data:")
                    else None
                ),
            )
            for variant, query in VARIANTS.items():
                for screen, ready in SCREENS.items():
                    page.goto(f"{args.base_url}/{query}#/{screen}", wait_until="networkidle")
                    page.wait_for_selector(ready)
                    page.wait_for_selector(".nav-group")
                    page.wait_for_timeout(SETTLE_MS)
                    path = OUT / f"{variant}-{screen}-{width}.png"
                    page.screenshot(path=str(path))
                    print(f"saved {path.relative_to(OUT.parents[2])}")
            page.close()
        browser.close()
    print(f"console errors: {len(errors)}; requests to other hosts: {len(foreign)}")
    for e in errors:
        print("  error:", e)
    for u in sorted(foreign):
        print("  foreign:", u)
    return 1 if errors or foreign else 0


if __name__ == "__main__":
    sys.exit(main())
