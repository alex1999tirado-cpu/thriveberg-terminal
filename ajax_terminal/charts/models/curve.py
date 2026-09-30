from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ajax_terminal.models.quote import Curve


@dataclass(frozen=True, slots=True)
class CurveObservation:
    tenor: str
    years: float
    yield_pct: float
    change_bp: float | None = None

    def __post_init__(self) -> None:
        if self.years <= 0 or not math.isfinite(self.years):
            raise ValueError("Curve tenor must be positive")
        if not math.isfinite(self.yield_pct):
            raise ValueError("Curve yield must be finite")


@dataclass(slots=True)
class CurveChart:
    currency: str
    name: str
    points: list[CurveObservation]
    provider: str
    quality: str
    timestamp: datetime
    method: str


def normalize_curve(curve: Curve) -> CurveChart:
    points: list[CurveObservation] = []
    for point in curve.points:
        try:
            points.append(
                CurveObservation(
                    tenor=point.tenor.upper(),
                    years=float(point.years),
                    yield_pct=float(point.yield_pct),
                    change_bp=float(point.change_bp) if point.change_bp is not None else None,
                )
            )
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item.years)
    return CurveChart(
        currency=curve.currency.upper(),
        name=curve.name,
        points=points,
        provider=curve.provider,
        quality=str(getattr(curve.quality, "value", curve.quality)),
        timestamp=curve.timestamp,
        method=curve.method,
    )
