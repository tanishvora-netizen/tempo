import pytest

from tempo.assumptions import SEED_A, SEED_B, SEED_C, SEED_D, SEED_FAN
from tempo.economics import annualized_return, break_even_discount, compounded_return
from tempo.optimize.stats import wilson_upper


def test_two_ten_net_thirty_is_37_24_percent_on_a_365_day_year() -> None:
    assert annualized_return(0.02, 10, 30) == pytest.approx(0.3724, abs=5e-5)


def test_treasury_360_day_basis_is_36_73_percent() -> None:
    assert annualized_return(0.02, 10, 30, days_in_year=360) == pytest.approx(0.3673, abs=5e-5)


def test_compounded_rate_is_44_6_percent() -> None:
    assert compounded_return(0.02, 10, 30) == pytest.approx(0.446, abs=5e-4)


def test_break_even_discount_at_8_percent_for_30_days() -> None:
    d = break_even_discount(0.08, 30)

    assert d == pytest.approx(0.006532, abs=5e-7)
    assert d < 0.08 * 30 / 365  # the shortcut overstates it


def test_annualized_return_rejects_empty_window() -> None:
    with pytest.raises(ValueError):
        annualized_return(0.02, 30, 30)


def test_wilson_bound_464_of_10000_passes_and_465_fails_at_5_percent() -> None:
    assert wilson_upper(464, 10_000, 1.645) <= 0.05
    assert wilson_upper(465, 10_000, 1.645) > 0.05


def test_wilson_bound_is_above_the_point_estimate_and_grows_with_z() -> None:
    assert wilson_upper(200, 10_000, 1.645) > 0.02
    assert wilson_upper(200, 10_000, 2.394) > wilson_upper(200, 10_000, 1.645)


def test_certification_seeds_are_distinct() -> None:
    seeds = [SEED_A, SEED_B, SEED_C, SEED_D, SEED_FAN]
    assert len(set(seeds)) == len(seeds)
