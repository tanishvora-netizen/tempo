"""Screenshot every Tempo screen and drawer at 1440x900 and 1024x768 (directive 9.4).

Usage:
    .venv/bin/python scripts/screenshots.py [--base-url http://127.0.0.1:8000] [--mutate]

Saves PNGs to docs/screenshots/ (overview-1440.png, ...). Also logs every network request
and fails if any goes to a host other than the app's own origin (the app must make zero
external calls), and reports browser console errors.

Every run starts with POST /api/reset so counts start clean (13 bills in Needs review).
The default run is read-only. Run --mutate afterwards as a separate, final step: it records an
approval (an audit entry) and accepts one Needs-review item, saving approve-dialog,
audit-drawer-approved, and needs-review-accepted, then resets the demo state again. Only use
--mutate against a throwaway server whose TEMPO_AUDIT_PATH points somewhere disposable.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "screenshots"
VIEWPORTS = {1440: 900, 1024: 768}
WAIT_MS = 15_000
SETTLE_MS = 300
MODEL_WAIT_MS = 120_000  # live local-model calls (offer drafting, reply parsing) can take a while
APPROVER = "Jordan Lee, CFO"
SAMPLE_INVOICE_LINES = [
    "NORTHWIND FASTENER SUPPLY",
    "INVOICE #NFS-20417",
    "Invoice date: 11/02/2026",
    "Bill to: Kestrel Ridge Manufacturing, Inc.",
    "Hex bolts M8, box of 200   12 x $84.50   $1,014.00",
    "Subtotal: $1,014.00",
    "Freight: $45.00",
    "Total due: $1,059.00 USD",
    "Payment terms: 2/10 Net 30",
    "Late payments accrue 1.5% per month.",
    "We accept ACH and credit card, 3% surcharge on card payments.",
]
LOCAL_SCHEMES = {"data", "blob"}


@dataclass
class Log:
    origin: str
    requests: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)

    def external(self) -> list[str]:
        out = []
        for url in self.requests:
            parsed = urlparse(url)
            if parsed.scheme in LOCAL_SCHEMES:
                continue
            if f"{parsed.scheme}://{parsed.netloc}" != self.origin:
                out.append(url)
        return out


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle", timeout=WAIT_MS)
    page.wait_for_timeout(SETTLE_MS)


def shoot(page: Page, name: str, width: int, *, full_page: bool = True) -> Path:
    path = OUT_DIR / f"{name}-{width}.png"
    page.screenshot(path=str(path), full_page=full_page)
    print(f"  saved {path.relative_to(ROOT)}")
    return path


def goto(page: Page, base: str, route: str, ready: str) -> None:
    page.goto(f"{base}/#/{route}")
    page.wait_for_selector(ready, timeout=WAIT_MS)
    settle(page)


def close_drawer(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_selector(".drawer", state="detached", timeout=WAIT_MS)


def reset_server(base: str) -> None:
    """POST /api/reset: clear review acceptances, negotiated terms, and autonomy (not the audit log)."""
    request = urllib.request.Request(f"{base}/api/reset", method="POST", data=b"")
    with urllib.request.urlopen(request, timeout=WAIT_MS / 1000) as response:
        response.read()


def capture_overview(page: Page, base: str, width: int) -> None:
    goto(page, base, "overview", "#fan-canvas")
    shoot(page, "overview", width)
    page.click("[data-open-audit]")
    page.wait_for_selector(".drawer [data-plist] li", timeout=WAIT_MS)
    settle(page)
    shoot(page, "audit-drawer", width, full_page=False)
    close_drawer(page)


def capture_approval(page: Page, base: str, width: int) -> None:
    """Mutating: record an approval for this week's run and show the new audit entry."""
    goto(page, base, "overview", "#fan-canvas")
    page.click("[data-approve]")
    page.wait_for_selector("dialog[open]", timeout=WAIT_MS)
    page.fill('dialog [name="approver"]', APPROVER)
    page.wait_for_timeout(SETTLE_MS)
    shoot(page, "approve-dialog", width, full_page=False)
    page.click("dialog [data-confirm]")
    page.wait_for_selector(".drawer [data-plist] li", timeout=WAIT_MS)
    settle(page)
    shoot(page, "audit-drawer-approved", width, full_page=False)
    close_drawer(page)


def capture_run(page: Page, base: str, width: int) -> None:
    goto(page, base, "run", "tr[data-bill]")
    shoot(page, "payment-run", width, full_page=False)  # 212 rows; the first screen is what matters
    page.locator("tr[data-bill]", has_text="Early, discount").first.click()
    page.wait_for_selector(".drawer .doc", timeout=WAIT_MS)
    settle(page)
    shoot(page, "bill-panel", width, full_page=False)
    close_drawer(page)


