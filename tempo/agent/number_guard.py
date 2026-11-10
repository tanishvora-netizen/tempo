"""Number guard for model-written prose (directive 7.5). The model never writes a number.

The model returns a subject and body using only placeholders. Code:
1. rejects a template that contains any digit, number word, or unknown placeholder;
2. fills the placeholders from computed values;
3. extracts every number from the final text and checks each against the numbers code supplied.
Any failure falls back to a deterministic template, so a rogue number can never reach a vendor.
"""

import re
from dataclasses import dataclass

from tempo.llm.schemas import OfferTemplate

PLACEHOLDERS = ("VENDOR", "INVOICE_NO", "AMOUNT", "DISC_PCT", "SAVINGS", "PAY_BY", "NET_DAYS")
_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million "
    "half quarter dozen first second third fourth fifth tenth".split()
)

FALLBACK = OfferTemplate(
    subject_template="Early payment offer for invoice {INVOICE_NO}",
    body_template=(
        "Hello {VENDOR},\n\nWe would like to pay invoice {INVOICE_NO} for {AMOUNT} early, on {PAY_BY}, instead of "
        "on its net {NET_DAYS} due date, in exchange for a {DISC_PCT} early-payment discount (a {SAVINGS} "
        "reduction). Payment would arrive instantly by RTP into your bank account, with no fee to you.\n\n"
        "If that works, a short reply confirming the discount is all we need.\n\nThank you,\nAccounts Payable"
    ),
)


@dataclass(frozen=True)
class GuardedText:
    subject: str
    body: str
    used_fallback: bool
    problems: tuple[str, ...]


def template_problems(t: OfferTemplate) -> list[str]:
    """Why a model template is unusable (empty list if it is clean)."""
    problems = []
    for name, text in (("subject", t.subject_template), ("body", t.body_template)):
        if re.search(r"\d", text):
            problems.append(f"{name} contains a digit")
        words = {w.lower() for w in re.findall(r"[A-Za-z]+", _PLACEHOLDER.sub(" ", text))}
        found = sorted(words & NUMBER_WORDS)
        if found:
            problems.append(f"{name} contains number words: {', '.join(found)}")
        unknown = sorted(set(_PLACEHOLDER.findall(text)) - set(PLACEHOLDERS))
        if unknown:
            problems.append(f"{name} uses unknown placeholders: {', '.join(unknown)}")
    if "{DISC_PCT}" not in t.body_template or "{PAY_BY}" not in t.body_template:
        problems.append("body must state {DISC_PCT} and {PAY_BY}")
    return problems


def numbers_in(text: str) -> set[str]:
    """Every number token in a text, normalized by dropping thousands separators."""
    return {m.replace(",", "") for m in _NUMBER.findall(text)}


def fill(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def guard(candidate: OfferTemplate | None, values: dict[str, str]) -> GuardedText:
    """Fill the model's template if it is clean and every number in the result came from `values`;
    otherwise fill the deterministic fallback."""
    allowed = set().union(*(numbers_in(v) for v in values.values()))
    problems = template_problems(candidate) if candidate is not None else ["no model template"]
    if not problems and candidate is not None:
        subject, body = fill(candidate.subject_template, values), fill(candidate.body_template, values)
        rogue = sorted(numbers_in(subject + "\n" + body) - allowed)
        if not rogue:
            return GuardedText(subject, body, False, ())
        problems = [f"numbers not supplied by code: {', '.join(rogue)}"]
    subject, body = fill(FALLBACK.subject_template, values), fill(FALLBACK.body_template, values)
    return GuardedText(subject, body, True, tuple(problems))
