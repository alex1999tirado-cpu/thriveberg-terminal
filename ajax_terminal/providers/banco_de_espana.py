from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory, Quote
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period


SERIES = {
    "ES2Y": ("D_G0B1F0ZD", "Spain Bono 1-2Y Yield"),
    "ES5Y": ("D_G0B1F0ZO", "Spain Bono 5Y Yield"),
    "ES10Y": ("D_G0B1F0ZP", "Spain Bono 10Y Yield"),
    "ES15Y": ("D_G0B1F0ZQ", "Spain Bono 15Y Yield"),
}


class BancoDeEspanaProvider:
    """Official daily Spanish government-bond secondary-market yields."""

    name = "Banco de Espana"
    BASE_URL = "https://app.bde.es/bierest/resources/srdatosapp/listaSeries"

    async def quote(self, symbol: str) -> Quote:
        clean = symbol.upper()
        _series_id, name = _series(clean)
        observations = await self._observations(clean, "3M")
        if not observations:
            raise ProviderError(f"Banco de Espana yield unavailable for {clean}")
        latest_at, latest = observations[-1]
        previous = observations[-2][1] if len(observations) > 1 else None
        change = latest - previous if previous is not None else None
        change_percent = change / previous * 100.0 if change is not None and previous else None
        return Quote(
            symbol=clean,
            name=name,
            price=latest,
            change=change,
            change_percent=change_percent,
            currency="%",
            asset_class="RATE",
            previous_close=previous,
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=latest_at,
        )

    async def historical(
        self,
        symbol: str,
        period: str = "1Y",
        interval: str | None = None,
    ) -> PriceHistory:
        clean = symbol.upper()
        _series(clean)
        normalized = normalize_history_period(period)
        selected_interval = normalize_history_interval(normalized, interval)
        observations = await self._history_observations(clean, normalized)
        if not observations:
            raise ProviderError(f"Banco de Espana yield history unavailable for {clean}")
        bars = [
            PriceBar(timestamp=observed_at, open=value, high=value, low=value, close=value)
            for observed_at, value in observations
        ]
        return PriceHistory(
            symbol=clean,
            period=normalized,
            interval=selected_interval,
            bars=bars,
            currency="%",
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=bars[-1].timestamp,
        )

    async def _history_observations(
        self,
        symbol: str,
        period: str,
    ) -> list[tuple[datetime, float]]:
        now = datetime.now(timezone.utc)
        if period == "5Y":
            batches = await asyncio.gather(
                *(self._observations(symbol, str(year)) for year in range(now.year - 4, now.year + 1))
            )
            observations = sorted({item[0]: item for batch in batches for item in batch}.values())
        else:
            api_range = str(now.year) if period == "YTD" else "12M" if period in {"6M", "1Y"} else "3M"
            observations = await self._observations(symbol, api_range)

        lookbacks = {
            "1D": timedelta(days=7),
            "5D": timedelta(days=14),
            "1M": timedelta(days=31),
            "3M": timedelta(days=93),
            "6M": timedelta(days=186),
            "1Y": timedelta(days=370),
            "5Y": timedelta(days=5 * 366),
        }
        if period == "YTD":
            return [item for item in observations if item[0].year == now.year]
        cutoff = now - lookbacks.get(period, timedelta(days=370))
        return [item for item in observations if item[0] >= cutoff]

    async def _observations(self, symbol: str, api_range: str) -> list[tuple[datetime, float]]:
        series_id, _name = _series(symbol)

        def read() -> list[dict[str, Any]]:
            response = requests.get(
                self.BASE_URL,
                params={"idioma": "es", "series": series_id, "rango": api_range},
                headers={
                    "Accept": "application/json",
                    "Referer": "https://www.bde.es/",
                    "User-Agent": "THRIVEBERG-Terminal/0.1",
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ProviderError("Banco de Espana returned an invalid response")
            return payload

        try:
            payload = await asyncio.to_thread(read)
            if not payload:
                return []
            row = payload[0]
            dates = row.get("fechas", [])
            values = row.get("valores", [])
            observations = [
                (_parse_datetime(observed_at), float(value))
                for observed_at, value in zip(dates, values)
                if value is not None
            ]
            observations.sort(key=lambda item: item[0])
            return observations
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network path
            raise ProviderError(str(exc)) from exc


def _series(symbol: str) -> tuple[str, str]:
    try:
        return SERIES[symbol]
    except KeyError as exc:
        raise ProviderError(f"No Banco de Espana series mapping for {symbol}") from exc


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
