from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ajax_terminal.country_registry import COUNTRY_REGISTRY, CountryRegistry
from ajax_terminal.models.macro import (
    CountryMacroSnapshot,
    CountryMapValue,
    CountryProfile,
    EconomicEvent,
    MacroMapDataset,
    MacroMapMetric,
    MacroObservation,
)
from ajax_terminal.models.quote import DataQuality, PriceHistory, Quote
from ajax_terminal.providers.eurostat import EUROSTAT_METRICS, EurostatProvider
from ajax_terminal.providers.policy_rates import FredPolicyRateProvider
from ajax_terminal.providers.world_bank import WORLD_BANK_METRICS, WorldBankProvider
from ajax_terminal.services.macro_service import MacroService
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache


LOGGER = logging.getLogger(__name__)
MACRO_CODES = (
    "GDP",
    "CPI",
    "CORE_CPI",
    "UNEMP",
    "RATE",
    "PMI_MFG",
    "PMI_SVC",
    "RETAIL",
    "INDUSTRIAL",
    "DEBT_GDP",
    "CURRENT_ACCOUNT",
)
MAP_METRIC_ALIASES = {
    "GDP": MacroMapMetric.GDP,
    "GROWTH": MacroMapMetric.GDP,
    "CPI": MacroMapMetric.CPI,
    "INFLATION": MacroMapMetric.CPI,
    "UNEMP": MacroMapMetric.UNEMPLOYMENT,
    "UNEMPLOYMENT": MacroMapMetric.UNEMPLOYMENT,
    "RATE": MacroMapMetric.POLICY_RATE,
    "RATES": MacroMapMetric.POLICY_RATE,
    "POLICY": MacroMapMetric.POLICY_RATE,
    "10Y": MacroMapMetric.SOVEREIGN_10Y,
    "YIELD": MacroMapMetric.SOVEREIGN_10Y,
    "EQUITY": MacroMapMetric.EQUITY_YTD,
    "INDEX": MacroMapMetric.EQUITY_YTD,
}


def normalize_map_metric(value: str | None) -> MacroMapMetric:
    if isinstance(value, MacroMapMetric):
        return value
    return MAP_METRIC_ALIASES.get((value or "GDP").strip().upper(), MacroMapMetric.GDP)


