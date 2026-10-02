from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

import numpy as np


TRADING_DAYS = 252
MIN_OBSERVATIONS = 60
MIN_COVERAGE_PERCENT = 80.0


@dataclass(frozen=True, slots=True)
class PositionReturnSeries:
    symbol: str
    returns: Mapping[date, float]
    weight: float
    market_value: float
    currency: str
    provider: str
    quality: str
    status: str = "OK"


@dataclass(frozen=True, slots=True)
class FactorReturnSeries:
    name: str
    returns: Mapping[date, float]
    proxy: str
    provider: str


@dataclass(frozen=True, slots=True)
class RiskContribution:
    symbol: str
    weight_percent: float
    observations: int
    annualized_volatility: float | None
    beta: float | None
    variance_contribution_percent: float | None
    volatility_contribution: float | None
    var_95_contribution: float | None
    provider: str
    quality: str
    status: str


@dataclass(frozen=True, slots=True)
class FactorExposure:
    name: str
    loading: float
    proxy: str
    provider: str


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    return_percent: float
    profit_loss: float
    basis: str
    methodology: str


@dataclass(frozen=True, slots=True)
class PortfolioRiskReport:
    benchmark: str
    period: str
    available: bool
    message: str
    observations: int
    start_date: str
    end_date: str
    coverage_percent: float
    annualized_return: float | None
    annualized_volatility: float | None
    historical_var_95: float | None
    historical_var_99: float | None
    expected_shortfall_95: float | None
    expected_shortfall_99: float | None
    max_drawdown: float | None
    sharpe: float | None
    beta: float | None
    alpha: float | None
    factor_r_squared: float | None
    var_95_value: float | None
    expected_shortfall_95_value: float | None
    contributions: tuple[RiskContribution, ...]
    factors: tuple[FactorExposure, ...]
    correlation_symbols: tuple[str, ...]
    correlations: tuple[tuple[float | None, ...], ...]
    scenarios: tuple[StressScenario, ...]
    methodology: str


def returns_from_levels(levels: Mapping[date, float]) -> dict[date, float]:
    ordered = sorted(
        (observed, float(value))
        for observed, value in levels.items()
        if math.isfinite(float(value)) and float(value) > 0
    )
    returns: dict[date, float] = {}
    for index in range(1, len(ordered)):
        previous = ordered[index - 1][1]
        current = ordered[index][1]
        if previous > 0:
            value = current / previous - 1.0
            if math.isfinite(value):
                returns[ordered[index][0]] = value
    return returns


def spread_returns(
    long_returns: Mapping[date, float],
    short_returns: Mapping[date, float],
) -> dict[date, float]:
    dates = sorted(set(long_returns) & set(short_returns))
    return {observed: long_returns[observed] - short_returns[observed] for observed in dates}


