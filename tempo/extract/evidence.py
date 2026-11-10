"""Quote verification: does a quote the model returned really appear in the source text?

Comparison ignores differences in whitespace (line breaks, tabs, repeated spaces) but nothing else: case and
punctuation must match exactly.
"""

import re

from tempo.extract.regex_parser import Span


def normalize_ws(s: str) -> str:
    """Collapse every whitespace run to a single space and strip the ends. Case is preserved."""
    return " ".join(s.split())


def quote_in_source(quote: str | None, source: str) -> bool:
    """True iff the whitespace-normalized quote is a non-empty substring of the normalized source."""
    normalized_quote = normalize_ws(quote or "")
    return bool(normalized_quote) and normalized_quote in normalize_ws(source)


def locate_quote(quote: str | None, source: str) -> Span | None:
    """Find the quote in the source, allowing any whitespace run to stand for any other.

    Returns the span in the ORIGINAL source (so the UI can highlight it), or None when the quote is empty
    or absent.
    """
    words = (quote or "").split()
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), source)
    if match is None:
        return None
    return Span(match.start(), match.end(), match[0])
