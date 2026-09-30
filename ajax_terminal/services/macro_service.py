from __future__ import annotations

import logging

from ajax_terminal.models.macro import EconomicEvent, MacroIndicator
from ajax_terminal.providers.fred import FredProvider

LOGGER = logging.getLogger(__name__)


class MacroService:
    def __init__(self) -> None:
        self.providers = [FredProvider()]

    async def monitor(self, country: str) -> list[MacroIndicator]:
        for provider in self.providers:
            try:
                return await provider.indicators(country)
            except Exception as exc:
                LOGGER.warning("macro fallback provider=%s country=%s error=%s", provider.name, country, exc)
        return []

    async def indicator(self, code: str, country: str) -> MacroIndicator | None:
        indicators = await self.monitor(country)
        normalized = code.upper()
        return next((item for item in indicators if item.code.upper() == normalized or normalized in item.name.upper()), None)

    async def calendar(self, country: str | None = None) -> list[EconomicEvent]:
        for provider in self.providers:
            try:
                return await provider.calendar(country)
            except Exception as exc:
                LOGGER.warning("calendar fallback provider=%s country=%s error=%s", provider.name, country, exc)
        return []