def analyze_portfolio_risk(
    positions: Sequence[PositionReturnSeries],
    *,
    net_asset_value: float,
    benchmark: str,
    period: str,
    benchmark_returns: Mapping[date, float] | None = None,
    factor_series: Sequence[FactorReturnSeries] = (),
    foreign_weight: float = 0.0,
    minimum_observations: int = MIN_OBSERVATIONS,
    minimum_coverage_percent: float = MIN_COVERAGE_PERCENT,
) -> PortfolioRiskReport:
    total_market_value = sum(max(item.market_value, 0.0) for item in positions)
    covered = [item for item in positions if item.returns]
    covered_market_value = sum(max(item.market_value, 0.0) for item in covered)
    coverage = (
        covered_market_value / total_market_value * 100.0
        if total_market_value > 0
        else 0.0
    )
    common_dates = _common_dates([item.returns for item in covered])
    observations = len(common_dates)
    start_date = common_dates[0].isoformat() if common_dates else ""
    end_date = common_dates[-1].isoformat() if common_dates else ""
    base_kwargs = dict(
        benchmark=benchmark,
        period=period,
        observations=observations,
        start_date=start_date,
        end_date=end_date,
        coverage_percent=coverage,
        contributions=tuple(_empty_contribution(item) for item in positions),
        factors=(),
        correlation_symbols=tuple(item.symbol for item in covered),
        correlations=_correlation_matrix(covered),
        scenarios=(),
        methodology=(
            "CURRENT-WEIGHT HISTORICAL SIMULATION | DAILY CLOSE-TO-CLOSE RETURNS | "
            "BASE-CURRENCY LEVELS | 252-DAY ANNUALIZATION"
        ),
    )
    if net_asset_value <= 0:
        return _unavailable("NET ASSET VALUE MUST BE POSITIVE", **base_kwargs)
    if not covered:
        return _unavailable("NO OBSERVED POSITION HISTORY", **base_kwargs)
    if coverage + 1e-9 < minimum_coverage_percent:
        return _unavailable(
            f"HISTORY COVERAGE {coverage:.1f}% IS BELOW {minimum_coverage_percent:.0f}%",
            **base_kwargs,
        )
    if observations < minimum_observations:
        return _unavailable(
            f"ONLY {observations} COMMON RETURNS; {minimum_observations} REQUIRED",
            **base_kwargs,
        )

    matrix = np.asarray(
        [[item.returns[observed] for item in covered] for observed in common_dates],
        dtype=float,
    )
    weights = np.asarray([item.weight for item in covered], dtype=float)
    portfolio_returns = matrix @ weights
    annualized_return = float(np.mean(portfolio_returns) * TRADING_DAYS)
    daily_volatility = float(np.std(portfolio_returns, ddof=1))
    annualized_volatility = daily_volatility * math.sqrt(TRADING_DAYS)
    var_95 = _historical_var(portfolio_returns, 0.95)
    var_99 = _historical_var(portfolio_returns, 0.99)
    es_95 = _expected_shortfall(portfolio_returns, 0.95)
    es_99 = _expected_shortfall(portfolio_returns, 0.99)
    drawdown = _max_drawdown(portfolio_returns)
    sharpe = annualized_return / annualized_volatility if annualized_volatility > 0 else None
    beta = _beta(
        {observed: float(value) for observed, value in zip(common_dates, portfolio_returns)},
        benchmark_returns or {},
    )
    factors, alpha, r_squared = _factor_regression(
        {observed: float(value) for observed, value in zip(common_dates, portfolio_returns)},
        factor_series,
        minimum_observations,
    )
    contributions = _risk_contributions(
        positions,
        covered,
        matrix,
        weights,
        benchmark_returns or {},
        annualized_volatility,
        (var_95 or 0.0) * net_asset_value,
    )
    scenarios = _stress_scenarios(
        positions,
        net_asset_value,
        portfolio_returns,
        drawdown,
        beta,
        factors,
        foreign_weight,
    )
    return PortfolioRiskReport(
        benchmark=benchmark,
        period=period,
        available=True,
        message="OBSERVED HISTORY WITH ESTIMATED FACTOR AND SHOCK SCENARIOS",
        observations=observations,
        start_date=start_date,
        end_date=end_date,
        coverage_percent=coverage,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        historical_var_95=var_95,
        historical_var_99=var_99,
        expected_shortfall_95=es_95,
        expected_shortfall_99=es_99,
        max_drawdown=drawdown,
        sharpe=sharpe,
        beta=beta,
        alpha=alpha,
        factor_r_squared=r_squared,
        var_95_value=var_95 * net_asset_value if var_95 is not None else None,
        expected_shortfall_95_value=es_95 * net_asset_value if es_95 is not None else None,
        contributions=contributions,
        factors=factors,
        correlation_symbols=tuple(item.symbol for item in covered),
        correlations=_correlation_matrix(covered),
        scenarios=scenarios,
        methodology=base_kwargs["methodology"],
    )


def _unavailable(message: str, **kwargs: object) -> PortfolioRiskReport:
    return PortfolioRiskReport(
        available=False,
        message=message,
        annualized_return=None,
        annualized_volatility=None,
        historical_var_95=None,
        historical_var_99=None,
        expected_shortfall_95=None,
        expected_shortfall_99=None,
        max_drawdown=None,
        sharpe=None,
        beta=None,
        alpha=None,
        factor_r_squared=None,
        var_95_value=None,
        expected_shortfall_95_value=None,
        **kwargs,
    )


