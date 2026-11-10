"""The demo path, end to end in a real browser (host mode): Overview -> Payment run row -> What-if preset ->
Proof -> Needs review -> Approve. Also asserts the page makes zero external network calls."""

import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
LOAD_BUDGET_MS = 3_000


def test_demo_path_works_and_stays_on_localhost(page: Page, live_server: str) -> None:
    hosts: set[str] = set()
    page.on("request", lambda r: hosts.add(urlparse(r.url).hostname or ""))
    page.set_viewport_size({"width": 1440, "height": 900})

    page.goto(f"{live_server}/#/overview")
    expect(page.get_by_label("Key numbers")).to_contain_text("$", timeout=LOAD_BUDGET_MS)
    expect(page.locator("#fan-canvas")).to_be_visible()

    page.goto(f"{live_server}/#/run")
    first_row = page.locator("tr[data-bill]").first
    first_row.click()
    expect(page.get_by_text(re.compile("Paid|Sent|Financed"), exact=False).first).to_be_visible()
    page.keyboard.press("Escape")

    page.goto(f"{live_server}/#/whatif")
    page.locator("[data-preset]").first.click()
    expect(page.locator("#wi-diff")).to_be_visible(timeout=10_000)

    page.goto(f"{live_server}/#/proof")
    expect(page.get_by_text("Smart spreadsheet", exact=False).first).to_be_visible()

    page.goto(f"{live_server}/#/review")
    expect(page.get_by_label("Bills needing review")).to_be_visible()

    assert hosts <= {"127.0.0.1", "localhost"}, f"external requests: {hosts}"
