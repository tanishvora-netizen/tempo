from hypothesis import given
from hypothesis import strategies as st

from tempo.extract.numwords import normalize_number_words, original_span
from tempo.extract.regex_parser import PaymentTerms, parse_block

# Filler letters avoid every keyword the parser reacts to (net, n/, days, due, eom, prox, number words,
# OCR look-alikes O/o/I/l) so the embedded terms are the only thing to find.
FILLER = st.text(alphabet="abcfghjkmquvwxz \n,:", max_size=60)


@st.composite
def discount_terms(draw: st.DrawFn) -> tuple[int, int, int]:
    pct = draw(st.integers(min_value=1, max_value=5))
    days = draw(st.integers(min_value=5, max_value=20))
    net = draw(st.integers(min_value=days + 5, max_value=90))
    return pct, days, net


@given(discount_terms(), FILLER, FILLER)
def test_embedded_discount_terms_parse_exactly(terms: tuple[int, int, int], prefix: str, suffix: str) -> None:
    pct, days, net = terms
    written = f"{pct}/{days} net {net}"
    text = f"{prefix} {written} {suffix}"

    result = parse_block(text)

    expected = PaymentTerms(discount_bps=pct * 100, discount_days=days, net_days=net, anchor="invoice_date")
    assert [match.terms for match in result.terms] == [expected]
    span = result.terms[0].span
    assert text[span.start : span.end] == span.text == written
    assert span.start == len(prefix) + 1


@given(
    st.lists(st.sampled_from(["ten", "days", "forty-five", "often", "net", "tenth", "2", " "]), max_size=12)
)
def test_number_word_offsets_are_monotonic_and_cover_the_original(words: list[str]) -> None:
    text = " ".join(words)

    normalized, offsets = normalize_number_words(text)

    assert len(offsets) == len(normalized) + 1
    assert offsets == sorted(offsets)
    assert original_span(offsets, 0, len(normalized)) == (0, len(text))
