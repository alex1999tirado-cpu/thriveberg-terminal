from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from ajax_terminal.models.options import VolatilitySurface


@dataclass(frozen=True, slots=True)
class VolPoint:
    expiry: date
    tenor_days: int
    strike: float
    moneyness: float
    delta: float | None
    iv: float
    option_type: str
    volume: int | None = None
    open_interest: int | None = None

    def __post_init__(self) -> None:
        if self.tenor_days <= 0:
            raise ValueError("Tenor must be positive")
        if self.strike <= 0 or not math.isfinite(self.strike):
            raise ValueError("Strike must be positive")
        if not 0 < self.moneyness < 10:
            raise ValueError("Moneyness must be a strike/spot ratio")
        if not 0 < self.iv <= 5 or not math.isfinite(self.iv):
            raise ValueError("IV must be a decimal between 0 and 5")
        if self.option_type not in {"call", "put"}:
            raise ValueError("Option type must be call or put")


@dataclass(slots=True)
class VolSurface:
    symbol: str
    spot: float
    timestamp: datetime
    currency: str
    source: str
    status: str
    points: list[VolPoint]
    rate: float = 0.0
    dividend_yield: float = 0.0
    rate_available: bool = True

    @property
    def expiries(self) -> list[date]:
        return sorted({point.expiry for point in self.points})

    @property
    def tenors(self) -> list[int]:
        return sorted({point.tenor_days for point in self.points})


def normalize_vol_surface(surface: VolatilitySurface) -> VolSurface:
    if surface.spot is None or surface.spot <= 0:
        raise ValueError(f"No valid spot is available for {surface.symbol}")
    points: list[VolPoint] = []
    for slice_ in surface.slices:
        for point in slice_.points:
            try:
                points.append(
                    VolPoint(
                        expiry=point.expiry,
                        tenor_days=point.days_to_expiry,
                        strike=float(point.strike),
                        moneyness=float(point.moneyness),
                        delta=float(point.delta) if point.delta is not None else None,
                        iv=float(point.implied_volatility),
                        option_type=point.option_type.lower(),
                        volume=point.volume,
                        open_interest=point.open_interest,
                    )
                )
            except (TypeError, ValueError):
                continue
    return VolSurface(
        symbol=surface.symbol.upper(),
        spot=float(surface.spot),
        timestamp=surface.timestamp,
        currency=surface.currency,
        source=surface.provider,
        status=str(getattr(surface.quality, "value", surface.quality)),
        points=points,
        rate=surface.rate,
        dividend_yield=surface.dividend_yield,
        rate_available=surface.rate_available,
    )
