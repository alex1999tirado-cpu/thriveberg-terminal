from __future__ import annotations

from ajax_terminal.providers.base import ProviderError


class AlphaVantageProvider:
    name = "Alpha Vantage"

    async def quote(self, symbol: str):  # pragma: no cover - requires API key
        raise ProviderError(f"Alpha Vantage quote adapter requires API configuration for {symbol}")
