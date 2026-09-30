from __future__ import annotations

import asyncio
import csv
import io
import time as time_module
from datetime import date, datetime

import requests

from ajax_terminal.providers.base import ProviderError


_OBSERVATION_CACHE: dict[str, list[tuple[date, float]]] = {}


async def fred_observations(series_id: str, start: str = "2020-01-01") -> list[tuple[date, float]]:
    cache_key = f"{series_id}:{start}"
    cached = _OBSERVATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    def read() -> list[tuple[date, float]]:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
        response = None
        for attempt in range(2):
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AJAX-Terminal/0.1"},
                    timeout=8,
                )
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt:
                    raise
                time_module.sleep(0.3)
        if response is None:
            raise ProviderError(f"FRED response unavailable for {series_id}")
        rows: list[tuple[date, float]] = []
        for item in csv.DictReader(io.StringIO(response.text)):
            raw_value = item.get(series_id)
            if not raw_value or raw_value == ".":
                continue
            rows.append((datetime.strptime(item["observation_date"], "%Y-%m-%d").date(), float(raw_value)))
        _OBSERVATION_CACHE[cache_key] = rows
        return rows

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:  # pragma: no cover - depends on network availability
        raise ProviderError(str(exc)) from exc
