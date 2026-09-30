from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ajax_terminal.analytics.risk import expected_shortfall, historical_var, max_drawdown, returns_from_prices, sharpe_ratio
from ajax_terminal.analytics.volatility import historical_volatility
from ajax_terminal.models.quote import PriceHistory
from ajax_terminal.utils.periods import annualization_factor


@dataclass(frozen=True, slots=True)
class MarketStatistics:
    period_return: float | None
    high: float | None
    low: float | None
    latest_volume: float | None
    average_volume_20: float | None
    annualized_volatility: float | None
    max_drawdown: float | None
    historical_var_95: float | None
    expected_shortfall_95: float | None
    sharpe: float | None


def calculate_market_statistics(history: PriceHistory) -> MarketStatistics:
    prices = [bar.close for bar in history.bars if bar.close > 0]
    returns = returns_from_prices(prices)
    volumes = [bar.volume for bar in history.bars[-20:] if bar.volume is not None]
    period_return = prices[-1] / prices[0] - 1.0 if len(prices) >= 2 and prices[0] else None
    factor = annualization_factor(history.interval)
    return MarketStatistics(
        period_return=period_return,
        high=max((bar.high for bar in history.bars), default=None),
        low=min((bar.low for bar in history.bars), default=None),
        latest_volume=history.bars[-1].volume if history.bars else None,
        average_volume_20=sum(volumes) / len(volumes) if volumes else None,
        annualized_volatility=historical_volatility(prices, factor),
        max_drawdown=max_drawdown(prices),
        historical_var_95=historical_var(returns),
        expected_shortfall_95=expected_shortfall(returns),
        sharpe=sharpe_ratio(returns, periods_per_year=factor),
    )


def horizon_returns(history: PriceHistory) -> dict[str, float | None]:
    if len(history.bars) < 2:
        return {label: None for label in ("1W", "1M", "3M", "6M", "1Y")}
    latest = history.bars[-1]
    horizons = {
        "1W": timedelta(days=7),
        "1M": timedelta(days=30),
        "3M": timedelta(days=91),
        "6M": timedelta(days=182),
        "1Y": timedelta(days=365),
    }
    result: dict[str, float | None] = {}
    for label, delta in horizons.items():
        cutoff = latest.timestamp - delta
        candidates = [bar for bar in history.bars if bar.timestamp <= cutoff]
        base = candidates[-1].close if candidates else None
        result[label] = latest.close / base - 1.0 if base and latest.close else None
    return result
