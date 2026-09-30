from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

OptionType = Literal["call", "put"]


@dataclass(frozen=True, slots=True)
class Greeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass(frozen=True, slots=True)
class OptionAnalytics:
    price: float
    intrinsic_value: float
    time_value: float
    forward: float
    break_even: float
    gearing: float | None
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    vanna: float
    volga: float


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def d1(spot: float, strike: float, rate: float, volatility: float, time_years: float, dividend_yield: float = 0.0) -> float:
    _validate_inputs(spot, strike, volatility, time_years)
    return (math.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility**2) * time_years) / (
        volatility * math.sqrt(time_years)
    )


def d2(spot: float, strike: float, rate: float, volatility: float, time_years: float, dividend_yield: float = 0.0) -> float:
    return d1(spot, strike, rate, volatility, time_years, dividend_yield) - volatility * math.sqrt(time_years)


def black_scholes_price(
    option_type: OptionType,
    spot: float,
    strike: float,
    rate: float,
    volatility: float,
    time_years: float,
    dividend_yield: float = 0.0,
) -> float:
    first = d1(spot, strike, rate, volatility, time_years, dividend_yield)
    second = first - volatility * math.sqrt(time_years)
    discounted_spot = spot * math.exp(-dividend_yield * time_years)
    discounted_strike = strike * math.exp(-rate * time_years)
    if option_type == "call":
        return discounted_spot * _norm_cdf(first) - discounted_strike * _norm_cdf(second)
    if option_type == "put":
        return discounted_strike * _norm_cdf(-second) - discounted_spot * _norm_cdf(-first)
    raise ValueError("option_type must be 'call' or 'put'")


def greeks(
    option_type: OptionType,
    spot: float,
    strike: float,
    rate: float,
    volatility: float,
    time_years: float,
    dividend_yield: float = 0.0,
) -> Greeks:
    first = d1(spot, strike, rate, volatility, time_years, dividend_yield)
    second = first - volatility * math.sqrt(time_years)
    discounted_spot = math.exp(-dividend_yield * time_years)
    discounted_strike = math.exp(-rate * time_years)
    pdf = _norm_pdf(first)
    gamma = discounted_spot * pdf / (spot * volatility * math.sqrt(time_years))
    vega = spot * discounted_spot * pdf * math.sqrt(time_years) / 100.0
    if option_type == "call":
        delta = discounted_spot * _norm_cdf(first)
        theta = (
            -spot * discounted_spot * pdf * volatility / (2.0 * math.sqrt(time_years))
            - rate * strike * discounted_strike * _norm_cdf(second)
            + dividend_yield * spot * discounted_spot * _norm_cdf(first)
        ) / 365.0
        rho = strike * time_years * discounted_strike * _norm_cdf(second) / 100.0
    elif option_type == "put":
        delta = discounted_spot * (_norm_cdf(first) - 1.0)
        theta = (
            -spot * discounted_spot * pdf * volatility / (2.0 * math.sqrt(time_years))
            + rate * strike * discounted_strike * _norm_cdf(-second)
            - dividend_yield * spot * discounted_spot * _norm_cdf(-first)
        ) / 365.0
        rho = -strike * time_years * discounted_strike * _norm_cdf(-second) / 100.0
    else:
        raise ValueError("option_type must be 'call' or 'put'")
    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def implied_volatility(
    option_type: OptionType,
    market_price: float,
    spot: float,
    strike: float,
    rate: float,
    time_years: float,
    dividend_yield: float = 0.0,
    low: float = 1e-6,
    high: float = 5.0,
    tolerance: float = 1e-8,
) -> float:
    if market_price <= 0:
        raise ValueError("market_price must be positive")
    discounted_spot = spot * math.exp(-dividend_yield * time_years)
    discounted_strike = strike * math.exp(-rate * time_years)
    if option_type == "call":
        lower_bound = max(0.0, discounted_spot - discounted_strike)
        upper_bound = discounted_spot
    elif option_type == "put":
        lower_bound = max(0.0, discounted_strike - discounted_spot)
        upper_bound = discounted_strike
    else:
        raise ValueError("option_type must be 'call' or 'put'")
    bound_tolerance = max(tolerance, spot * 1e-10)
    if market_price < lower_bound - bound_tolerance or market_price > upper_bound + bound_tolerance:
        raise ValueError("market_price violates European option arbitrage bounds")
    if market_price <= lower_bound + bound_tolerance:
        return low
    while black_scholes_price(option_type, spot, strike, rate, high, time_years, dividend_yield) < market_price:
        high *= 2.0
        if high > 20.0:
            raise ValueError("implied volatility is outside the supported range")
    for _ in range(200):
        mid = (low + high) / 2.0
        price = black_scholes_price(option_type, spot, strike, rate, mid, time_years, dividend_yield)
        if abs(price - market_price) < tolerance:
            return mid
        if price > market_price:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def option_analytics(
    option_type: OptionType,
    spot: float,
    strike: float,
    rate: float,
    volatility: float,
    time_years: float,
    dividend_yield: float = 0.0,
) -> OptionAnalytics:
    price = black_scholes_price(
        option_type, spot, strike, rate, volatility, time_years, dividend_yield
    )
    values = greeks(option_type, spot, strike, rate, volatility, time_years, dividend_yield)
    first = d1(spot, strike, rate, volatility, time_years, dividend_yield)
    second = first - volatility * math.sqrt(time_years)
    discount_dividend = math.exp(-dividend_yield * time_years)
    raw_vega = spot * discount_dividend * _norm_pdf(first) * math.sqrt(time_years)
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    break_even = strike + price if option_type == "call" else strike - price
    return OptionAnalytics(
        price=price,
        intrinsic_value=intrinsic,
        time_value=max(price - intrinsic, 0.0),
        forward=spot * math.exp((rate - dividend_yield) * time_years),
        break_even=break_even,
        gearing=(values.delta * spot / price) if price > 0 else None,
        delta=values.delta,
        gamma=values.gamma,
        theta=values.theta,
        vega=values.vega,
        rho=values.rho,
        vanna=-discount_dividend * _norm_pdf(first) * second / volatility,
        volga=raw_vega * first * second / volatility / 10000.0,
    )


def put_call_parity(
    call_price: float,
    put_price: float,
    spot: float,
    strike: float,
    rate: float,
    time_years: float,
    dividend_yield: float = 0.0,
) -> float:
    left = call_price - put_price
    right = spot * math.exp(-dividend_yield * time_years) - strike * math.exp(-rate * time_years)
    return left - right


def _validate_inputs(spot: float, strike: float, volatility: float, time_years: float) -> None:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if volatility <= 0 or time_years <= 0:
        raise ValueError("volatility and time_years must be positive")
