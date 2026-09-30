from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from ajax_terminal.utils.dates import add_months


@dataclass(frozen=True, slots=True)
class BondAnalytics:
    clean_price: float
    dirty_price: float
    accrued_interest: float
    ytm: float
    macaulay_duration: float
    modified_duration: float
    convexity: float
    dv01: float


def bootstrap_zero_rates(
    par_yields_pct: Mapping[float, float],
    target_years: Sequence[float],
    frequency: int = 2,
) -> dict[float, float]:
    """Bootstrap nominal zero rates from interpolated par yields.

    Inputs and outputs are annual percentages. Par yields are interpolated
    linearly between observed maturities and held flat outside their range.
    """
    if frequency <= 0:
        raise ValueError("frequency must be positive")
    observed = sorted(
        (float(years), float(rate))
        for years, rate in par_yields_pct.items()
        if years > 0
    )
    targets = sorted({float(years) for years in target_years if years > 0})
    if not observed or not targets:
        return {}

    max_period = max(1, int(max(targets) * frequency + 0.999999))
    discount_factors: dict[int, float] = {}
    for period in range(1, max_period + 1):
        years = period / frequency
        par_rate = _interpolate_rate(observed, years) / 100.0
        coupon = par_rate / frequency
        prior_coupons = coupon * sum(discount_factors.values())
        discount = (1.0 - prior_coupons) / (1.0 + coupon)
        if discount <= 0:
            discount = (1.0 + max(par_rate, -0.99) / frequency) ** (-period)
        discount_factors[period] = discount

    result: dict[float, float] = {}
    for years in targets:
        periods = years * frequency
        rounded_period = int(round(periods))
        if periods >= 1 and abs(periods - rounded_period) < 1e-9:
            discount = discount_factors[rounded_period]
            zero = frequency * (discount ** (-1.0 / rounded_period) - 1.0)
        else:
            par_rate = _interpolate_rate(observed, years) / 100.0
            zero = par_rate
        result[years] = zero * 100.0
    return result


def _interpolate_rate(observed: list[tuple[float, float]], years: float) -> float:
    if years <= observed[0][0]:
        return observed[0][1]
    if years >= observed[-1][0]:
        return observed[-1][1]
    for (left_years, left_rate), (right_years, right_rate) in zip(observed, observed[1:]):
        if left_years <= years <= right_years:
            weight = (years - left_years) / (right_years - left_years)
            return left_rate + weight * (right_rate - left_rate)
    return observed[-1][1]


def coupon_dates_after(settlement: date, maturity: date, frequency: int = 2) -> list[date]:
    if frequency <= 0:
        raise ValueError("frequency must be positive")
    step_months = 12 // frequency
    dates = [maturity]
    cursor = maturity
    while True:
        cursor = add_months(cursor, -step_months)
        if cursor <= settlement:
            break
        dates.append(cursor)
    return sorted(dates)


