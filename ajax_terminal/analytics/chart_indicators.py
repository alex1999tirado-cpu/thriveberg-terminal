from __future__ import annotations

import math

from ajax_terminal.charts.models.ohlcv import OHLCVChart


def price_indicators(chart: OHLCVChart) -> dict[str, list[tuple[int, float]]]:
    closes = [point.close for point in chart.points]
    volumes = [point.volume or 0.0 for point in chart.points]
    typical = [(point.high + point.low + point.close) / 3.0 for point in chart.points]
    epochs = [point.epoch for point in chart.points]
    result = {
        "sma20": _pair(epochs, _sma(closes, 20)),
        "ema50": _pair(epochs, _ema(closes, 50)),
        "vwap": _pair(epochs, _vwap(typical, volumes)),
    }
    return {key: values for key, values in result.items() if values}


def _pair(epochs: list[int], values: list[float | None]) -> list[tuple[int, float]]:
    return [
        (timestamp, value)
        for timestamp, value in zip(epochs, values)
        if value is not None and math.isfinite(value)
    ]


def _sma(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        result.append(running / window if index + 1 >= window else None)
    return result


def _ema(values: list[float], span: int) -> list[float | None]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    result: list[float | None] = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * float(result[-1]))
    return result


def _vwap(prices: list[float], volumes: list[float]) -> list[float | None]:
    result: list[float | None] = []
    cumulative_value = 0.0
    cumulative_volume = 0.0
    for price, volume in zip(prices, volumes):
        cumulative_value += price * volume
        cumulative_volume += volume
        result.append(cumulative_value / cumulative_volume if cumulative_volume > 0 else None)
    return result
