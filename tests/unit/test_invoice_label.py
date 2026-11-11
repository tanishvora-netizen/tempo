"""Invoice numbers must never render as dates (final fix pass, item 7)."""

import json
import re

import pytest

from tempo.precompute import OUT_DIR
from tempo.report import invoice_label

PLAIN_DATE = re.compile(r"^\s*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\s*$")
JS_FORMAT = OUT_DIR.parents[1] / "app" / "static" / "js" / "format.js"


@pytest.mark.parametrize("number", ["10/14/2026", "2026-11-10", "11.4.2026", "1/2/27"])
def test_date_like_numbers_get_an_explicit_label(number: str) -> None:
    assert invoice_label(number) == f"Invoice no. {number}"
    assert not PLAIN_DATE.match(invoice_label(number))


@pytest.mark.parametrize("number", ["FES-67182", "INV-2026-001", "A1"])
def test_ordinary_numbers_are_unchanged(number: str) -> None:
    assert invoice_label(number) == number


def test_no_bill_row_label_reads_as_a_date() -> None:
    bills = json.loads((OUT_DIR / "bundle.json").read_text())["bills"]
    assert any(PLAIN_DATE.match(b["invoice_number"]) for b in bills), "the demo keeps date-style numbers"
    for b in bills:
        assert not PLAIN_DATE.match(b["invoice_label"]), b["invoice_number"]


def test_the_browser_uses_the_same_rule() -> None:
    js = JS_FORMAT.read_text()
    assert "Invoice no. ${number}" in js
    assert r"/^\s*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\s*$/" in js