class MacroCountryService:
    OFFICIAL_TTL = 24 * 3600
    POLICY_TTL = 6 * 3600
    MARKET_TTL = 15 * 60

    def __init__(
        self,
        *,
        cache: SQLiteCache | None = None,
        countries: CountryRegistry = COUNTRY_REGISTRY,
        world_bank: WorldBankProvider | None = None,
        eurostat: EurostatProvider | None = None,
        policy: FredPolicyRateProvider | None = None,
        market: MarketService | None = None,
        calendar: MacroService | None = None,
    ) -> None:
        self.cache = cache or SQLiteCache()
        self.countries = countries
        self.world_bank = world_bank or WorldBankProvider()
        self.eurostat = eurostat or EurostatProvider()
        self.policy = policy or FredPolicyRateProvider()
        self.market = market or MarketService(cache=self.cache)
        self.calendar = calendar or MacroService()

    async def world_dataset(
        self,
        metric: MacroMapMetric | str = MacroMapMetric.GDP,
        region: str = "WORLD",
    ) -> MacroMapDataset:
        selected = normalize_map_metric(metric)
        profiles = list(self.countries.region(region))
        values = await self._metric_values(selected.value, profiles)
        return MacroMapDataset(
            metric=selected,
            values=[CountryMapValue(profile, values.get(profile.iso3)) for profile in profiles],
        )

    async def get_snapshot(self, country: str) -> CountryMacroSnapshot:
        profile = self.countries.resolve(country)
        if profile is None:
            raise ValueError(f"Unknown country: {country}")
        codes = (*MACRO_CODES, "10Y", "EQUITY", "FX_YTD")
        loaded = await asyncio.gather(*(self._metric_values(code, [profile]) for code in codes))
        indicators = {
            code: values[profile.iso3]
            for code, values in zip(codes, loaded)
            if profile.iso3 in values
        }
        events = await self._events(profile)
        market_status = (
            self.market.registry.market_status(profile.main_equity_index)
            if profile.main_equity_index
            else "N/A"
        )
        return CountryMacroSnapshot(profile, indicators, events, market_status)

    async def _metric_values(
        self,
        metric: str,
        profiles: list[CountryProfile],
    ) -> dict[str, MacroObservation]:
        code = metric.upper()
        cached, missing = self._read_cache(profiles, code)
        if not missing:
            return cached
        try:
            if code in WORLD_BANK_METRICS or code in EUROSTAT_METRICS:
                fresh = await self._official_macro_values(code, missing)
                ttl = self.OFFICIAL_TTL
            elif code == "RATE":
                fresh = await self.policy.latest(missing)
                ttl = self.POLICY_TTL
            elif code == "10Y":
                fresh = await self._sovereign_yields(missing)
                ttl = self.MARKET_TTL
            elif code == "EQUITY":
                fresh = await self._market_returns(missing, equity=True)
                ttl = self.MARKET_TTL
            elif code == "FX_YTD":
                fresh = await self._market_returns(missing, equity=False)
                ttl = self.MARKET_TTL
            else:
                fresh = {}
                ttl = self.OFFICIAL_TTL
        except Exception as exc:
            LOGGER.warning("macro country provider fallback metric=%s error=%s", code, exc)
            fresh = {}
            ttl = self.OFFICIAL_TTL
        for iso3, observation in fresh.items():
            if observation.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
                cached[iso3] = observation
                self.cache.set_json(self._cache_key(iso3, code), _observation_to_dict(observation), ttl)
        for profile in missing:
            if profile.iso3 in cached:
                continue
            stale = self.cache.get_stale_json(self._cache_key(profile.iso3, code))
            if isinstance(stale, dict):
                cached[profile.iso3] = replace(
                    _observation_from_dict(stale),
                    quality=DataQuality.CACHED,
                    status="CACHED",
                )
        return cached

    def _read_cache(
        self,
        profiles: list[CountryProfile],
        metric: str,
    ) -> tuple[dict[str, MacroObservation], list[CountryProfile]]:
        values: dict[str, MacroObservation] = {}
        missing: list[CountryProfile] = []
        for profile in profiles:
            payload = self.cache.get_json(self._cache_key(profile.iso3, metric))
            if isinstance(payload, dict):
                observation = _observation_from_dict(payload)
                if observation.quality != DataQuality.MOCK:
                    values[profile.iso3] = observation
                    continue
            missing.append(profile)
        return values, missing

    async def _official_macro_values(
        self,
        code: str,
        profiles: list[CountryProfile],
    ) -> dict[str, MacroObservation]:
        tasks: list[tuple[str, object]] = []
        if code in WORLD_BANK_METRICS:
            tasks.append(("World Bank", self.world_bank.latest([profile.iso3 for profile in profiles], code)))
        if code in EUROSTAT_METRICS:
            tasks.append(("Eurostat", self.eurostat.latest(profiles, code)))
        loaded = await asyncio.gather(*(task for _name, task in tasks), return_exceptions=True)
        result: dict[str, MacroObservation] = {}
        for (name, _task), observations in zip(tasks, loaded):
            if isinstance(observations, Exception):
                LOGGER.warning("macro provider=%s metric=%s error=%s", name, code, observations)
                continue
            result.update(observations)
        return result

    async def _sovereign_yields(self, profiles: list[CountryProfile]) -> dict[str, MacroObservation]:
        selected = [profile for profile in profiles if profile.sovereign_10y]
        if not selected:
            return {}
        quotes = await self.market.government_quotes([profile.sovereign_10y for profile in selected])
        return {
            profile.iso3: _quote_observation("10Y", quote, "%")
            for profile, quote in zip(selected, quotes)
            if quote.price is not None and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        }

    async def _market_returns(
        self,
        profiles: list[CountryProfile],
        *,
        equity: bool,
    ) -> dict[str, MacroObservation]:
        selected = [
            profile
            for profile in profiles
            if (profile.main_equity_index if equity else profile.fx_reference)
        ]
        symbols = [profile.main_equity_index if equity else profile.fx_reference for profile in selected]
        histories = await asyncio.gather(
            *(self.market.history(symbol, "YTD", "1d", allow_mock=False) for symbol in symbols),
            return_exceptions=True,
        )
        result: dict[str, MacroObservation] = {}
        code = "EQUITY" if equity else "FX_YTD"
        for profile, history in zip(selected, histories):
            if isinstance(history, Exception):
                continue
            observation = _history_return_observation(code, history)
            if observation is not None:
                result[profile.iso3] = observation
        return result

    async def _events(self, profile: CountryProfile) -> list[EconomicEvent]:
        try:
            events = await self.calendar.calendar(profile.iso2)
        except Exception as exc:
            LOGGER.warning("country calendar unavailable country=%s error=%s", profile.iso2, exc)
            return []
        real = [
            event
            for event in events
            if event.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        return sorted(
            real,
            key=lambda event: event.time or datetime.max.replace(tzinfo=timezone.utc),
        )[:5]

    @staticmethod
    def _cache_key(iso3: str, metric: str) -> str:
        return f"macro_country:v2:{iso3.upper()}:{metric.lower()}"


def _quote_observation(code: str, quote: Quote, unit: str) -> MacroObservation:
    return MacroObservation(
        code=code,
        value=quote.price,
        unit=unit,
        period=quote.timestamp.date().isoformat(),
        source=quote.provider,
        quality=quote.quality,
        status=str(quote.quality),
        timestamp=quote.timestamp,
    )


def _history_return_observation(code: str, history: PriceHistory) -> MacroObservation | None:
    if len(history.bars) < 2 or history.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
        return None
    first = history.bars[0].close
    last = history.bars[-1].close
    if not first:
        return None
    return MacroObservation(
        code=code,
        value=(last / first - 1.0) * 100.0,
        unit="%",
        period=f"{history.bars[0].timestamp.date().isoformat()} / {history.bars[-1].timestamp.date().isoformat()}",
        source=history.provider,
        quality=history.quality,
        status=str(history.quality),
        timestamp=history.timestamp,
    )


def _observation_to_dict(value: MacroObservation) -> dict[str, Any]:
    return {
        "code": value.code,
        "value": value.value,
        "unit": value.unit,
        "period": value.period,
        "source": value.source,
        "quality": str(value.quality),
        "status": value.status,
        "timestamp": value.timestamp.isoformat(),
    }


def _observation_from_dict(data: dict[str, Any]) -> MacroObservation:
    return MacroObservation(
        code=str(data.get("code") or ""),
        value=float(data["value"]) if data.get("value") is not None else None,
        unit=str(data.get("unit") or ""),
        period=str(data.get("period") or ""),
        source=str(data.get("source") or "UNKNOWN"),
        quality=DataQuality(str(data.get("quality") or DataQuality.UNAVAILABLE)),
        status=str(data.get("status") or "UNAVAILABLE"),
        timestamp=(
            datetime.fromisoformat(str(data.get("timestamp")))
            if data.get("timestamp")
            else datetime.now(timezone.utc)
        ),
    )
