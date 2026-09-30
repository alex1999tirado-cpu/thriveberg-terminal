from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    timestamp: datetime
    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("Time-series values must be finite")


@dataclass(slots=True)
class TimeSeries:
    key: str
    label: str
    unit: str
    points: list[TimeSeriesPoint]
    source: str = ""

    def normalized(self) -> "TimeSeries":
        unique = {point.timestamp: point for point in self.points}
        return TimeSeries(
            self.key,
            self.label,
            self.unit,
            sorted(unique.values(), key=lambda item: item.timestamp),
            self.source,
        )
