"""Number-word normalization with an offset map back to the original text.

The deterministic parser only understands digits, so prose such as "two percent off if paid within ten
days" is rewritten to "2 percent off if paid within 10 days" first. Every rewrite is recorded in an offset
map so that a match found in the normalized text can be reported at its position in the original text.
"""

import re
from collections.abc import Sequence

_CARDINALS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}
_HUNDRED = 100


def _alternation(words: Sequence[str]) -> str:
    """Longest words first so a regex alternation never stops at a shorter prefix ("four" vs "fourteen")."""
    return "|".join(sorted(words, key=len, reverse=True))


_UNIT = _alternation([word for word, value in _CARDINALS.items() if 1 <= value <= 9])
_TEEN = _alternation([word for word, value in _CARDINALS.items() if 10 <= value <= 19])
_TENS = _alternation([word for word, value in _CARDINALS.items() if value >= 20])
_ORD_UNIT = _alternation([word for word, value in _ORDINALS.items() if value <= 9])
_ORD_REST = _alternation([word for word, value in _ORDINALS.items() if value >= 10])

_JOIN = r"[-\s]+"
_PERCENT_AHEAD = r"(?=\s*(?:%|percent\b|per\s+cent\b))"
_BELOW_HUNDRED = (
    rf"(?:(?:{_TENS}){_JOIN}(?:{_ORD_UNIT}|{_UNIT})|{_ORD_REST}|{_ORD_UNIT}|{_TENS}|{_TEEN}|{_UNIT}|zero)"
)
_NUMBER = rf"(?:(?:{_UNIT})\s+hundred(?:(?:\s+and)?\s+{_BELOW_HUNDRED})?|{_BELOW_HUNDRED})"

_NUMBER_PHRASE = re.compile(
    rf"\b(?:"
    rf"(?P<and_half>{_NUMBER})\s+and\s+(?:a|one){_JOIN}half{_PERCENT_AHEAD}"
    rf"|(?P<half>one{_JOIN}half|a\s+half|half\s+(?:a|of\s+(?:a|one))){_PERCENT_AHEAD}"
    rf"|(?P<number>{_NUMBER})"
    rf")\b",
    re.IGNORECASE,
)


def normalize_number_words(text: str) -> tuple[str, list[int]]:
    """Rewrite number words as digits and return the new text with its offset map.

    Covers zero..ninety-nine (hyphenated or spaced: "forty-five", "forty five"), "N hundred [and] M",
    ordinals ("tenth" -> "10th", "twenty-first" -> "21st") and half percents ("one-half percent" and
    "half a percent" -> "0.5 percent", "one and a half percent" -> "1.5 percent"). Only whole words change,
    so "often", "tone" and "network" are left alone.

    The offset map has one entry per character of the normalized text, giving that character's index in
    the original, plus a final sentinel equal to ``len(text)``; use :func:`original_span` to map a span.
    """
    pieces: list[str] = []
    offsets: list[int] = []
    cursor = 0
    for match in _NUMBER_PHRASE.finditer(text):
        replacement = _render(match)
        pieces.append(text[cursor : match.start()])
        offsets.extend(range(cursor, match.start()))
        pieces.append(replacement)
        offsets.extend(_replacement_offsets(match.start(), match.end(), len(replacement)))
        cursor = match.end()
    pieces.append(text[cursor:])
    offsets.extend(range(cursor, len(text) + 1))
    return "".join(pieces), offsets


def original_span(offsets: Sequence[int], start: int, end: int) -> tuple[int, int]:
    """Map a ``[start, end)`` span of normalized text to the matching span of the original text."""
    if not 0 <= start <= end < len(offsets):
        raise ValueError(f"span ({start}, {end}) is outside the offset map of length {len(offsets)}")
    return offsets[start], offsets[end]


def _replacement_offsets(start: int, end: int, length: int) -> list[int]:
    """Point each replacement character at the original word, never past its last character."""
    last = end - 1
    return [min(start + index, last) for index in range(length)]


def _render(match: re.Match[str]) -> str:
    if match["half"] is not None:
        return "0.5"
    if match["and_half"] is not None:
        value, _ = _number_value(match["and_half"])
        return f"{value}.5"
    value, is_ordinal = _number_value(match["number"])
    return f"{value}{_ordinal_suffix(value)}" if is_ordinal else str(value)


def _number_value(phrase: str) -> tuple[int, bool]:
    """Value of a phrase the number regex accepted, and whether it ends in an ordinal word."""
    words = [word for word in re.split(r"[-\s]+", phrase.casefold()) if word != "and"]
    total = 0
    for word in words:
        if word == "hundred":
            total *= _HUNDRED
        else:
            total += _CARDINALS[word] if word in _CARDINALS else _ORDINALS[word]
    return total, words[-1] in _ORDINALS


def _ordinal_suffix(value: int) -> str:
    if value % 100 in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
