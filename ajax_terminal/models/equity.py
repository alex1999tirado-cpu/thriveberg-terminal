from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ajax_terminal.models.quote import DataQuality, FinancialPeriod, StatementType


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CompanyProfile:
    symbol: str
    name: str
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    website: str = ""
    employees: int | None = None
    description: str = ""
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class FinancialMetric:
    name: str
    value: float | None
    period: str
    unit: str = "currency"
    status: str = "ACTUAL"


@dataclass(slots=True)
class FinancialStatement:
    symbol: str
    statement_type: StatementType
    frequency: str
    periods: list[FinancialPeriod]
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class Estimate:
    metric: str
    period: str
    end_date: date | None = None
    average: float | None = None
    low: float | None = None
    high: float | None = None
    year_ago: float | None = None
    growth_percent: float | None = None
    analyst_count: int | None = None
    revision_7d: float | None = None
    revision_30d: float | None = None


@dataclass(slots=True)
class EstimateSet:
    symbol: str
    name: str
    currency: str
    estimates: list[Estimate]
    earnings_date: datetime | None = None
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class AnalystConsensus:
    symbol: str
    name: str
    recommendation: str = ""
    recommendation_score: float | None = None
    analyst_count: int | None = None
    strong_buy: int | None = None
    buy: int | None = None
    hold: int | None = None
    sell: int | None = None
    strong_sell: int | None = None
    target_low: float | None = None
    target_mean: float | None = None
    target_median: float | None = None
    target_high: float | None = None
    current_price: float | None = None
    upside_percent: float | None = None
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class DividendRecord:
    ex_date: date
    amount: float
    currency: str = ""


@dataclass(slots=True)
class DividendAnalysis:
    symbol: str
    name: str
    records: list[DividendRecord]
    indicated_rate: float | None = None
    yield_percent: float | None = None
    payout_ratio_percent: float | None = None
    five_year_average_yield: float | None = None
    ex_dividend_date: date | None = None
    payment_date: date | None = None
    currency: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class CorporateEvent:
    symbol: str
    company: str
    event_type: str
    event_date: datetime
    detail: str = ""
    estimated: bool = False
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)


@dataclass(slots=True)
class PeerCompany:
    symbol: str
    name: str
    price: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    ev_ebitda: float | None = None
    price_book: float | None = None
    revenue_growth: float | None = None
    operating_margin: float | None = None
    roe: float | None = None
    dividend_yield: float | None = None
    quality: DataQuality = DataQuality.UNAVAILABLE


@dataclass(slots=True)
class RelativeValuation:
    symbol: str
    peers: list[PeerCompany]
    automatic: bool
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)
    message: str = ""
    peer_sector: str = ""
    peer_industry: str = ""


@dataclass(frozen=True, slots=True)
class ScreenerFilter:
    field: str
    operator: str
    value: float | str


@dataclass(slots=True)
class ScreenerResult:
    symbol: str
    name: str
    country: str = ""
    sector: str = ""
    price: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    dividend_yield: float | None = None
    roe: float | None = None
    roic: float | None = None
    revenue_growth: float | None = None
    operating_margin: float | None = None
    volume: float | None = None
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE


@dataclass(slots=True)
class ScreenerPage:
    filters: list[ScreenerFilter]
    results: list[ScreenerResult]
    universe: str
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)
    message: str = ""


@dataclass(slots=True)
class FinancialAnalysis:
    symbol: str
    name: str
    currency: str
    periods: list[str]
    metrics: dict[str, list[FinancialMetric]]
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=_now)
    message: str = ""