def accrued_interest(
    face: float,
    coupon_rate: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    coupon = face * coupon_rate / frequency
    step_months = 12 // frequency
    next_coupon = maturity
    while add_months(next_coupon, -step_months) > settlement:
        next_coupon = add_months(next_coupon, -step_months)
    previous_coupon = add_months(next_coupon, -step_months)
    period_days = (next_coupon - previous_coupon).days
    accrued_days = max((settlement - previous_coupon).days, 0)
    return coupon * accrued_days / period_days if period_days else 0.0


def dirty_price_from_ytm(
    face: float,
    coupon_rate: float,
    ytm: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    coupon = face * coupon_rate / frequency
    price = 0.0
    for cashflow_date, periods, _years in _cashflow_periods(settlement, maturity, frequency):
        cashflow = coupon + (face if cashflow_date == maturity else 0.0)
        price += cashflow / (1.0 + ytm / frequency) ** periods
    return price


def clean_price_from_ytm(
    face: float,
    coupon_rate: float,
    ytm: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    return dirty_price_from_ytm(face, coupon_rate, ytm, settlement, maturity, frequency) - accrued_interest(
        face, coupon_rate, settlement, maturity, frequency
    )


def ytm_from_price(
    clean_price: float,
    face: float,
    coupon_rate: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
    low: float = -0.5,
    high: float = 1.0,
    tolerance: float = 1e-10,
) -> float:
    target_dirty = clean_price + accrued_interest(face, coupon_rate, settlement, maturity, frequency)
    for _ in range(200):
        mid = (low + high) / 2.0
        price = dirty_price_from_ytm(face, coupon_rate, mid, settlement, maturity, frequency)
        if abs(price - target_dirty) < tolerance:
            return mid
        if price > target_dirty:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def macaulay_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    coupon = face * coupon_rate / frequency
    weighted = 0.0
    pv_total = 0.0
    for cashflow_date, periods, years in _cashflow_periods(settlement, maturity, frequency):
        cashflow = coupon + (face if cashflow_date == maturity else 0.0)
        pv = cashflow / (1.0 + ytm / frequency) ** periods
        weighted += years * pv
        pv_total += pv
    return weighted / pv_total if pv_total else 0.0


def modified_duration(macaulay: float, ytm: float, frequency: int = 2) -> float:
    return macaulay / (1.0 + ytm / frequency)


def convexity(
    face: float,
    coupon_rate: float,
    ytm: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    price = dirty_price_from_ytm(face, coupon_rate, ytm, settlement, maturity, frequency)
    if price == 0:
        return 0.0
    coupon = face * coupon_rate / frequency
    total = 0.0
    for cashflow_date, n, _years in _cashflow_periods(settlement, maturity, frequency):
        cashflow = coupon + (face if cashflow_date == maturity else 0.0)
        total += cashflow * n * (n + 1) / (1.0 + ytm / frequency) ** (n + 2)
    return total / (price * frequency**2)


def dv01(
    face: float,
    coupon_rate: float,
    ytm: float,
    settlement: date,
    maturity: date,
    frequency: int = 2,
) -> float:
    down = dirty_price_from_ytm(face, coupon_rate, ytm - 0.0001, settlement, maturity, frequency)
    up = dirty_price_from_ytm(face, coupon_rate, ytm + 0.0001, settlement, maturity, frequency)
    return (down - up) / 2.0


def analyze_bond(
    clean_price: float,
    coupon_rate: float,
    settlement: date,
    maturity: date,
    face: float = 100.0,
    frequency: int = 2,
) -> BondAnalytics:
    ytm = ytm_from_price(clean_price, face, coupon_rate, settlement, maturity, frequency)
    accrued = accrued_interest(face, coupon_rate, settlement, maturity, frequency)
    dirty = clean_price + accrued
    mac = macaulay_duration(face, coupon_rate, ytm, settlement, maturity, frequency)
    mod = modified_duration(mac, ytm, frequency)
    return BondAnalytics(
        clean_price=clean_price,
        dirty_price=dirty,
        accrued_interest=accrued,
        ytm=ytm,
        macaulay_duration=mac,
        modified_duration=mod,
        convexity=convexity(face, coupon_rate, ytm, settlement, maturity, frequency),
        dv01=dv01(face, coupon_rate, ytm, settlement, maturity, frequency),
    )


def _cashflow_periods(settlement: date, maturity: date, frequency: int) -> list[tuple[date, float, float]]:
    future_dates = coupon_dates_after(settlement, maturity, frequency)
    if not future_dates:
        return []
    step_months = 12 // frequency
    first_coupon = future_dates[0]
    previous_coupon = add_months(first_coupon, -step_months)
    period_days = max((first_coupon - previous_coupon).days, 1)
    first_fraction = max((first_coupon - settlement).days / period_days, 0.0)
    return [
        (cashflow_date, first_fraction + index, (first_fraction + index) / frequency)
        for index, cashflow_date in enumerate(future_dates)
    ]
