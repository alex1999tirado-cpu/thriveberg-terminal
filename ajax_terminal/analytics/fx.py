from __future__ import annotations

import math
from collections.abc import Sequence


def realized_volatility(prices: Sequence[float], periods_per_year: int = 252) -> float | None:
    if len(prices) < 2:
        return None
    returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0 and prices[i] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance * periods_per_year)


def average_true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float | None:
    if not highs or len(highs) != len(lows) or len(highs) != len(closes) or len(highs) < 2:
        return None
    true_ranges: list[float] = []
    for index in range(1, len(highs)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    window = true_ranges[-period:]
    return sum(window) / len(window) if window else None
