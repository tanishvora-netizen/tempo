import pytest

from tempo.extract.evidence import locate_quote, normalize_ws, quote_in_source

SOURCE = "INVOICE 1042\nTerms:   2/10\n  net 30\n\nPlease remit to Acme Supply"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  2/10\n net\t30  ", "2/10 net 30"),
        ("Terms:\r\n\r\nNet 30", "Terms: Net 30"),
        ("", ""),
        ("   \n\t ", ""),
        ("Net 30", "Net 30"),
    ],
)
def test_normalize_ws_collapses_whitespace_runs_and_strips(raw: str, expected: str) -> None:
    assert normalize_ws(raw) == expected


def test_normalize_ws_keeps_case() -> None:
    assert normalize_ws("NET  30") == "NET 30"


def test_quote_with_line_breaks_is_found_in_source() -> None:
    assert quote_in_source("Terms: 2/10 net 30", SOURCE)


def test_quote_with_its_own_line_breaks_is_found_in_source() -> None:
    assert quote_in_source("2/10\n\nnet   30", SOURCE)


def test_quote_not_present_is_rejected() -> None:
    assert not quote_in_source("1/10 net 30", SOURCE)


def test_quote_match_is_case_sensitive() -> None:
    assert not quote_in_source("TERMS: 2/10 NET 30", SOURCE)


@pytest.mark.parametrize("quote", [None, "", "   \n"])
def test_empty_or_missing_quote_is_rejected(quote: str | None) -> None:
    assert not quote_in_source(quote, SOURCE)


def test_locate_quote_returns_offsets_in_the_original_source() -> None:
    span = locate_quote("2/10 net 30", SOURCE)

    assert span is not None
    assert SOURCE[span.start : span.end] == span.text
    assert span.text == "2/10\n  net 30"


def test_locate_quote_returns_none_when_missing() -> None:
    assert locate_quote("Net 45", SOURCE) is None


@pytest.mark.parametrize("quote", [None, "", "  "])
def test_locate_quote_returns_none_for_empty_quote(quote: str | None) -> None:
    assert locate_quote(quote, SOURCE) is None


def test_locate_quote_ignores_surrounding_whitespace_in_the_quote() -> None:
    span = locate_quote("\n Please remit ", SOURCE)

    assert span is not None
    assert span.text == "Please remit"
