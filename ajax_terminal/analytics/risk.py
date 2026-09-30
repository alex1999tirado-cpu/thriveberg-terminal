from __future__ import annotations

import math
from collections.abc import Sequence


def returns_from_prices(prices: Sequence[float]) -> list[float]:
    return [prices[index] / prices[index - 1] - 1.0 for index in range(1, len(prices)) if prices[index - 1] != 0]


def historical_var(returns: Sequence[float], confidence: float = 0.95) -> float | None:
    if not returns:
        return None
    ordered = sorted(returns)
    index = max(int((1.0 - confidence) * len(ordered)) - 1, 0)
    return -ordered[index]


def expected_shortfall(returns: Sequence[float], confidence: float = 0.95) -> float | None:
    if not returns:
        return None
    ordered = sorted(returns)
    cutoff = max(int((1.0 - confidence) * len(ordered)), 1)
    tail = ordered[:cutoff]
    return -sum(tail) / len(tail)


def parametric_var(returns: Sequence[float], confidence_z: float = 1.645) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return -(mean - confidence_z * math.sqrt(variance))


def max_drawdown(prices: Sequence[float]) -> float | None:
    if not prices:
        return None
    peak = prices[0]
    drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        if peak:
            drawdown = min(drawdown, price / peak - 1.0)
    return drawdown


def sharpe_ratio(returns: Sequence[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float | None:
    if len(returns) < 2:
        return None
    excess = [item - risk_free_rate / periods_per_year for item in returns]
    mean = sum(excess) / len(excess)
    variance = sum((item - mean) ** 2 for item in excess) / (len(excess) - 1)
    stdev = math.sqrt(variance)
    return math.sqrt(periods_per_year) * mean / stdev if stdev else None
