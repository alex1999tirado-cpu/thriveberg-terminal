from __future__ import annotations

from datetime import date

from ajax_terminal.analytics.forwards import build_forward_curve, discount_factor, forward_from_rates, forward_outright


def test_forward_outright_uses_foreign_over_domestic_discount_factor() -> None:
    spot = 1.10
    domestic_df = discount_factor(0.05, 1.0)
    foreign_df = discount_factor(0.03, 1.0)

    forward = forward_outright(spot, foreign_df, domestic_df)

    assert forward > spot
    assert round(forward, 6) == round(spot * foreign_df / domestic_df, 6)


def test_forward_from_rates_matches_discount_factor_formula() -> None:
    forward = forward_from_rates(1.10, domestic_rate=0.05, foreign_rate=0.03, time_years=1.0)

    assert round(forward, 6) == round(1.10 * (1.05 / 1.03), 6)


def test_build_forward_curve_sets_pair_convention() -> None:
    rates_usd = {"ON": 0.05, "TN": 0.05, "1W": 0.05, "1M": 0.05, "3M": 0.05, "6M": 0.05, "9M": 0.05, "1Y": 0.05, "2Y": 0.05}
    rates_eur = {"ON": 0.03, "TN": 0.03, "1W": 0.03, "1M": 0.03, "3M": 0.03, "6M": 0.03, "9M": 0.03, "1Y": 0.03, "2Y": 0.03}

    curve = build_forward_curve("EURUSD", 1.10, rates_usd, rates_eur, valuation_date=date(2026, 1, 2))

    assert curve[0].domestic_currency == "USD"
    assert curve[0].foreign_currency == "EUR"
    assert curve[-1].outright > 1.10
    assert curve[-1].annualized_carry > 0
