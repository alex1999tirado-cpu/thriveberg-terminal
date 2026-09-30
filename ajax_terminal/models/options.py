from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ajax_terminal.models.quote import DataQuality


@dataclass(slots=True)
class OptionContract:
    contract_symbol: str
    option_type: str
    strike: float
    expiry: date
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    vendor_implied_volatility: float | None = None
    calculated_implied_volatility: float | None = None
    delta: float | None = None
    in_the_money: bool = False
    last_trade: datetime | None = None
    currency: str = ""

    @property
    def market_price(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask >= self.bid:
            return (self.bid + self.ask) / 2.0
        if self.last is not None and self.last > 0:
            return self.last
        return None


@dataclass(slots=True)
class OptionChain:
    symbol: str
    name: str
    spot: float | None
    currency: str
    expirations: list[date]
    selected_expiry: date | None
    calls: list[OptionContract]
    puts: list[OptionContract]
    provider: str
    quality: DataQuality
    dividend_yield: float = 0.0
    underlying_change: float | None = None
    underlying_change_percent: float | None = None
    market_status: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""


@dataclass(frozen=True, slots=True)
class OptionMarketContext:
    rate: float
    dividend_yield: float
    rate_source: str
    dividend_source: str
    rate_available: bool = True


@dataclass(frozen=True, slots=True)
class VolatilityPoint:
    expiry: date
    days_to_expiry: int
    strike: float
    moneyness: float
    option_type: str
    market_price: float
    implied_volatility: float
    delta: float
    volume: int | None
    open_interest: int | None


@dataclass(slots=True)
class VolatilitySlice:
    expiry: date
    days_to_expiry: int
    points: list[VolatilityPoint]
    grid: dict[float, float | None]


@dataclass(slots=True)
class VolatilitySurface:
    symbol: str
    name: str
    spot: float | None
    currency: str
    slices: list[VolatilitySlice]
    moneyness_grid: tuple[float, ...]
    rate: float
    dividend_yield: float
    provider: str
    quality: DataQuality
    rate_available: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = ""
