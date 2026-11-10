"""Deterministic parser for payment terms and related facts in one source block of an invoice or email.

Every match is kept with its character offsets in the ORIGINAL block text: the UI highlights them, and two
or more distinct terms in a block is a review signal. The parser reports what is written; sanity checks
(an absurd discount, a discount longer than the net period) belong to reconciliation, not here.

Text passes through three pre-passes before matching. The first two keep the length, so offsets stay valid;
the number-word pass returns an offset map:
  1. OCR repair inside digit context: O/o -> 0 and I/l -> 1 ("2/1O net 3O", "Net3O"); words never change.
  2. Fraction repair: "1/2%" is one-half percent, rewritten to "0.5%" ("1 1/2%" becomes "1.5  %").
  3. Number words: "two percent off within ten days" -> "2 percent off within 10 days".
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from tempo.extract.numwords import normalize_number_words, original_span

Anchor = Literal["invoice_date", "eom", "prox", "receipt"]
Method = Literal["ACH", "CARD", "CHECK", "WIRE"]

EOM_DEFAULT_NET_DAYS = 30
MONTHS_PER_YEAR = 12
BPS_PER_PERCENT = 100
CENTS_PER_DOLLAR = 100


@dataclass(frozen=True)
class Span:
    """A ``[start, end)`` slice of the original block text; ``text == original[start:end]``."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class PaymentTerms:
    """Payment terms as written. ``net_days`` is None for prox terms, which use ``prox_day`` instead."""

    discount_bps: int | None
    discount_days: int | None
    net_days: int | None
    anchor: Anchor
    prox_day: int | None = None


@dataclass(frozen=True)
class TermsMatch:
    terms: PaymentTerms
    span: Span


@dataclass(frozen=True)
class LateFee:
    """A late fee: a monthly percentage in basis points, or a flat amount in cents."""

    kind: Literal["pct_month", "flat"]
    pct_month_bps: int | None
    flat_cents: int | None
    converted_from_annual: bool


@dataclass(frozen=True)
class LateFeeMatch:
    fee: LateFee
    span: Span


@dataclass(frozen=True)
class SurchargeMatch:
    bps: int
    span: Span


@dataclass(frozen=True)
class MethodMatch:
    method: Method
    span: Span


@dataclass(frozen=True)
class CardDiscountMatch:
    allowed: bool
    span: Span


@dataclass(frozen=True)
class CurrencyMatch:
    code: str
    span: Span


@dataclass(frozen=True)
class BlockParse:
    """Every match found in one block, each category ordered by position."""

    terms: tuple[TermsMatch, ...]
    late_fees: tuple[LateFeeMatch, ...]
    surcharges: tuple[SurchargeMatch, ...]
    methods: tuple[MethodMatch, ...]
    card_discount: tuple[CardDiscountMatch, ...]
    currencies: tuple[CurrencyMatch, ...]

    def distinct_terms(self) -> frozenset[PaymentTerms]:
        """The set of different terms written in the block; more than one means the block is ambiguous."""
        return frozenset(match.terms for match in self.terms)


# ---------------------------------------------------------------------------------------------------------
# Pre-passes
# ---------------------------------------------------------------------------------------------------------

_OCR_DIGIT_RUN = re.compile(r"(?:(?<![A-Za-z])[OoIl]+)?\d[\dOoIl]*(?=(?:st|nd|rd|th)\b|[^A-Za-z]|$)")
_OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})
_HALF_PERCENT = re.compile(
    r"(?<![\d./])(?:(?P<whole>\d{1,2})\s+)?1/2(?=\s*(?:%|percent\b|per\s+cent\b))", re.IGNORECASE
)


def _repair_ocr_digits(text: str) -> str:
    """Map letter look-alikes to digits inside runs that already contain a digit (length-preserving)."""
    return _OCR_DIGIT_RUN.sub(lambda match: match[0].translate(_OCR_DIGITS), text)


def _repair_half_percent(text: str) -> str:
    """Rewrite "1/2%" as "0.5%" and "1 1/2%" as "1.5  %" (length-preserving)."""

    def replace(match: re.Match[str]) -> str:
        whole = match["whole"]
        value = f"{whole}.5" if whole else "0.5"
        return value.ljust(len(match[0]))

    return _HALF_PERCENT.sub(replace, text)


