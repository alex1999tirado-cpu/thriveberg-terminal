from __future__ import annotations

from collections.abc import Iterable
from math import isfinite


def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    value = numerator / denominator
    return value if isfinite(value) else None


def margin(profit: float | None, revenue: float | None) -> float | None:
    value = safe_divide(profit, revenue)
    return value * 100.0 if value is not None else None


def growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return (current / previous - 1.0) * 100.0


def free_cash_flow(operating_cash_flow: float | None, capital_expenditure: float | None) -> float | None:
    if operating_cash_flow is None or capital_expenditure is None:
        return None
    return operating_cash_flow + capital_expenditure if capital_expenditure < 0 else operating_cash_flow - capital_expenditure


def free_cash_flow_yield(fcf: float | None, market_cap: float | None) -> float | None:
    value = safe_divide(fcf, market_cap)
    return value * 100.0 if value is not None else None


def net_debt(total_debt: float | None, cash: float | None) -> float | None:
    if total_debt is None or cash is None:
        return None
    return total_debt - cash


def enterprise_value(market_cap: float | None, total_debt: float | None, cash: float | None) -> float | None:
    if market_cap is None:
        return None
    return market_cap + (total_debt or 0.0) - (cash or 0.0)


def return_on_equity(net_income: float | None, equity: float | None) -> float | None:
    value = safe_divide(net_income, equity)
    return value * 100.0 if value is not None else None


def return_on_assets(net_income: float | None, assets: float | None) -> float | None:
    value = safe_divide(net_income, assets)
    return value * 100.0 if value is not None else None


def return_on_invested_capital(
    ebit: float | None,
    tax_rate: float | None,
    debt: float | None,
    equity: float | None,
    cash: float | None,
) -> float | None:
    if ebit is None or debt is None or equity is None:
        return None
    invested_capital = debt + equity - (cash or 0.0)
    effective_tax = min(max(tax_rate or 0.0, 0.0), 1.0)
    value = safe_divide(ebit * (1.0 - effective_tax), invested_capital)
    return value * 100.0 if value is not None else None


def cagr(first: float | None, last: float | None, years: float) -> float | None:
    if first is None or last is None or first <= 0 or last < 0 or years <= 0:
        return None
    return ((last / first) ** (1.0 / years) - 1.0) * 100.0


def mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def median(values: Iterable[float | None]) -> float | None:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    midpoint = len(clean) // 2
    if len(clean) % 2:
        return clean[midpoint]
    return (clean[midpoint - 1] + clean[midpoint]) / 2.0
