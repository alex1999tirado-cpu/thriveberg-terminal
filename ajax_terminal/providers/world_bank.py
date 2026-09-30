from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from typing import Any

import requests

from ajax_terminal.models.macro import MacroObservation
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError


WORLD_BANK_METRICS: dict[str, tuple[str, str, str]] = {
    "GDP": ("NY.GDP.MKTP.KD.ZG", "GDP Growth", "%"),
    "CPI": ("FP.CPI.TOTL.ZG", "CPI Inflation", "%"),
    "UNEMP": ("SL.UEM.TOTL.ZS", "Unemployment", "%"),
    "DEBT_GDP": ("GC.DOD.TOTL.GD.ZS", "Central Government Debt / GDP", "% GDP"),
    "CURRENT_ACCOUNT": ("BN.CAB.XOKA.GD.ZS", "Current Account / GDP", "% GDP"),
}


class WorldBankProvider:
    name = "World Bank"

    async def latest(self, countries: list[str], metric: str) -> dict[str, MacroObservation]:
        code = metric.upper()
        try:
            indicator, name, unit = WORLD_BANK_METRICS[code]
        except KeyError as exc:
            raise ProviderError(f"World Bank metric is not configured: {metric}") from exc
        if not countries:
            return {}
        current_year = datetime.now(timezone.utc).year
        selected = sorted(set(countries))
        batches = [selected[index : index + 6] for index in range(0, len(selected), 6)]

        def read(batch: list[str]) -> Any:
            country_path = ";".join(batch)
            url = (
                f"https://api.worldbank.org/v2/country/{country_path}/indicator/{indicator}"
                f"?format=json&per_page=500&date={current_year - 8}:{current_year}"
            )
            response = requests.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "THRIVEBERG-Terminal/0.1"},
                timeout=(5, 10),
            )
            response.raise_for_status()
            return response.json()

        try:
            payloads = await asyncio.gather(
                *(asyncio.to_thread(read, batch) for batch in batches),
                return_exceptions=True,
            )
            result: dict[str, MacroObservation] = {}
            errors: list[Exception] = []
            for payload in payloads:
                if isinstance(payload, Exception):
                    errors.append(payload)
                    continue
                result.update(normalize_world_bank_latest(payload, code, name, unit))
            if not result and errors:
                raise ProviderError(str(errors[0]))
            return result
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc


def normalize_world_bank_latest(
    payload: Any,
    metric: str,
    name: str,
    unit: str,
) -> dict[str, MacroObservation]:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ProviderError("World Bank returned an invalid response")
    latest: dict[str, MacroObservation] = {}
    for row in payload[1]:
        if not isinstance(row, dict) or row.get("value") is None:
            continue
        iso3 = str(row.get("countryiso3code") or "").upper()
        period = str(row.get("date") or "")
        if not iso3 or not period:
            continue
        try:
            value = float(row["value"])
            observed = datetime(int(period), 1, 1, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        existing = latest.get(iso3)
        if existing is not None and existing.period >= period:
            continue
        latest[iso3] = MacroObservation(
            code=metric,
            value=value,
            unit=unit,
            period=period,
            source="World Bank",
            quality=DataQuality.DELAYED,
            status="LATEST OFFICIAL",
            timestamp=datetime.combine(observed.date(), time(), timezone.utc),
        )
    return latest