@dataclass(frozen=True)
class _PreparedText:
    original: str
    text: str
    offsets: tuple[int, ...]

    def span(self, start: int, end: int) -> Span:
        original_start, original_end = original_span(self.offsets, start, end)
        return Span(original_start, original_end, self.original[original_start:original_end])


def _prepare(original: str) -> _PreparedText:
    normalized, offsets = normalize_number_words(_repair_half_percent(_repair_ocr_digits(original)))
    return _PreparedText(original=original, text=normalized, offsets=tuple(offsets))


# ---------------------------------------------------------------------------------------------------------
# Shared pattern fragments
# ---------------------------------------------------------------------------------------------------------

_NUMBER_START = r"(?<![\w.#/])(?<!no\.\s)(?<!#\s)"
_PCT = r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)"
_PCT_UNIT = r"(?:%|percent\b|per\s+cent\b)"
_SEP = r"\s*[,;\-]?\s*"
_EOM = r"(?:e\.o\.m\.?|eom\b|end\s+of\s+(?:the\s+)?month\b)"
_DAYS_WORD = r"(?:\s*(?:calendar\s+)?days?\b)?"
_NOT_DATE_OR_AMOUNT = r"(?![\d/]|[.,]\d|\s*/\s*\d|(?:st|nd|rd|th)\b)"
_CARD = r"(?:(?:credit\s*/\s*debit|credit|debit)\s+)?cards?"
_DISCOUNT_WORD = r"(?:(?:early|prompt|cash)[-\s]+(?:payment\s+)?)?discount"


def _net_clause(group: str) -> str:
    """'net 30', 'Net30', 'n/30', 'n30' with the day count captured in ``group``."""
    return rf"(?<![\w/])(?:net\s*|n\s*/\s*|n(?=\d))(?P<{group}>\d{{1,3}}){_NOT_DATE_OR_AMOUNT}{_DAYS_WORD}"


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------------
# Generic rule engine
# ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule[T]:
    pattern: re.Pattern[str]
    build: Callable[[re.Match[str]], T]
    priority: int = 0


@dataclass(frozen=True)
class _Candidate[T]:
    start: int
    end: int
    priority: int
    value: T


def _scan[T](prepared: _PreparedText, rules: Sequence[_Rule[T]]) -> list[tuple[T, Span]]:
    """Run every rule, drop matches overlapping a stronger one, and return the rest in text order."""
    candidates = [
        _Candidate(match.start(), match.end(), rule.priority, rule.build(match))
        for rule in rules
        for match in rule.pattern.finditer(prepared.text)
    ]
    kept = _non_overlapping(candidates)
    return [(candidate.value, prepared.span(candidate.start, candidate.end)) for candidate in kept]


def _non_overlapping[T](candidates: Sequence[_Candidate[T]]) -> list[_Candidate[T]]:
    """Greedy pick by priority then length, so "2/10 net 30" never also yields a bare "net 30"."""
    ranked = sorted(candidates, key=lambda c: (-c.priority, -(c.end - c.start), c.start))
    kept: list[_Candidate[T]] = []
    for candidate in ranked:
        if all(candidate.end <= other.start or candidate.start >= other.end for other in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda c: c.start)


def _pct_to_bps(pct: str) -> int:
    return int(Decimal(pct) * BPS_PER_PERCENT)


def _dollars_to_cents(amount: str) -> int:
    return int(Decimal(amount.replace(",", "")) * CENTS_PER_DOLLAR)


# ---------------------------------------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------------------------------------

_PRIORITY_DISCOUNT = 3
_PRIORITY_SPECIAL = 2
_PRIORITY_NET_ONLY = 1

