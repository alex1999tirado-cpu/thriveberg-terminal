from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class AssetClass(StrEnum):
    FX = "FX"
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    RATE = "RATE"
    BOND = "BOND"
    COMMODITY = "COMMODITY"
    OPTION = "OPTION"
    MACRO = "MACRO"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str = ""
    currency: str = ""
    provider_symbol: str = ""
    region: str = ""
    country: str = ""
    market_timezone: str = "UTC"
    market_open: str = ""
    market_close: str = ""
    aliases: tuple[str, ...] = ()
    home_group: str = ""
    default_watchlist: bool = False
    instrument_type: str = ""
    issuer: str = ""
    identifier: str = ""
    coupon: float | None = None
    maturity: date | None = None
    rating: str = ""
    seniority: str = ""
    source: str = ""
