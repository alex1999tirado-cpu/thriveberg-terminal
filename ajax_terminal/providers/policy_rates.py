from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

from ajax_terminal.models.macro import CountryProfile, MacroObservation
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.fred_csv import fred_observations


class FredPolicyRateProvider:
    name = "FRED / CENTRAL BANKS"

    async def latest(self, countries: list[CountryProfile]) -> dict[str, MacroObservation]:
        series_to_countries: dict[str, list[CountryProfile]] = {}
        for country in countries:
            if country.policy_series:
                series_to_countries.setdefault(country.policy_series, []).append(country)
        series_ids = list(series_to_countries)
        loaded = await asyncio.gather(
            *(fred_observations(series, "2020-01-01") for series in series_ids),
            return_exceptions=True,
        )
        result: dict[str, MacroObservation] = {}
        for series, observations in zip(series_ids, loaded):
            if isinstance(observations, Exception) or not observations:
                continue
            observed_on, value = observations[-1]
            for country in series_to_countries[series]:
                result[country.iso3] = MacroObservation(
                    code="RATE",
                    value=float(value),
                    unit="%",
                    period=observed_on.isoformat(),
                    source=self.name,
                    quality=DataQuality.DELAYED,
                    status="LATEST OFFICIAL",
                    timestamp=datetime.combine(observed_on, time(), timezone.utc),
                )
        return result
