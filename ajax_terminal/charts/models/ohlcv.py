from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ajax_terminal.models.quote import PriceHistory


@dataclass(frozen=True, slots=True)
class OHLCVPoint:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("OHLC values must be finite")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("High must be the largest OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Low must be the smallest OHLC value")
        if self.volume is not None and (not math.isfinite(self.volume) or self.volume < 0):
            raise ValueError("Volume must be finite and non-negative")

    @property
    def epoch(self) -> int:
        value = self.timestamp
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())


@dataclass(slots=True)
class OHLCVChart:
    symbol: str
    period: str
    interval: str
    currency: str
    provider: str
    quality: str
    points: list[OHLCVPoint]
    indicators: dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    events: list[dict[str, object]] = field(default_factory=list)


def normalize_ohlcv(history: PriceHistory) -> OHLCVChart:
    by_timestamp: dict[datetime, OHLCVPoint] = {}
    for bar in history.bars:
        try:
            point = OHLCVPoint(
                timestamp=bar.timestamp,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume) if bar.volume is not None else None,
            )
        except (TypeError, ValueError):
            continue
        by_timestamp[point.timestamp] = point
    points = sorted(by_timestamp.values(), key=lambda item: item.timestamp)
    return OHLCVChart(
        symbol=history.symbol.upper(),
        period=history.period,
        interval=history.interval,
        currency=history.currency,
        provider=history.provider,
        quality=str(getattr(history.quality, "value", history.quality)),
        points=points,
    )