_DISCOUNT_TERMS = _compile(
    rf"{_NUMBER_START}{_PCT}(?:\s*{_PCT_UNIT}\s*[/,;]?|\s*/)\s*(?P<days>\d{{1,3}}){_NOT_DATE_OR_AMOUNT}"
    rf"{_DAYS_WORD}{_SEP}"
    rf"(?:(?P<eom_a>{_EOM})(?:{_SEP}{_net_clause('net_a')})?"
    rf"|{_net_clause('net_b')}(?:{_SEP}(?:after\s+)?(?P<eom_b>{_EOM}))?)"
)
_NET_ONLY = _compile(rf"{_net_clause('net')}(?:{_SEP}(?:after\s+)?(?P<eom>{_EOM}))?")
_DAYS_NET = _compile(r"(?<![\w.#/])(?P<net>\d{1,3})\s*days?\s+net\b(?!\s*\d)")
_DUE_WITHIN = _compile(
    r"\b(?:due|payable)\s+(?:(?:with)?in\s+)?(?P<net>\d{1,3})(?![\d/]|[.,]\d)\s*(?:calendar\s+)?days?\b"
)
_RECEIPT = _compile(r"\b(?:due|payable)\s+(?:(?:up)?on|at)\s+receipt\b")
_PROX = _compile(
    r"(?<![\w/.])(?:net\s*)?(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?:prox(?:imo)?\b|of\s+(?:the\s+)?(?:following|next)\s+month\b)"
)


def _sentence_gap(limit: int) -> str:
    """Up to ``limit`` characters that do not cross a sentence end (a ". " but not the "." in "1.5")."""
    return rf"(?:(?![.!?](?:\s|$))[\s\S]){{0,{limit}}}?"


_CLAUSE_GAP = _sentence_gap(80)
_NEXT_SENTENCE_GAP = rf"{_sentence_gap(120)}(?:[.!?]\s+{_sentence_gap(120)})?"
_PROSE_DISCOUNT_FORMS = (
    rf"(?<![\w.]){_PCT}\s*{_PCT_UNIT}\s+(?:{_DISCOUNT_WORD}|off)\b",
    rf"\b(?:discount|reduction)\s+of\s+{_PCT}\s*{_PCT_UNIT}",
)
_PROSE_WINDOW = r"\b(?:with)?in\s+(?P<days>\d{1,3})\s*(?:calendar\s+|business\s+)?days?\b"
_PROSE_NET = (
    r"\b(?:(?:due|payable|required|owed|expected)\s+(?:(?:with)?in\s+)?|net\s*)"
    rf"(?P<net>\d{{1,3}})(?![\d/]|[.,]\d){_DAYS_WORD}"
)
_PROSE_TERMS = tuple(
    _compile(pattern)
    for discount in _PROSE_DISCOUNT_FORMS
    for pattern in (
        rf"{discount}{_CLAUSE_GAP}{_PROSE_WINDOW}{_NEXT_SENTENCE_GAP}{_PROSE_NET}",
        rf"{_PROSE_WINDOW}{_CLAUSE_GAP}{discount}{_NEXT_SENTENCE_GAP}{_PROSE_NET}",
        rf"{_PROSE_NET}{_NEXT_SENTENCE_GAP}{discount}{_CLAUSE_GAP}{_PROSE_WINDOW}",
    )
)


def _discount_terms(match: re.Match[str]) -> PaymentTerms:
    """Structured discount terms. "2/10 EOM" means net 30 days after the end of the month (convention)."""
    net = match["net_a"] or match["net_b"]
    is_eom = bool(match["eom_a"] or match["eom_b"])
    return PaymentTerms(
        discount_bps=_pct_to_bps(match["pct"]),
        discount_days=int(match["days"]),
        net_days=int(net) if net else EOM_DEFAULT_NET_DAYS,
        anchor="eom" if is_eom else "invoice_date",
    )


def _prose_terms(match: re.Match[str]) -> PaymentTerms:
    return PaymentTerms(
        discount_bps=_pct_to_bps(match["pct"]),
        discount_days=int(match["days"]),
        net_days=int(match["net"]),
        anchor="invoice_date",
    )


def _net_only_terms(match: re.Match[str]) -> PaymentTerms:
    is_eom = match.groupdict().get("eom") is not None
    return PaymentTerms(None, None, int(match["net"]), "eom" if is_eom else "invoice_date")


def _receipt_terms(_: re.Match[str]) -> PaymentTerms:
    return PaymentTerms(None, None, 0, "receipt")


def _prox_terms(match: re.Match[str]) -> PaymentTerms:
    return PaymentTerms(None, None, None, "prox", prox_day=int(match["day"]))


