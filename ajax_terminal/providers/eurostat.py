from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any

import requests

from ajax_terminal.models.macro import CountryProfile, MacroObservation
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError


@dataclass(frozen=True, slots=True)
class _EurostatSeries:
    dataset: str
    filters: tuple[tuple[str, str], ...]
    unit: str


EUROSTAT_METRICS: dict[str, _EurostatSeries] = {
    "CPI": _EurostatSeries(
        "prc_hicp_minr",
        (("unit", "RCH_A"), ("coicop18", "TOTAL")),
        "% y/y",
    ),
    "CORE_CPI": _EurostatSeries(
        "prc_hicp_minr",
        (("unit", "RCH_A"), ("coicop18", "TOT_X_NRG_FOOD")),
        "% y/y",
    ),
    "UNEMP": _EurostatSeries(
        "une_rt_m",
        (("s_adj", "SA"), ("age", "TOTAL"), ("unit", "PC_ACT"), ("sex", "T")),
        "%",
    ),
    "RETAIL": _EurostatSeries(
        "sts_trtu_m",
        (
            ("indic_bt", "VOL_SLS"),
            ("nace_r2", "G47"),
            ("s_adj", "SCA"),
            ("unit", "PCH_PRE"),
        ),
        "% m/m",
    ),
    "INDUSTRIAL": _EurostatSeries(
        "sts_inpr_m",
        (
            ("indic_bt", "PRD"),
            ("nace_r2", "B-D"),
            ("s_adj", "SCA"),
            ("unit", "PCH_PRE"),
        ),
        "% m/m",
    ),
    "DEBT_GDP": _EurostatSeries(
        "gov_10dd_edpt1",
        (("unit", "PC_GDP"), ("sector", "S13"), ("na_item", "GD")),
        "% GDP",
    ),
}

_EUROSTAT_GEOS = {
    "GB",
    "DE",
    "FR",
    "ES",
    "IT",
    "CH",
    "SE",
    "NO",
    "PL",
    "NL",
    "PT",
    "GR",
    "TR",
}
_EURO_AREA_GEO = "EA20"


class EurostatProvider:
    """Official Eurostat observations exposed through its free Statistics API."""

    name = "Eurostat"
    base_url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

    async def latest(
        self,
        countries: list[CountryProfile],
        metric: str,
    ) -> dict[str, MacroObservation]:
        code = metric.upper()
        try:
            series = EUROSTAT_METRICS[code]
        except KeyError as exc:
            raise ProviderError(f"Eurostat metric is not configured: {metric}") from exc

        selected = [country for country in countries if self._geo(country) is not None]
        if not selected:
            return {}
        geo_to_iso3 = {self._geo(country): country.iso3 for country in selected}
        params: list[tuple[str, str | int]] = [
            ("lang", "en"),
            ("lastTimePeriod", 12),
            *series.filters,
            *(("geo", geo) for geo in geo_to_iso3 if geo),
        ]

        def read() -> Any:
            response = requests.get(
                f"{self.base_url}/{series.dataset}",
                params=params,
                headers={"Accept": "application/json", "User-Agent": "THRIVEBERG-Terminal/0.1"},
                timeout=(5, 15),
            )
            response.raise_for_status()
            return response.json()

        try:
            payload = await asyncio.to_thread(read)
            return normalize_eurostat_latest(payload, code, series.unit, geo_to_iso3)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    @staticmethod
    def _geo(country: CountryProfile) -> str | None:
        if country.iso3 == "EMU":
            return _EURO_AREA_GEO
        return country.iso2 if country.iso2 in _EUROSTAT_GEOS else None


def normalize_eurostat_latest(
    payload: Any,
    metric: str,
    unit: str,
    geo_to_iso3: dict[str | None, str],
) -> dict[str, MacroObservation]:
    if not isinstance(payload, dict):
        raise ProviderError("Eurostat returned an invalid response")
    dimension_ids = payload.get("id")
    sizes = payload.get("size")
    dimensions = payload.get("dimension")
    values = payload.get("value")
    if (
        not isinstance(dimension_ids, list)
        or not isinstance(sizes, list)
        or not isinstance(dimensions, dict)
        or not isinstance(values, dict)
        or "geo" not in dimension_ids
        or "time" not in dimension_ids
    ):
        raise ProviderError("Eurostat returned an invalid JSON-stat dataset")

    codes_by_dimension = [
        _ordered_category_codes(dimensions.get(identifier)) for identifier in dimension_ids
    ]
    geo_index = dimension_ids.index("geo")
    time_index = dimension_ids.index("time")
    statuses = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    latest: dict[str, MacroObservation] = {}
    for raw_index, raw_value in values.items():
        try:
            flat_index = int(raw_index)
            value = float(raw_value)
            coordinates = _decode_index(flat_index, [int(size) for size in sizes])
            geo = codes_by_dimension[geo_index][coordinates[geo_index]]
            period = codes_by_dimension[time_index][coordinates[time_index]]
        except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        iso3 = geo_to_iso3.get(geo)
        if not iso3:
            continue
        existing = latest.get(iso3)
        if existing is not None and existing.period >= period:
            continue
        status_code = str(statuses.get(str(raw_index)) or "").lower()
        status = "OFFICIAL"
        if "p" in status_code:
            status = "OFFICIAL PRELIMINARY"
        elif "e" in status_code:
            status = "OFFICIAL ESTIMATE"
        observed = _period_datetime(period)
        latest[iso3] = MacroObservation(
            code=metric,
            value=value,
            unit=unit,
            period=period,
            source="Eurostat",
            quality=DataQuality.DELAYED,
            status=status,
            timestamp=datetime.combine(observed.date(), time(), timezone.utc),
        )
    return latest


def _ordered_category_codes(node: Any) -> list[str]:
    category = node.get("category") if isinstance(node, dict) else None
    index = category.get("index") if isinstance(category, dict) else None
    if isinstance(index, dict):
        return [code for code, _position in sorted(index.items(), key=lambda item: int(item[1]))]
    if isinstance(index, list):
        return [str(code) for code in index]
    return []


def _decode_index(flat_index: int, sizes: list[int]) -> list[int]:
    coordinates = [0] * len(sizes)
    remaining = flat_index
    for index in range(len(sizes) - 1, -1, -1):
        size = sizes[index]
        if size <= 0:
            raise ValueError("Invalid JSON-stat dimension size")
        coordinates[index] = remaining % size
        remaining //= size
    return coordinates


def _period_datetime(period: str) -> datetime:
    parts = period.replace("Q", "-").split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        return datetime(year, min(max(month, 1), 12), 1, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