def _common_dates(series: Sequence[Mapping[date, float]]) -> list[date]:
    if not series:
        return []
    common = set(series[0])
    for item in series[1:]:
        common.intersection_update(item)
    return sorted(common)


def _historical_var(returns: np.ndarray, confidence: float) -> float | None:
    if returns.size == 0:
        return None
    quantile = float(np.quantile(returns, 1.0 - confidence))
    return max(0.0, -quantile)


def _expected_shortfall(returns: np.ndarray, confidence: float) -> float | None:
    if returns.size == 0:
        return None
    cutoff = float(np.quantile(returns, 1.0 - confidence))
    tail = returns[returns <= cutoff]
    return max(0.0, -float(np.mean(tail))) if tail.size else None


def _max_drawdown(returns: np.ndarray) -> float | None:
    if returns.size == 0:
        return None
    wealth = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peaks - 1.0))


def _beta(portfolio: Mapping[date, float], benchmark: Mapping[date, float]) -> float | None:
    dates = sorted(set(portfolio) & set(benchmark))
    if len(dates) < 30:
        return None
    portfolio_values = np.asarray([portfolio[item] for item in dates], dtype=float)
    benchmark_values = np.asarray([benchmark[item] for item in dates], dtype=float)
    variance = float(np.var(benchmark_values, ddof=1))
    if variance <= 0:
        return None
    covariance = float(np.cov(portfolio_values, benchmark_values, ddof=1)[0, 1])
    return covariance / variance


def _factor_regression(
    portfolio: Mapping[date, float],
    factors: Sequence[FactorReturnSeries],
    minimum_observations: int,
) -> tuple[tuple[FactorExposure, ...], float | None, float | None]:
    usable = [item for item in factors if item.returns]
    if not usable:
        return (), None, None
    dates = sorted(set(portfolio).intersection(*(set(item.returns) for item in usable)))
    required = max(minimum_observations, len(usable) * 12)
    if len(dates) < required:
        return (), None, None
    y = np.asarray([portfolio[item] for item in dates], dtype=float)
    x = np.asarray([[factor.returns[item] for factor in usable] for item in dates], dtype=float)
    design = np.column_stack((np.ones(len(dates)), x))
    coefficients, _residuals, rank, _singular = np.linalg.lstsq(design, y, rcond=None)
    if rank < design.shape[1]:
        return (), None, None
    fitted = design @ coefficients
    total = float(np.sum((y - np.mean(y)) ** 2))
    residual = float(np.sum((y - fitted) ** 2))
    r_squared = 1.0 - residual / total if total > 0 else None
    exposures = tuple(
        FactorExposure(item.name, float(coefficients[index + 1]), item.proxy, item.provider)
        for index, item in enumerate(usable)
    )
    return exposures, float(coefficients[0] * TRADING_DAYS), r_squared


def _risk_contributions(
    all_positions: Sequence[PositionReturnSeries],
    covered: Sequence[PositionReturnSeries],
    matrix: np.ndarray,
    weights: np.ndarray,
    benchmark_returns: Mapping[date, float],
    portfolio_volatility: float,
    var_95_value: float,
) -> tuple[RiskContribution, ...]:
    covariance = np.cov(matrix, rowvar=False, ddof=1)
    covariance = np.atleast_2d(covariance)
    portfolio_variance = float(weights @ covariance @ weights)
    covariance_weight = covariance @ weights
    covered_by_symbol: dict[str, RiskContribution] = {}
    for index, item in enumerate(covered):
        standalone = float(np.std(matrix[:, index], ddof=1) * math.sqrt(TRADING_DAYS))
        contribution_percent = (
            float(weights[index] * covariance_weight[index] / portfolio_variance * 100.0)
            if portfolio_variance > 0
            else None
        )
        contribution_volatility = (
            portfolio_volatility * contribution_percent / 100.0
            if contribution_percent is not None
            else None
        )
        covered_by_symbol[item.symbol] = RiskContribution(
            item.symbol,
            item.weight * 100.0,
            len(item.returns),
            standalone,
            _beta(item.returns, benchmark_returns),
            contribution_percent,
            contribution_volatility,
            var_95_value * contribution_percent / 100.0 if contribution_percent is not None else None,
            item.provider,
            item.quality,
            item.status,
        )
    return tuple(
        covered_by_symbol.get(item.symbol, _empty_contribution(item))
        for item in all_positions
    )


