import pytest

from tempo.extract.numwords import normalize_number_words, original_span


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("two percent", "2 percent"),
        ("ten days", "10 days"),
        ("zero days", "0 days"),
        ("forty-five days", "45 days"),
        ("forty five days", "45 days"),
        ("Thirty Days", "30 Days"),
        ("one hundred twenty days", "120 days"),
        ("one hundred and twenty days", "120 days"),
        ("one-half percent", "0.5 percent"),
        ("one half percent", "0.5 percent"),
        ("half a percent", "0.5 percent"),
        ("one and a half percent", "1.5 percent"),
        ("tenth prox", "10th prox"),
        ("fifteenth of the month", "15th of the month"),
        ("twenty-first", "21st"),
        ("the second notice", "the 2nd notice"),
        ("thirty-third", "33rd"),
        ("eighteen percent", "18 percent"),
        ("seventy-two", "72"),
    ],
)
def test_normalizes_number_words(text: str, expected: str) -> None:
    normalized, _ = normalize_number_words(text)

    assert normalized == expected


@pytest.mark.parametrize(
    "text",
    ["often", "tone", "network", "someone", "attention", "Net 30", "the later half of the month"],
)
def test_leaves_words_that_only_contain_number_words_alone(text: str) -> None:
    normalized, offsets = normalize_number_words(text)

    assert normalized == text
    assert offsets == list(range(len(text) + 1))


def test_offset_map_has_one_entry_per_char_plus_end_sentinel() -> None:
    text = "pay within ten days"

    normalized, offsets = normalize_number_words(text)

    assert len(offsets) == len(normalized) + 1
    assert offsets[-1] == len(text)


def test_offset_map_round_trips_a_span_over_a_replaced_word() -> None:
    text = "2 percent off if settled within ten days, balance due in thirty days"
    normalized, offsets = normalize_number_words(text)
    start = normalized.index("10 days")

    original_start, original_end = original_span(offsets, start, start + len("10 days"))

    assert text[original_start:original_end] == "ten days"


def test_offset_map_round_trips_a_span_covering_the_whole_text() -> None:
    text = "forty-five days net"
    normalized, offsets = normalize_number_words(text)

    original_start, original_end = original_span(offsets, 0, len(normalized))

    assert (original_start, original_end) == (0, len(text))


def test_offset_map_round_trips_unchanged_text_after_a_replacement() -> None:
    text = "two percent within 10 days"
    normalized, offsets = normalize_number_words(text)
    start = normalized.index("within")

    original_start, original_end = original_span(offsets, start, start + len("within"))

    assert text[original_start:original_end] == "within"
