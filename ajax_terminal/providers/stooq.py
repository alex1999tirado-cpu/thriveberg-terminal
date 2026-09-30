from __future__ import annotations

from ajax_terminal.providers.base import ProviderError


class StooqProvider:
    name = "Stooq"

    async def quote(self, symbol: str):  # pragma: no cover - placeholder
        raise ProviderError(f"Stooq quote adapter not implemented for {symbol}")