def _empty_contribution(item: PositionReturnSeries) -> RiskContribution:
    return RiskContribution(
        item.symbol,
        item.weight * 100.0,
        len(item.returns),
        None,
        None,
        None,
        None,
        None,
        item.provider,
        item.quality,
        item.status,
    )


def _correlation_matrix(
    positions: Sequence[PositionReturnSeries],
) -> tuple[tuple[float | None, ...], ...]:
    matrix: list[tuple[float | None, ...]] = []
    for left in positions:
        row: list[float | None] = []
        for right in positions:
            dates = sorted(set(left.returns) & set(right.returns))
            if left.symbol == right.symbol and dates:
                row.append(1.0)
                continue
            if len(dates) < 30:
                row.append(None)
                continue
            left_values = np.asarray([left.returns[item] for item in dates], dtype=float)
            right_values = np.asarray([right.returns[item] for item in dates], dtype=float)
            if np.std(left_values) == 0 or np.std(right_values) == 0:
                row.append(None)
                continue
            row.append(float(np.corrcoef(left_values, right_values)[0, 1]))
        matrix.append(tuple(row))
    return tuple(matrix)


def _stress_scenarios(
    positions: Sequence[PositionReturnSeries],
    net_asset_value: float,
    portfolio_returns: np.ndarray,
    max_drawdown: float | None,
    beta: float | None,
    factors: Sequence[FactorExposure],
    foreign_weight: float,
) -> tuple[StressScenario, ...]:
    scenarios: list[StressScenario] = []
    worst_day = float(np.min(portfolio_returns))
    scenarios.append(
        StressScenario(
            "WORST OBSERVED DAY",
            worst_day * 100.0,
            worst_day * net_asset_value,
            "OBSERVED",
            "Worst current-weight daily return in the selected history",
        )
    )
    if max_drawdown is not None:
        scenarios.append(
            StressScenario(
                "MAX OBSERVED DRAWDOWN",
                max_drawdown * 100.0,
                max_drawdown * net_asset_value,
                "OBSERVED",
                "Peak-to-trough loss of the current-weight historical series",
            )
        )
    if beta is not None:
        equity_return = max(-1.0, beta * -0.20)
        scenarios.append(
            StressScenario(
                "GLOBAL EQUITY -20%*",
                equity_return * 100.0,
                equity_return * net_asset_value,
                "ESTIMATED*",
                "Linear benchmark beta multiplied by a -20% benchmark shock",
            )
        )
    factor_by_name = {item.name: item.loading for item in factors}
    factor_shocks = {
        "MARKET": -0.05,
        "SIZE": -0.10,
        "VALUE": 0.10,
        "MOMENTUM": -0.10,
        "QUALITY": 0.05,
    }
    if factor_by_name:
        factor_return = sum(
            factor_by_name.get(name, 0.0) * shock
            for name, shock in factor_shocks.items()
        )
        factor_return = max(-1.0, factor_return)
        scenarios.append(
            StressScenario(
                "FACTOR ROTATION*",
                factor_return * 100.0,
                factor_return * net_asset_value,
                "ESTIMATED*",
                "MKT -5%, SIZE -10%, VALUE +10%, MOM -10%, QUALITY +5%",
            )
        )
    if foreign_weight > 0:
        fx_return = max(-1.0, -0.10 * foreign_weight)
        scenarios.append(
            StressScenario(
                "FOREIGN FX -10%*",
                fx_return * 100.0,
                fx_return * net_asset_value,
                "ESTIMATED*",
                "All non-base portfolio currencies depreciate 10% simultaneously",
            )
        )
    largest = max((item.weight for item in positions), default=0.0)
    if largest > 0:
        concentration_return = max(-1.0, -0.25 * largest)
        scenarios.append(
            StressScenario(
                "LARGEST POSITION -25%*",
                concentration_return * 100.0,
                concentration_return * net_asset_value,
                "ESTIMATED*",
                "Idiosyncratic -25% shock to the largest current position",
            )
        )
    return tuple(scenarios)
