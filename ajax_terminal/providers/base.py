from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, Protocol, TypeVar

from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    CorporateAction,
    CorporateEvent,
    DividendAnalysis,
    EstimateSet,
    ScreenerFilter,
    ScreenerPage,
)
from ajax_terminal.models.macro import EconomicEvent, MacroIndicator
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import Curve, EquityFundamentals, FinancialStatements, PriceHistory, Quote, StatementType

T = TypeVar("T")


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ProviderResult(Generic[T]):
    value: T
    provider: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""


class MarketDataProvider(Protocol):
    name: str

    async def quote(self, symbol: str) -> Quote:
        ...

    async def fundamentals(self, symbol: str) -> EquityFundamentals:
        ...

    async def historical(self, symbol: str, period: str, interval: str) -> PriceHistory:
        ...

    async def financial_statements(self, symbol: str, statement_type: StatementType) -> FinancialStatements:
        ...


class CurveProvider(Protocol):
    name: str

    async def curve(self, currency: str) -> Curve:
        ...


class MacroProvider(Protocol):
    name: str

    async def indicators(self, country: str) -> list[MacroIndicator]:
        ...

    async def calendar(self, country: str | None = None) -> list[EconomicEvent]:
        ...


class NewsProvider(Protocol):
    name: str

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        ...


class FundamentalsProvider(Protocol):
    name: str

    async def company_profile(self, symbol: str) -> CompanyProfile:
        ...

    async def fundamentals(self, symbol: str) -> EquityFundamentals:
        ...

    async def financial_statements(self, symbol: str, statement_type: StatementType) -> FinancialStatements:
        ...


class EstimatesProvider(Protocol):
    name: str

    async def estimates(self, symbol: str) -> EstimateSet:
        ...


class AnalystProvider(Protocol):
    name: str

    async def analyst_consensus(self, symbol: str) -> AnalystConsensus:
        ...


class PeerProvider(Protocol):
    name: str

    async def peers(self, symbol: str, limit: int = 5) -> list[str]:
        ...


class DividendProvider(Protocol):
    name: str

    async def dividends(self, symbol: str) -> DividendAnalysis:
        ...


class EventsProvider(Protocol):
    name: str

    async def events(self, symbol: str) -> list[CorporateEvent]:
        ...


class CorporateActionsProvider(Protocol):
    name: str

    async def corporate_actions(self, symbol: str) -> list[CorporateAction]:
        ...


class ScreenerProvider(Protocol):
    name: str

    async def screener(self, filters: list[ScreenerFilter], limit: int = 30) -> ScreenerPage:
        ...
