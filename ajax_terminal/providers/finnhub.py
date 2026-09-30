from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import requests

from ajax_terminal.config import setting
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.providers.base import ProviderError


class FinnhubProvider:
    name = "Finnhub"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else setting("FINNHUB_KEY")).strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def quote(self, symbol: str) -> Quote:
        if not self.api_key:
            raise ProviderError("Finnhub API key is not configured")
        instrument = INSTRUMENT_REGISTRY.resolve(symbol)
        if instrument.asset_class != AssetClass.EQUITY:
            raise ProviderError(f"Finnhub streaming quote is not enabled for {symbol}")
        try:
            response = await asyncio.to_thread(
                requests.get,
                "https://finnhub.io/api/v1/quote",
                params={"symbol": instrument.symbol, "token": self.api_key},
                timeout=10,
                headers={"User-Agent": "AJAX-Financial-Terminal/0.1"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"Finnhub quote unavailable for {instrument.symbol}") from exc
        price = _number(payload.get("c"))
        timestamp = _number(payload.get("t"))
        if price is None or price <= 0:
            raise ProviderError(f"Finnhub returned no entitled quote for {instrument.symbol}")
        return Quote(
            symbol=instrument.symbol,
            name=instrument.name,
            price=price,
            change=_number(payload.get("d")),
            change_percent=_number(payload.get("dp")),
            currency=instrument.currency,
            asset_class=str(instrument.asset_class),
            day_high=_number(payload.get("h")),
            day_low=_number(payload.get("l")),
            open_price=_number(payload.get("o")),
            previous_close=_number(payload.get("pc")),
            provider=self.name,
            quality=DataQuality.REALTIME,
            timestamp=(
                datetime.fromtimestamp(timestamp, timezone.utc)
                if timestamp is not None and timestamp > 0
                else datetime.now(timezone.utc)
            ),
        )


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
