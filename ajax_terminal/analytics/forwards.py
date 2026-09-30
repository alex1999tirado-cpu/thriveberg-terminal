from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ajax_terminal.utils.dates import tenor_to_date, year_fraction
from ajax_terminal.utils.symbols import split_fx_pair


DEFAULT_TENORS = ["ON", "TN", "1W", "1M", "3M", "6M", "9M", "1Y", "2Y"]


@dataclass(frozen=True, slots=True)
class ForwardPoint:
    pair: str
    tenor: str
    maturity: date
    year_fraction: float
    spot: float
    outright: float
    points: float
    carry: float
    annualized_carry: float
    domestic_currency: str
    foreign_currency: str


def discount_factor(rate: float, time_years: float, continuous: bool = False) -> float:
    if time_years < 0:
        raise ValueError("time_years must be non-negative")
    if continuous:
        import math

        return math.exp(-rate * time_years)
    return 1.0 / (1.0 + rate * time_years)


def forward_outright(spot: float, df_foreign: float, df_domestic: float) -> float:
    if spot <= 0:
        raise ValueError("spot must be positive")
    if df_foreign <= 0 or df_domestic <= 0:
        raise ValueError("discount factors must be positive")
    return spot * df_foreign / df_domestic


def forward_from_rates(
    spot: float,
    domestic_rate: float,
    foreign_rate: float,
    time_years: float,
    continuous: bool = False,
) -> float:
    df_domestic = discount_factor(domestic_rate, time_years, continuous=continuous)
    df_foreign = discount_factor(foreign_rate, time_years, continuous=continuous)
    return forward_outright(spot, df_foreign=df_foreign, df_domestic=df_domestic)


def interpolate_rate(curve: dict[str, float], tenor: str) -> float:
    target = tenor.upper()
    if target in curve:
        return curve[target]
    raise KeyError(f"Tenor {tenor} not found in curve")


def build_forward_curve(
    pair: str,
    spot: float,
    domestic_rates: dict[str, float],
    foreign_rates: dict[str, float],
    valuation_date: date | None = None,
    tenors: list[str] | None = None,
    basis: str = "ACT/365",
) -> list[ForwardPoint]:
    valuation_date = valuation_date or date.today()
    tenors = tenors or DEFAULT_TENORS
    base, quote = split_fx_pair(pair)
    points: list[ForwardPoint] = []
    for tenor in tenors:
        maturity = tenor_to_date(valuation_date, tenor)
        t = max(year_fraction(valuation_date, maturity, basis), 1 / 365)
        domestic_rate = interpolate_rate(domestic_rates, tenor)
        foreign_rate = interpolate_rate(foreign_rates, tenor)
        outright = forward_from_rates(spot, domestic_rate, foreign_rate, t)
        fwd_points = outright - spot
        carry = fwd_points / spot
        annualized = carry / t
        points.append(
            ForwardPoint(
                pair=pair.upper().replace("/", ""),
                tenor=tenor,
                maturity=maturity,
                year_fraction=t,
                spot=spot,
                outright=outright,
                points=fwd_points,
                carry=carry,
                annualized_carry=annualized,
                domestic_currency=quote,
                foreign_currency=base,
            )
        )
    return points