_TERMS_RULES: tuple[_Rule[PaymentTerms], ...] = (
    _Rule(_DISCOUNT_TERMS, _discount_terms, _PRIORITY_DISCOUNT),
    *(_Rule(pattern, _prose_terms, _PRIORITY_SPECIAL) for pattern in _PROSE_TERMS),
    _Rule(_PROX, _prox_terms, _PRIORITY_SPECIAL),
    _Rule(_RECEIPT, _receipt_terms, _PRIORITY_SPECIAL),
    _Rule(_NET_ONLY, _net_only_terms, _PRIORITY_NET_ONLY),
    _Rule(_DAYS_NET, _net_only_terms, _PRIORITY_NET_ONLY),
    _Rule(_DUE_WITHIN, _net_only_terms, _PRIORITY_NET_ONLY),
)


# ---------------------------------------------------------------------------------------------------------
# Late fees, surcharges, card discount, methods, currency
# ---------------------------------------------------------------------------------------------------------

_RATE = rf"(?<![\w.]){_PCT}\s*{_PCT_UNIT}\s*(?:interest\s+)?"
_AMOUNT = r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
_LATE_WORDS = r"late\s+(?:payment\s+)?(?:fee|charge)"
_MONTHLY_RATE = _compile(
    rf"{_RATE}(?:per\s+month|a\s+month|each\s+month|monthly|per\s+mo\b\.?|/\s*mo(?:nth)?\b\.?)"
)
_ANNUAL_RATE = _compile(rf"{_RATE}(?:per\s+annum|per\s+year|a\s+year|annually|annual\b|p\.a\.|APR\b)")
_FLAT_FEE_AFTER = _compile(rf"\$\s*{_AMOUNT}\s+{_LATE_WORDS}\b")
_FLAT_FEE_BEFORE = _compile(rf"\b{_LATE_WORDS}\s+of\s+\$\s*{_AMOUNT}")


def _monthly_fee(match: re.Match[str]) -> LateFee:
    return LateFee("pct_month", _pct_to_bps(match["pct"]), None, converted_from_annual=False)


def _annual_fee(match: re.Match[str]) -> LateFee:
    """An annual rate becomes a monthly rate (divide by 12, round half up) and is flagged as converted."""
    monthly = (Decimal(_pct_to_bps(match["pct"])) / MONTHS_PER_YEAR).quantize(Decimal(1), ROUND_HALF_UP)
    return LateFee("pct_month", int(monthly), None, converted_from_annual=True)


def _flat_fee(match: re.Match[str]) -> LateFee:
    return LateFee("flat", None, _dollars_to_cents(match["amount"]), converted_from_annual=False)


_LATE_FEE_RULES: tuple[_Rule[LateFee], ...] = (
    _Rule(_MONTHLY_RATE, _monthly_fee),
    _Rule(_ANNUAL_RATE, _annual_fee),
    _Rule(_FLAT_FEE_AFTER, _flat_fee),
    _Rule(_FLAT_FEE_BEFORE, _flat_fee),
)

_FEE_KIND = r"(?:(?:processing|convenience|service|transaction|handling)\s+)?"
_SURCHARGE_WORD = r"(?:surcharge|fee)\b"
_SURCHARGE_PATTERNS = (
    rf"(?<![\w.]){_PCT}\s*{_PCT_UNIT}\s+{_CARD}\s+{_FEE_KIND}{_SURCHARGE_WORD}",
    rf"(?<![\w.]){_PCT}\s*{_PCT_UNIT}\s+{_FEE_KIND}{_SURCHARGE_WORD}\s+"
    rf"(?:on|for|to|appl(?:ies|ied)\s+to|(?:when|if)\s+pa(?:ying|id)\s+(?:by|with))\s+(?:all\s+)?{_CARD}",
    rf"\b{_CARD}\s+(?:payments?|transactions?|purchases?)\b[^.\n%]{{0,40}}?"
    rf"(?<![\w.]){_PCT}\s*{_PCT_UNIT}\s+{_FEE_KIND}{_SURCHARGE_WORD}",
    rf"\bsurcharge\s+of\s+{_PCT}\s*{_PCT_UNIT}[^.\n]{{0,40}}?\b{_CARD}",
)
_SURCHARGE_RULES: tuple[_Rule[int], ...] = tuple(
    _Rule(_compile(pattern), lambda match: _pct_to_bps(match["pct"])) for pattern in _SURCHARGE_PATTERNS
)

