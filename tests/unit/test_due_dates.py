from datetime import date

import pytest

from tempo.extract.due_dates import discount_deadline, due_date
from tempo.extract.regex_parser import PaymentTerms

TWO_TEN_NET_30 = PaymentTerms(discount_bps=200, discount_days=10, net_days=30, anchor="invoice_date")
NET_45 = PaymentTerms(discount_bps=None, discount_days=None, net_days=45, anchor="invoice_date")
TWO_TEN_EOM = PaymentTerms(discount_bps=200, discount_days=10, net_days=30, anchor="eom")
NET_30_EOM = PaymentTerms(discount_bps=None, discount_days=None, net_days=30, anchor="eom")
NET_10TH_PROX = PaymentTerms(discount_bps=None, discount_days=None, net_days=None, anchor="prox", prox_day=10)
PROX_31 = PaymentTerms(discount_bps=None, discount_days=None, net_days=None, anchor="prox", prox_day=31)
DUE_ON_RECEIPT = PaymentTerms(discount_bps=None, discount_days=None, net_days=0, anchor="receipt")


def test_invoice_date_terms_count_from_the_issue_date() -> None:
    issued = date(2026, 11, 3)

    assert discount_deadline(issued, TWO_TEN_NET_30) == date(2026, 11, 13)
    assert due_date(issued, TWO_TEN_NET_30) == date(2026, 12, 3)


def test_net_only_terms_have_no_discount_deadline() -> None:
    issued = date(2026, 11, 3)

    assert discount_deadline(issued, NET_45) is None
    assert due_date(issued, NET_45) == date(2026, 12, 18)


def test_two_ten_eom_counts_from_the_end_of_the_issue_month() -> None:
    issued = date(2026, 11, 17)

    assert discount_deadline(issued, TWO_TEN_EOM) == date(2026, 12, 10)
    assert due_date(issued, TWO_TEN_EOM) == date(2026, 12, 30)


def test_net_30_eom_counts_from_the_end_of_the_issue_month() -> None:
    assert due_date(date(2026, 10, 28), NET_30_EOM) == date(2026, 11, 30)


def test_eom_rolls_a_month_after_the_25th_when_enabled() -> None:
    issued = date(2026, 10, 28)

    assert due_date(issued, NET_30_EOM, roll_after_25th=True) == date(2026, 12, 30)
    assert discount_deadline(issued, TWO_TEN_EOM, roll_after_25th=True) == date(2026, 12, 10)


def test_eom_does_not_roll_on_the_25th_itself() -> None:
    assert due_date(date(2026, 10, 25), NET_30_EOM, roll_after_25th=True) == date(2026, 11, 30)


def test_net_10th_prox_is_due_on_the_10th_of_the_next_month() -> None:
    issued = date(2026, 11, 20)

    assert due_date(issued, NET_10TH_PROX) == date(2026, 12, 10)
    assert discount_deadline(issued, NET_10TH_PROX) is None


def test_prox_day_is_clamped_to_the_length_of_the_due_month() -> None:
    assert due_date(date(2026, 1, 31), PROX_31) == date(2026, 2, 28)


def test_prox_crosses_the_year_boundary() -> None:
    assert due_date(date(2026, 12, 5), NET_10TH_PROX) == date(2027, 1, 10)


@pytest.mark.parametrize(
    ("issued", "roll", "expected"),
    [
        (date(2026, 11, 26), False, date(2026, 12, 10)),
        (date(2026, 11, 26), True, date(2027, 1, 10)),
        (date(2026, 11, 25), True, date(2026, 12, 10)),
    ],
)
def test_prox_roll_after_25th_toggle(issued: date, roll: bool, expected: date) -> None:
    assert due_date(issued, NET_10TH_PROX, roll_after_25th=roll) == expected


def test_due_on_receipt_is_due_on_the_issue_date_with_no_discount() -> None:
    issued = date(2026, 11, 3)

    assert due_date(issued, DUE_ON_RECEIPT) == issued
    assert discount_deadline(issued, DUE_ON_RECEIPT) is None


def test_invoice_date_terms_without_net_days_are_rejected() -> None:
    broken = PaymentTerms(discount_bps=200, discount_days=10, net_days=None, anchor="invoice_date")

    with pytest.raises(ValueError, match="net_days"):
        due_date(date(2026, 11, 3), broken)


def test_prox_terms_without_prox_day_are_rejected() -> None:
    broken = PaymentTerms(discount_bps=None, discount_days=None, net_days=None, anchor="prox")

    with pytest.raises(ValueError, match="prox_day"):
        due_date(date(2026, 11, 3), broken)
