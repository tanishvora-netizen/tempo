from tempo.agent.number_guard import FALLBACK, guard, numbers_in, template_problems
from tempo.llm.schemas import OfferTemplate

VALUES = {
    "VENDOR": "Tamarack Steel Supply",
    "INVOICE_NO": "TSS-10482",
    "AMOUNT": "$48,210.00",
    "DISC_PCT": "0.75%",
    "SAVINGS": "$361.58",
    "PAY_BY": "Nov 20, 2026",
    "NET_DAYS": "30",
}
CLEAN = OfferTemplate(
    subject_template="Early payment for invoice {INVOICE_NO}",
    body_template="Hi {VENDOR}, we can pay {AMOUNT} on {PAY_BY} for a {DISC_PCT} discount ({SAVINGS}). Net {NET_DAYS}.",
)


def test_clean_template_is_filled_with_code_numbers_only() -> None:
    out = guard(CLEAN, VALUES)

    assert not out.used_fallback
    assert "$48,210.00" in out.body and "0.75%" in out.body
    assert numbers_in(out.body) <= set().union(*(numbers_in(v) for v in VALUES.values()))


def test_rogue_digit_in_template_is_rejected_and_falls_back() -> None:
    rogue = OfferTemplate(
        subject_template="Offer", body_template="Pay by {PAY_BY} and get {DISC_PCT}, or 3% if faster."
    )

    out = guard(rogue, VALUES)

    assert out.used_fallback
    assert "digit" in out.problems[0]
    assert "3%" not in out.body


def test_number_words_are_rejected() -> None:
    sneaky = OfferTemplate(
        subject_template="Offer", body_template="Take two percent off: {DISC_PCT} by {PAY_BY}."
    )

    assert any("number words" in p for p in template_problems(sneaky))
    assert guard(sneaky, VALUES).used_fallback


def test_unknown_placeholder_is_rejected() -> None:
    bad = OfferTemplate(subject_template="Offer", body_template="{DISC_PCT} by {PAY_BY}, rate {APR}.")

    assert any("unknown placeholders" in p for p in template_problems(bad))


def test_fallback_template_itself_is_clean() -> None:
    assert template_problems(FALLBACK) == []
    assert guard(None, VALUES).used_fallback


def test_offer_that_says_it_saves_the_vendor_money_is_rejected() -> None:
    wrong = OfferTemplate(
        subject_template="Offer {INVOICE_NO}",
        body_template="Take {DISC_PCT} off; this will save you {SAVINGS} if paid by {PAY_BY}.",
    )

    out = guard(wrong, VALUES)

    assert out.used_fallback
    assert any("saves the vendor" in p for p in out.problems)
