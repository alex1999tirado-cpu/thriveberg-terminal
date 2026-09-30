from __future__ import annotations

from datetime import date

from ajax_terminal.analytics.fixed_income import (
    analyze_bond,
    bootstrap_zero_rates,
    clean_price_from_ytm,
    dv01,
    ytm_from_price,
)


def test_par_bond_prices_near_par_on_coupon_date() -> None:
    settlement = date(2024, 1, 1)
    maturity = date(2029, 1, 1)

    price = clean_price_from_ytm(100.0, 0.05, 0.05, settlement, maturity, frequency=1)

    assert round(price, 6) == 100.0


def test_ytm_solver_recovers_input_yield() -> None:
    settlement = date(2024, 1, 1)
    maturity = date(2029, 1, 1)
    price = clean_price_from_ytm(100.0, 0.0425, 0.0475, settlement, maturity, frequency=2)

    solved = ytm_from_price(price, 100.0, 0.0425, settlement, maturity, frequency=2)

    assert abs(solved - 0.0475) < 1e-7


def test_duration_and_dv01_are_positive() -> None:
    settlement = date(2024, 1, 1)
    maturity = date(2034, 1, 1)

    analytics = analyze_bond(98.5, 0.0425, settlement, maturity)
    point_value = dv01(100.0, 0.0425, analytics.ytm, settlement, maturity)

    assert analytics.modified_duration > 0
    assert analytics.convexity > 0
    assert analytics.dv01 > 0
    assert point_value > 0


def test_bootstrap_zero_rates_preserves_a_flat_par_curve() -> None:
    zero_rates = bootstrap_zero_rates(
        {1.0: 4.0, 2.0: 4.0, 5.0: 4.0, 10.0: 4.0},
        [0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    )

    assert all(abs(rate - 4.0) < 1e-9 for rate in zero_rates.values())
