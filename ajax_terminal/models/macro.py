from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum

from ajax_terminal.models.quote import DataQuality


@dataclass(slots=True)
class MacroIndicator:
    code: str
    country: str
    name: str
    value: float | None
    unit: str
    period: str = ""
    previous: float | None = None
    consensus: float | None = None
    surprise: float | None = None
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class EconomicEvent:
    time: datetime | None
    country: str
    event: str
    period: str = ""
    actual: str = ""
    consensus: str = ""
    previous: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE


@dataclass(slots=True)
class MacroSeriesPoint:
    observation_date: date
    value: float | None


class MacroMapMetric(StrEnum):
    GDP = "GDP"
    CPI = "CPI"
    UNEMPLOYMENT = "UNEMP"
    POLICY_RATE = "RATE"
    SOVEREIGN_10Y = "10Y"
    EQUITY_YTD = "EQUITY"


@dataclass(frozen=True, slots=True)
class CountryProfile:
    iso2: str
    iso3: str
    name: str
    map_name: str
    region: str
    development: str
    currency: str
    central_bank: str
    main_equity_index: str = ""
    sovereign_10y: str = ""
    fx_reference: str = ""
    policy_series: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(slots=True)
class MacroObservation:
    code: str
    value: float | None
    unit: str
    period: str
    source: str
    quality: DataQuality
    status: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class CountryMacroSnapshot:
    profile: CountryProfile
    indicators: dict[str, MacroObservation]
    events: list[EconomicEvent] = field(default_factory=list)
    market_status: str = "N/A"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def indicator(self, code: str) -> MacroObservation | None:
        return self.indicators.get(code.upper())


@dataclass(frozen=True, slots=True)
class CountryMapValue:
    profile: CountryProfile
    observation: MacroObservation | None


@dataclass(slots=True)
class MacroMapDataset:
    metric: MacroMapMetric
    values: list[CountryMapValue]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def available(self) -> list[CountryMapValue]:
        return [item for item in self.values if item.observation is not None and item.observation.value is not None]
