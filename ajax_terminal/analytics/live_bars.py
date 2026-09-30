from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ajax_terminal.charts.models.ohlcv import OHLCVChart, OHLCVPoint
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory


@dataclass(frozen=True, slots=True)
class TradeTick:
    symbol: str
    price: float
    timestamp_ms: int
    volume: float = 0.0

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000.0, timezone.utc)


def merge_trade_ticks(chart: OHLCVChart, ticks: list[TradeTick]) -> OHLCVChart:
    """Merge real trades into the active OHLCV bar without rebuilding history."""
    points = list(chart.points)
    if not points:
        return chart
    changed = False
    for tick in sorted(ticks, key=lambda item: item.timestamp_ms):
        if tick.symbol.upper() != chart.symbol.upper() or not _valid_tick(tick):
            continue
        last = points[-1]
        target_epoch = _target_epoch(tick.timestamp, chart.interval, last.timestamp, last.epoch)
        if target_epoch < last.epoch:
            continue
        volume = max(float(tick.volume), 0.0)
        if target_epoch == last.epoch:
            points[-1] = OHLCVPoint(
                timestamp=last.timestamp,
                open=last.open,
                high=max(last.high, tick.price),
                low=min(last.low, tick.price),
                close=tick.price,
                volume=(last.volume or 0.0) + volume,
            )
            changed = True
            continue
        timestamp = datetime.fromtimestamp(target_epoch, timezone.utc)
        points.append(
            OHLCVPoint(
                timestamp=timestamp,
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=volume,
            )
        )
        changed = True
    if not changed:
        return chart
    return replace(chart, points=points, provider="Finnhub WebSocket", quality="STREAM")


def merge_history_trade_ticks(history: PriceHistory, ticks: list[TradeTick]) -> PriceHistory:
    bars = list(history.bars)
    if not bars:
        return history
    changed = False
    latest_tick: TradeTick | None = None
    for tick in sorted(ticks, key=lambda item: item.timestamp_ms):
        if tick.symbol.upper() != history.symbol.upper() or not _valid_tick(tick):
            continue
        last = bars[-1]
        last_epoch = int(last.timestamp.replace(tzinfo=last.timestamp.tzinfo or timezone.utc).timestamp())
        target_epoch = _target_epoch(tick.timestamp, history.interval, last.timestamp, last_epoch)
        if target_epoch < last_epoch:
            continue
        volume = max(float(tick.volume), 0.0)
        if target_epoch == last_epoch:
            bars[-1] = PriceBar(
                timestamp=last.timestamp,
                open=last.open,
                high=max(last.high, tick.price),
                low=min(last.low, tick.price),
                close=tick.price,
                volume=(last.volume or 0.0) + volume,
            )
        else:
            bars.append(
                PriceBar(
                    timestamp=datetime.fromtimestamp(target_epoch, timezone.utc),
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=volume,
                )
            )
        changed = True
        latest_tick = tick
    if not changed:
        return history
    return replace(
        history,
        bars=bars,
        provider="Finnhub WebSocket + Yahoo history",
        quality=DataQuality.REALTIME,
        timestamp=latest_tick.timestamp if latest_tick is not None else history.timestamp,
    )


def _valid_tick(tick: TradeTick) -> bool:
    return (
        math.isfinite(tick.price)
        and tick.price > 0
        and tick.timestamp_ms > 0
        and math.isfinite(tick.volume)
    )


def _target_epoch(timestamp: datetime, interval: str, last_timestamp: datetime, last_epoch: int) -> int:
    normalized_last = last_timestamp.replace(tzinfo=last_timestamp.tzinfo or timezone.utc).astimezone(timezone.utc)
    if interval == "1d" and timestamp.date() == normalized_last.date():
        return last_epoch
    if interval == "1wk" and timestamp.isocalendar()[:2] == normalized_last.isocalendar()[:2]:
        return last_epoch
    seconds = _interval_seconds(interval)
    epoch = int(timestamp.timestamp())
    return epoch - (epoch % seconds)


def _interval_seconds(interval: str) -> int:
    if interval.endswith("m"):
        return max(int(interval[:-1]), 1) * 60
    if interval in {"1h", "60m"}:
        return 3600
    if interval == "1wk":
        return 7 * 86400
    return 86400