_CARD_PAYMENTS = rf"{_CARD}(?:\s+payments?)?"
_CARD_DISCOUNT_ALLOWED = (
    rf"\bdiscount\s+(?:also\s+)?(?:applies|apply|is\s+available|available|(?:is\s+)?valid|(?:is\s+)?honou?red)"
    rf"\s+(?:to|on|for|with)\s+{_CARD_PAYMENTS}",
    rf"\b{_CARD_PAYMENTS}\s+(?:are\s+|is\s+)?(?:eligible|qualify|qualifies)\s+for\s+(?:the\s+)?{_DISCOUNT_WORD}",
)
_CARD_DISCOUNT_DENIED = (
    rf"\bdiscount\s+(?:is\s+not|isn['’]t|does\s+not|doesn['’]t|not)\s+"
    rf"(?:available|valid|apply|applicable|offered|honou?red)\s+(?:to|on|for|with)\s+{_CARD_PAYMENTS}",
    rf"\bdiscount\s+(?:is\s+)?(?:void|forfeited)\s+(?:if|when)\s+paid\s+(?:by|with)\s+{_CARD_PAYMENTS}",
    rf"\bno\s+{_DISCOUNT_WORD}\s+(?:on|for)\s+{_CARD_PAYMENTS}",
    rf"\b{_CARD_PAYMENTS}\s+(?:are\s+|is\s+)?(?:not\s+eligible|ineligible)\s+for\s+(?:the\s+)?{_DISCOUNT_WORD}",
)
_CARD_DISCOUNT_RULES: tuple[_Rule[bool], ...] = (
    *(_Rule(_compile(pattern), lambda _: True) for pattern in _CARD_DISCOUNT_ALLOWED),
    *(_Rule(_compile(pattern), lambda _: False) for pattern in _CARD_DISCOUNT_DENIED),
)

_METHODS = _compile(
    r"(?P<ACH>\bACH\b|\bbank\s+transfers?\b|\bdirect\s+deposits?\b)"
    r"|(?P<CARD>\b(?:credit|debit)\s+cards?\b|\bvisa\b|\bmaster\s?card\b|\bamex\b|\bamerican\s+express\b"
    r"|\bcards?\b)"
    r"|(?P<CHECK>\bche(?:ck|que)s?\b)"
    r"|(?P<WIRE>\bwire(?:\s+transfers?)?\b|\bwires\b)"
)
_CURRENCIES = re.compile(r"(?P<USD>\bUSD\b|\bUS\$|\$)|(?P<EUR>\bEUR\b)|(?P<GBP>\bGBP\b)|(?P<CAD>\bCAD\b)")


_METHOD_BY_GROUP: dict[str, Method] = {"ACH": "ACH", "CARD": "CARD", "CHECK": "CHECK", "WIRE": "WIRE"}


def _group_name(match: re.Match[str]) -> str:
    name = match.lastgroup
    if name is None:
        raise ValueError(f"pattern matched {match[0]!r} without a named alternative")
    return name


def _method(match: re.Match[str]) -> Method:
    return _METHOD_BY_GROUP[_group_name(match)]


_METHOD_RULES: tuple[_Rule[Method], ...] = (_Rule(_METHODS, _method),)
_CURRENCY_RULES: tuple[_Rule[str], ...] = (_Rule(_CURRENCIES, _group_name),)


# ---------------------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------------------


def parse_block(text: str) -> BlockParse:
    """Parse one source block (invoice header, body, footer, payment box, or one email message).

    Returns every terms, late fee, card surcharge, payment method, card-discount and currency mention with
    its span in ``text``. Overlapping matches of the same category collapse to the strongest one, so
    "2/10 net 30" yields one terms match, not also a separate "net 30".
    """
    prepared = _prepare(text)
    return BlockParse(
        terms=tuple(TermsMatch(value, span) for value, span in _scan(prepared, _TERMS_RULES)),
        late_fees=tuple(LateFeeMatch(value, span) for value, span in _scan(prepared, _LATE_FEE_RULES)),
        surcharges=tuple(SurchargeMatch(value, span) for value, span in _scan(prepared, _SURCHARGE_RULES)),
        methods=tuple(MethodMatch(value, span) for value, span in _scan(prepared, _METHOD_RULES)),
        card_discount=tuple(
            CardDiscountMatch(value, span) for value, span in _scan(prepared, _CARD_DISCOUNT_RULES)
        ),
        currencies=tuple(CurrencyMatch(value, span) for value, span in _scan(prepared, _CURRENCY_RULES)),
    )
