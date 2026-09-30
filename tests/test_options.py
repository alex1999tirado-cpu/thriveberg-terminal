from __future__ import annotations

from ajax_terminal.analytics.options import black_scholes_price, greeks, implied_volatility, put_call_parity


def test_black_scholes_reference_prices() -> None:
    call = black_scholes_price("call", 100, 100, 0.05, 0.20, 1.0)
    put = black_scholes_price("put", 100, 100, 0.05, 0.20, 1.0)

    assert abs(call - 10.4506) < 0.001
    assert abs(put - 5.5735) < 0.001


def test_greeks_reference_delta_gamma() -> None:
    values = greeks("call", 100, 100, 0.05, 0.20, 1.0)

    assert abs(values.delta - 0.6368) < 0.001
    assert abs(values.gamma - 0.0188) < 0.001
    assert values.vega > 0


def test_implied_volatility_recovers_model_vol() -> None:
    market_price = black_scholes_price("call", 100, 105, 0.04, 0.32, 0.75)

    solved = implied_volatility("call", market_price, 100, 105, 0.04, 0.75)

    assert abs(solved - 0.32) < 1e-6


def test_put_call_parity_residual_is_small() -> None:
    call = black_scholes_price("call", 100, 100, 0.05, 0.20, 1.0)
    put = black_scholes_price("put", 100, 100, 0.05, 0.20, 1.0)

    residual = put_call_parity(call, put, 100, 100, 0.05, 1.0)

    assert abs(residual) < 1e-10
