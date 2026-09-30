from __future__ import annotations

import math
from collections.abc import Sequence


def historical_volatility(prices: Sequence[float], periods_per_year: int = 252) -> float | None:
    if len(prices) < 3:
        return None
    returns = [math.log(prices[index] / prices[index - 1]) for index in range(1, len(prices)) if prices[index - 1] > 0]
    if len(returns) < 2:
        return None
    average = sum(returns) / len(returns)
    variance = sum((item - average) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance * periods_per_year)


def percentile_rank(history: Sequence[float], current: float) -> float | None:
    if not history:
        return None
    below = sum(1 for item in history if item <= current)
    return 100.0 * below / len(history)


def iv_rank(history: Sequence[float], current: float) -> float | None:
    if not history:
        return None
    low = min(history)
    high = max(history)
    if high == low:
        return 0.0
    return 100.0 * (current - low) / (high - low)
