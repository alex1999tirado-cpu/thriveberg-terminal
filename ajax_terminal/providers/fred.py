from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

from ajax_terminal.models.macro import EconomicEvent, MacroIndicator
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.fred_csv import fred_observations


_US_SERIES = {
    "GDP": ("A191RL1Q225SBEA", "Real GDP annualized", "%", "LEVEL"),
    "CPI": ("CPIAUCSL", "CPI YoY", "%", "YOY"),
    "CORE_CPI": ("CPILFESL", "Core CPI YoY", "%", "YOY"),
    "UNEMP": ("UNRATE", "Unemployment", "%", "LEVEL"),
    "POLICY": ("FEDFUNDS", "Federal Funds Rate", "%", "LEVEL"),
}


class FredProvider:
    """Small official US macro monitor backed by public FRED CSV series."""

    name = "FRED"

    async def indicators(self, country: str) -> list[MacroIndicator]:
        selected = country.upper()
        if selected not in {"US", "USA"}:
            raise ProviderError(f"FRED macro monitor is not configured for {selected}")
        loaded = await asyncio.gather(
            *(fred_observations(series_id, "2020-01-01") for series_id, _name, _unit, _transform in _US_SERIES.values())
        )
        indicators: list[MacroIndicator] = []
        for (code, (_series_id, name, unit, transform)), observations in zip(_US_SERIES.items(), loaded):
            if not observations:
                continue
            values = [_transform(observations, index, transform) for index in range(len(observations))]
            valid = [(observations[index][0], value) for index, value in enumerate(values) if value is not None]
            if not valid:
                continue
            observed_date, current = valid[-1]
            previous = valid[-2][1] if len(valid) > 1 else None
            indicators.append(
                MacroIndicator(
                    code=code,
                    country="US",
                    name=name,
                    value=current,
                    unit=unit,
                    period=observed_date.isoformat(),
                    previous=previous,
                    provider=self.name,
                    quality=DataQuality.DELAYED,
                    timestamp=datetime.combine(observed_date, time(), timezone.utc),
                )
            )
        if not indicators:
            raise ProviderError("FRED returned no US macro observations")
        return indicators

    async def calendar(self, country: str | None = None) -> list[EconomicEvent]:
        raise ProviderError("FRED does not provide a forward economic calendar")


def _transform(observations: list[tuple[object, float]], index: int, transform: str) -> float | None:
    current = observations[index][1]
    if transform != "YOY":
        return current
    if index < 12 or observations[index - 12][1] == 0:
        return None
    return (current / observations[index - 12][1] - 1.0) * 100.0