def sample_pdf() -> bytes:
    """A small fictional invoice PDF built with the test suite's hand-rolled PDF writer."""
    sys.path.insert(0, str(ROOT))
    from tests.unit.test_upload import make_pdf

    return make_pdf(SAMPLE_INVOICE_LINES)


def capture_upload(page: Page, width: int) -> None:
    page.set_input_files(
        "[data-upload]",
        files=[{"name": "northwind-invoice.pdf", "mimeType": "application/pdf", "buffer": sample_pdf()}],
    )
    page.wait_for_selector(".drawer[data-drawer='upload'] .doc", timeout=MODEL_WAIT_MS)
    settle(page)
    shoot(page, "upload-pdf", width, full_page=False)
    close_drawer(page)


def capture_review(page: Page, base: str, width: int) -> None:
    goto(page, base, "review", "[data-detail] [data-accept]")
    shoot(page, "needs-review", width)
    capture_upload(page, width)
    injection = page.locator("[data-item]", has_text="Westbrook")
    if injection.count():
        injection.first.click()
        settle(page)
        shoot(page, "needs-review-injection", width)


def capture_review_accept(page: Page, base: str, width: int) -> None:
    """Mutating: accept one Needs-review item and show the re-solve effect."""
    goto(page, base, "review", "[data-detail] [data-accept]")
    target = page.locator("[data-item]", has_text="Sorrel Bay")
    if target.count():
        target.first.click()
        page.click("[data-detail] [data-accept]")
        page.wait_for_selector("[data-effect]", timeout=60_000)
        settle(page)
        page.locator("[data-effect]").scroll_into_view_if_needed()
        shoot(page, "needs-review-accepted", width, full_page=False)


def capture_whatif(page: Page, base: str, width: int, live: bool) -> None:
    goto(page, base, "whatif", "#wi-canvas")
    page.click("[data-preset] >> nth=4")
    page.wait_for_selector("[data-diff] table", timeout=WAIT_MS)
    settle(page)
    shoot(page, "whatif", width)
    if live:
        page.select_option('[name="customer"]', index=1)
        page.fill('[name="delay"]', "21")
        page.click("[data-run]")
        page.wait_for_selector("[data-summary] .chip-review", timeout=60_000)
        settle(page)
        shoot(page, "whatif-live", width)


def capture_proof(page: Page, base: str, width: int) -> None:
    goto(page, base, "proof", "#breach-canvas")
    shoot(page, "proof", width)


def capture_negotiate(page: Page, base: str, width: int) -> None:
    goto(page, base, "overview", "#fan-canvas")
    page.click("[data-negotiate]")
    page.wait_for_selector(
        ".drawer[data-drawer='negotiate'] .drawer-body > *:not([role=status])", timeout=WAIT_MS
    )
    settle(page)
    shoot(page, "negotiate-drawer", width, full_page=False)
    draft = page.locator(".drawer [data-vendor]")
    if draft.count():
        draft.first.click()
        page.wait_for_selector(".drawer [data-reply]", timeout=MODEL_WAIT_MS)  # the local model drafts
        page.click(".drawer [data-reply='counter']")
        page.wait_for_selector(".drawer [data-reply-out] dl", timeout=MODEL_WAIT_MS)
        settle(page)
        shoot(page, "negotiate-offer", width, full_page=False)
    close_drawer(page)


def capture_read_only(page: Page, base: str, width: int) -> None:
    capture_overview(page, base, width)
    capture_run(page, base, width)
    capture_review(page, base, width)
    capture_whatif(page, base, width, live=width == max(VIEWPORTS))
    capture_proof(page, base, width)
    capture_negotiate(page, base, width)


def capture_mutating(page: Page, base: str, width: int) -> None:
    capture_approval(page, base, width)
    capture_review_accept(page, base, width)


def run(base: str, mutate: bool) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    log = Log(origin=origin)
    capture = capture_mutating if mutate else capture_read_only
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in VIEWPORTS.items():
            print(f"{width}x{height}")
            reset_server(base)
            context = browser.new_context(
                viewport={"width": width, "height": height}, reduced_motion="reduce", accept_downloads=False
            )
            page = context.new_page()
            page.on("request", lambda r: log.requests.append(r.url))
            page.on("console", lambda m: log.console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: log.console_errors.append(str(e)))
            capture(page, base, width)
            context.close()
        browser.close()
    reset_server(base)
    return report(log)


def report(log: Log) -> int:
    external = log.external()
    print(f"\nRequests: {len(log.requests)} total, {len(external)} to hosts other than {log.origin}")
    for url in sorted(set(external)):
        print(f"  EXTERNAL {url}")
    print(f"Console errors: {len(log.console_errors)}")
    for msg in log.console_errors:
        print(f"  {msg}")
    return 1 if external or log.console_errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mutate",
        action="store_true",
        help="record an approval and accept one review item (writes state on the server)",
    )
    args = parser.parse_args()
    return run(args.base_url.rstrip("/"), args.mutate)


if __name__ == "__main__":
    sys.exit(main())
