from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum


class DataQuality(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    CACHED = "CACHED"
    MOCK = "MOCK"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(slots=True)
class Quote:
    symbol: str
    name: str
    price: float | None
    change: float | None = None
    change_percent: float | None = None
    currency: str = ""
    asset_class: str = "UNKNOWN"
    day_high: float | None = None
    day_low: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    open_price: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    market_status: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bid: float | None = None
    ask: float | None = None
    estimated: bool = False
    methodology: str = ""


@dataclass(slots=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(slots=True)
class PriceHistory:
    symbol: str
    period: str
    interval: str
    bars: list[PriceBar]
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class CurvePoint:
    tenor: str
    years: float
    yield_pct: float
    change_bp: float | None = None


@dataclass(slots=True)
class Curve:
    currency: str
    name: str
    points: list[CurvePoint]
    provider: str
    quality: DataQuality
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    method: str = "OBSERVED"

    def point(self, tenor: str) -> CurvePoint | None:
        target = tenor.upper()
        return next((point for point in self.points if point.tenor.upper() == target), None)


@dataclass(slots=True)
class EquityFundamentals:
    symbol: str
    name: str
    market_cap: float | None = None
    enterprise_value: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    ev_ebitda: float | None = None
    price_book: float | None = None
    dividend_yield: float | None = None
    revenue: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    net_income: float | None = None
    eps: float | None = None
    free_cash_flow: float | None = None
    roe: float | None = None
    roic: float | None = None
    net_debt: float | None = None
    gross_profit: float | None = None
    operating_cash_flow: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    roa: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    beta: float | None = None
    shares_outstanding: float | None = None
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StatementType(StrEnum):
    INCOME = "INCOME"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW = "CASH_FLOW"


@dataclass(slots=True)
class FinancialPeriod:
    period: str
    end_date: date | None
    values: dict[str, float | None]
    source_form: str = ""
    filed_date: date | None = None
    accession_number: str = ""
    derived: bool = False


@dataclass(slots=True)
class FinancialStatements:
    symbol: str
    name: str
    statement_type: StatementType
    annual: list[FinancialPeriod]
    quarterly: list[FinancialPeriod]
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    metric_labels: dict[str, str] = field(default_factory=dict)
    metric_order: list[str] = field(default_factory=list)
    metric_sections: dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class MarketSnapshot:
    quote: Quote
    ytd_change_percent: float | None
    market_status: str
