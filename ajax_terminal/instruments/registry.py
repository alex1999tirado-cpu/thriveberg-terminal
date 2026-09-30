from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timezone
from difflib import SequenceMatcher
import re
import unicodedata
from zoneinfo import ZoneInfo

from ajax_terminal.models.instrument import AssetClass, Instrument


G10_CURRENCIES = ("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "NOK", "SEK")
INDEX_REGIONS = ("AMERICAS", "EUROPE", "ASIA-PACIFIC")
HOME_GROUPS = ("GLOBAL EQUITIES", "FX", "RATES", "CREDIT", "COMMODITIES")


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[A-Z0-9]+", ascii_text.upper()))


def _instrument_search_score(instrument: Instrument, needle: str) -> float:
    symbol = _search_text(instrument.symbol)
    name = _search_text(instrument.name)
    aliases = [_search_text(alias) for alias in instrument.aliases]
    compact_needle = needle.replace(" ", "")
    compact_symbol = symbol.replace(" ", "")
    compact_name = name.replace(" ", "")
    compact_aliases = [alias.replace(" ", "") for alias in aliases]
    tokens = needle.split()

    if compact_needle == compact_symbol or compact_needle in compact_aliases:
        return 1_000.0
    if compact_symbol.startswith(compact_needle) or any(alias.startswith(compact_needle) for alias in compact_aliases):
        return 920.0 - max(len(compact_symbol) - len(compact_needle), 0)
    if needle == name:
        return 900.0
    if all(token in f"{symbol} {name} {' '.join(aliases)}" for token in tokens):
        return 820.0 + min(len(compact_needle), 40)
    if compact_needle in compact_name:
        return 780.0 + min(len(compact_needle), 40)

    similarity = max(
        SequenceMatcher(None, compact_needle, candidate).ratio()
        for candidate in (compact_symbol, compact_name, *compact_aliases)
        if candidate
    )
    threshold = 0.66 if len(compact_needle) <= 3 else 0.62
    return similarity * 600.0 if similarity >= threshold else 0.0


class InstrumentRegistry:
    def __init__(self, instruments: list[Instrument]) -> None:
        self._instruments = tuple(instruments)
        self._by_symbol: dict[str, Instrument] = {}
        self._aliases: dict[str, str] = {}
        for instrument in self._instruments:
            symbol = self.normalize(instrument.symbol)
            if symbol in self._by_symbol:
                raise ValueError(f"Duplicate instrument symbol: {symbol}")
            self._by_symbol[symbol] = instrument
            for alias in instrument.aliases:
                normalized_alias = self.normalize(alias)
                if normalized_alias in self._aliases or normalized_alias in self._by_symbol:
                    raise ValueError(f"Duplicate instrument alias: {normalized_alias}")
                self._aliases[normalized_alias] = symbol

    @staticmethod
    def normalize(symbol: str) -> str:
        return symbol.strip().upper().replace("/", "").replace(":", "").replace(" ", "")

    def get(self, symbol: str) -> Instrument | None:
        clean = self.normalize(symbol)
        canonical = self._aliases.get(clean, clean)
        return self._by_symbol.get(canonical)

    def resolve(self, symbol: str) -> Instrument:
        clean = self.normalize(symbol)
        registered = self.get(clean)
        if registered is not None:
            return registered
        return Instrument(
            symbol=clean,
            name=clean,
            asset_class=AssetClass.EQUITY,
            provider_symbol=clean,
        )

    def provider_symbol(self, symbol: str) -> str:
        instrument = self.resolve(symbol)
        return instrument.provider_symbol or instrument.symbol

    def list(
        self,
        asset_class: AssetClass | str | None = None,
        *,
        region: str | None = None,
    ) -> list[Instrument]:
        selected_class = self.asset_class(asset_class) if isinstance(asset_class, str) else asset_class
        return [
            instrument
            for instrument in self._instruments
            if (selected_class is None or instrument.asset_class == selected_class)
            and (region is None or instrument.region == region.upper())
        ]

    def list_filter(self, value: str | None = None) -> list[Instrument] | None:
        """Resolve terminal registry filters without duplicating screen-level lists."""
        if value is None:
            return list(self._instruments)
        selected = value.strip().upper().replace("-", "")
        if selected in {"GOVT", "GOVTS", "GOVIE", "GOVIES", "SOVEREIGN"}:
            return self.government_benchmarks()
        if selected in {"CORP", "CORPORATE", "CREDIT"}:
            return self.credit_benchmarks() + self.corporate_bonds()
        if selected in {"BOND", "BONDS", "FI", "FIXEDINCOME"}:
            return self.government_benchmarks() + self.credit_benchmarks() + self.corporate_bonds()
        asset_class = self.asset_class(selected)
        return self.list(asset_class) if asset_class is not None else None

    def search(self, query: str, limit: int = 20) -> list[Instrument]:
        needle = _search_text(query)
        if not needle:
            return list(self._instruments[:limit])
        ranked = [
            (score, index, instrument)
            for index, instrument in enumerate(self._instruments)
            if (score := _instrument_search_score(instrument, needle)) > 0
        ]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [instrument for _score, _index, instrument in ranked[:limit]]

    def home_groups(self) -> OrderedDict[str, list[Instrument]]:
        groups: OrderedDict[str, list[Instrument]] = OrderedDict((name, []) for name in HOME_GROUPS)
        for instrument in self._instruments:
            if instrument.home_group:
                groups[instrument.home_group].append(instrument)
        return groups

    def default_watchlist(self) -> list[str]:
        return [instrument.symbol for instrument in self._instruments if instrument.default_watchlist]

    def fx_pairs(self) -> list[Instrument]:
        return self.list(AssetClass.FX)

    def government_benchmarks(self, country: str | None = None) -> list[Instrument]:
        selected_country = country.upper() if country else None
        return [
            instrument
            for instrument in self._instruments
            if instrument.instrument_type == "GOVT_BENCHMARK"
            and (selected_country is None or instrument.country == selected_country)
        ]

    def credit_benchmarks(self) -> list[Instrument]:
        return [
            instrument
            for instrument in self._instruments
            if instrument.instrument_type == "CREDIT_BENCHMARK"
        ]

    def corporate_bonds(self, issuer: str | None = None) -> list[Instrument]:
        needle = issuer.strip().upper() if issuer else ""
        return [
            instrument
            for instrument in self._instruments
            if instrument.instrument_type == "CORPORATE_BOND"
            and (
                not needle
                or needle in instrument.issuer.upper()
                or needle in instrument.symbol
                or any(needle in alias.upper() for alias in instrument.aliases)
            )
        ]

    def index_regions(self) -> OrderedDict[str, list[Instrument]]:
        return OrderedDict((region, self.list(AssetClass.INDEX, region=region)) for region in INDEX_REGIONS)

    def market_status(self, symbol: str, now: datetime | None = None) -> str:
        instrument = self.get(symbol)
        if instrument is None or not instrument.market_open or not instrument.market_close:
            return "24H" if instrument is not None and instrument.asset_class == AssetClass.FX else "N/A"
        current = now or datetime.now(timezone.utc)
        try:
            local = current.astimezone(ZoneInfo(instrument.market_timezone))
        except Exception:
            local = current
        if local.weekday() >= 5:
            return "CLOSED"
        opens = time.fromisoformat(instrument.market_open)
        closes = time.fromisoformat(instrument.market_close)
        if opens <= local.time() < closes:
            return "OPEN"
        if time(4, 0) <= local.time() < opens:
            return "PRE"
        if closes <= local.time() < time(20, 0):
            return "POST"
        return "CLOSED"

    @staticmethod
    def asset_class(value: str | AssetClass | None) -> AssetClass | None:
        if value is None or isinstance(value, AssetClass):
            return value
        aliases = {
            "FX": AssetClass.FX,
            "INDEX": AssetClass.INDEX,
            "INDICES": AssetClass.INDEX,
            "RATE": AssetClass.RATE,
            "RATES": AssetClass.RATE,
            "YIELD": AssetClass.RATE,
            "YIELDS": AssetClass.RATE,
            "BOND": AssetClass.BOND,
            "BONDS": AssetClass.BOND,
            "FI": AssetClass.BOND,
            "CORP": AssetClass.BOND,
            "CORPORATE": AssetClass.BOND,
            "CREDIT": AssetClass.BOND,
            "CMDTY": AssetClass.COMMODITY,
            "COMMODITY": AssetClass.COMMODITY,
            "COMMODITIES": AssetClass.COMMODITY,
        }
        return aliases.get(value.strip().upper())

    @property
    def g10_currencies(self) -> tuple[str, ...]:
        return G10_CURRENCIES


def _index(
    symbol: str,
    name: str,
    provider_symbol: str,
    region: str,
    country: str,
    currency: str,
    market_timezone: str,
    market_open: str,
    market_close: str,
    *,
    home: bool = False,
    watch: bool = False,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        asset_class=AssetClass.INDEX,
        currency=currency,
        provider_symbol=provider_symbol,
        region=region,
        country=country,
        market_timezone=market_timezone,
        market_open=market_open,
        market_close=market_close,
        home_group="GLOBAL EQUITIES" if home else "",
        default_watchlist=watch,
    )


def _fx(symbol: str, *, home: bool = False, watch: bool = False) -> Instrument:
    base, quote = symbol[:3], symbol[3:]
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote}",
        asset_class=AssetClass.FX,
        currency=quote,
        provider_symbol=f"{symbol}=X",
        region="G10",
        market_timezone="UTC",
        home_group="FX" if home else "",
        default_watchlist=watch,
    )


def _rate(
    symbol: str,
    name: str,
    provider_symbol: str,
    country: str,
    currency: str,
    *,
    home: bool = False,
    watch: bool = False,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        asset_class=AssetClass.RATE,
        currency=currency,
        provider_symbol=provider_symbol,
        region="SOVEREIGN",
        country=country,
        home_group="RATES" if home else "",
        default_watchlist=watch,
        instrument_type="GOVT_BENCHMARK",
    )


def _credit_benchmark(
    symbol: str,
    name: str,
    provider_symbol: str,
    rating: str,
    *,
    aliases: tuple[str, ...] = (),
    home: bool = False,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        asset_class=AssetClass.BOND,
        currency="USD",
        provider_symbol=provider_symbol,
        region="US CREDIT",
        country="US",
        aliases=aliases,
        instrument_type="CREDIT_BENCHMARK",
        issuer="ICE BofA",
        rating=rating,
        source="FRED / ICE Data Indices",
        home_group="CREDIT" if home else "",
    )


def _corporate_bond(
    symbol: str,
    issuer: str,
    coupon: float,
    maturity: date,
    currency: str,
    source: str,
    *,
    identifier: str = "",
    aliases: tuple[str, ...] = (),
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"{issuer} {coupon:.3f}% {maturity.year}",
        asset_class=AssetClass.BOND,
        currency=currency,
        region="CORPORATE",
        country="US",
        aliases=aliases,
        instrument_type="CORPORATE_BOND",
        issuer=issuer,
        identifier=identifier,
        coupon=coupon,
        maturity=maturity,
        seniority="Senior Unsecured",
        source=source,
    )


def _commodity(
    symbol: str,
    name: str,
    provider_symbol: str,
    sector: str,
    *,
    aliases: tuple[str, ...] = (),
    home: bool = False,
    watch: bool = False,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        asset_class=AssetClass.COMMODITY,
        currency="USD",
        provider_symbol=provider_symbol,
        region=sector,
        aliases=aliases,
        home_group="COMMODITIES" if home else "",
        default_watchlist=watch,
    )


_INDICES = [
    _index("SPX", "S&P 500", "^GSPC", "AMERICAS", "US", "USD", "America/New_York", "09:30", "16:00", home=True, watch=True),
    _index("NDX", "Nasdaq-100", "^NDX", "AMERICAS", "US", "USD", "America/New_York", "09:30", "16:00", home=True, watch=True),
    _index("DJI", "Dow Jones Industrial Average", "^DJI", "AMERICAS", "US", "USD", "America/New_York", "09:30", "16:00", home=True),
    _index("RUT", "Russell 2000", "^RUT", "AMERICAS", "US", "USD", "America/New_York", "09:30", "16:00"),
    _index("TSX", "S&P/TSX Composite", "^GSPTSE", "AMERICAS", "CA", "CAD", "America/Toronto", "09:30", "16:00"),
    _index("IBOV", "Bovespa", "^BVSP", "AMERICAS", "BR", "BRL", "America/Sao_Paulo", "10:00", "17:00"),
    _index("MEXBOL", "S&P/BMV IPC", "^MXX", "AMERICAS", "MX", "MXN", "America/Mexico_City", "08:30", "15:00"),
    _index("SX5E", "EURO STOXX 50", "^STOXX50E", "EUROPE", "EU", "EUR", "Europe/Berlin", "09:00", "17:30", home=True),
    _index("STOXX600", "STOXX Europe 600", "^STOXX", "EUROPE", "EU", "EUR", "Europe/Berlin", "09:00", "17:30"),
    _index("DAX", "DAX", "^GDAXI", "EUROPE", "DE", "EUR", "Europe/Berlin", "09:00", "17:30", home=True, watch=True),
    _index("CAC", "CAC 40", "^FCHI", "EUROPE", "FR", "EUR", "Europe/Paris", "09:00", "17:30", home=True),
    _index("FTSE", "FTSE 100", "^FTSE", "EUROPE", "GB", "GBP", "Europe/London", "08:00", "16:30", home=True),
    _index("IBEX", "IBEX 35", "^IBEX", "EUROPE", "ES", "EUR", "Europe/Madrid", "09:00", "17:30"),
    _index("FTSEMIB", "FTSE MIB", "FTSEMIB.MI", "EUROPE", "IT", "EUR", "Europe/Rome", "09:00", "17:30"),
    _index("SMI", "Swiss Market Index", "^SSMI", "EUROPE", "CH", "CHF", "Europe/Zurich", "09:00", "17:30"),
    _index("AEX", "AEX", "^AEX", "EUROPE", "NL", "EUR", "Europe/Amsterdam", "09:00", "17:30"),
    _index("OMXS30", "OMX Stockholm 30", "^OMX", "EUROPE", "SE", "SEK", "Europe/Stockholm", "09:00", "17:30"),
    _index("NIKKEI", "Nikkei 225", "^N225", "ASIA-PACIFIC", "JP", "JPY", "Asia/Tokyo", "09:00", "15:30", home=True),
    _index("TOPIX", "TOPIX", "^TOPX", "ASIA-PACIFIC", "JP", "JPY", "Asia/Tokyo", "09:00", "15:30"),
    _index("HSI", "Hang Seng", "^HSI", "ASIA-PACIFIC", "HK", "HKD", "Asia/Hong_Kong", "09:30", "16:00"),
    _index("CSI300", "CSI 300", "000300.SS", "ASIA-PACIFIC", "CN", "CNY", "Asia/Shanghai", "09:30", "15:00"),
    _index("SHCOMP", "Shanghai Composite", "000001.SS", "ASIA-PACIFIC", "CN", "CNY", "Asia/Shanghai", "09:30", "15:00"),
    _index("KOSPI", "KOSPI", "^KS11", "ASIA-PACIFIC", "KR", "KRW", "Asia/Seoul", "09:00", "15:30"),
    _index("ASX200", "S&P/ASX 200", "^AXJO", "ASIA-PACIFIC", "AU", "AUD", "Australia/Sydney", "10:00", "16:00"),
    _index("NIFTY", "NIFTY 50", "^NSEI", "ASIA-PACIFIC", "IN", "INR", "Asia/Kolkata", "09:15", "15:30"),
    _index("TAIEX", "Taiwan Weighted", "^TWII", "ASIA-PACIFIC", "TW", "TWD", "Asia/Taipei", "09:00", "13:30"),
    _index("STI", "Straits Times", "^STI", "ASIA-PACIFIC", "SG", "SGD", "Asia/Singapore", "09:00", "17:00"),
]

_FX_SYMBOLS = (
    "EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "USDNOK", "USDSEK",
    "EURJPY", "EURGBP", "EURCHF", "EURCAD", "EURAUD", "EURNZD", "EURNOK", "EURSEK",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD", "GBPNOK", "GBPSEK",
    "CHFJPY", "CADJPY", "AUDJPY", "NZDJPY", "NOKJPY", "SEKJPY",
    "CADCHF", "AUDCHF", "NZDCHF", "CHFNOK", "CHFSEK",
    "AUDCAD", "NZDCAD", "CADNOK", "CADSEK",
    "AUDNZD", "AUDNOK", "AUDSEK", "NZDNOK", "NZDSEK", "NOKSEK",
)
_HOME_FX = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD"}
_WATCH_FX = {"EURUSD", "GBPUSD", "USDJPY"}
_FX = [_fx(symbol, home=symbol in _HOME_FX, watch=symbol in _WATCH_FX) for symbol in _FX_SYMBOLS]

_RATES = [
    _rate("US2Y", "US Treasury 2Y Yield", "^UST2Y", "US", "USD", home=True),
    _rate("US5Y", "US Treasury 5Y Yield", "^FVX", "US", "USD"),
    _rate("US10Y", "US Treasury 10Y Yield", "^TNX", "US", "USD", home=True, watch=True),
    _rate("US30Y", "US Treasury 30Y Yield", "^TYX", "US", "USD", home=True),
    _rate("DE2Y", "Germany 2Y Yield", "^DE2Y", "DE", "EUR", home=True),
    _rate("DE5Y", "Germany 5Y Yield", "^DE5Y", "DE", "EUR"),
    _rate("DE10Y", "Germany 10Y Yield", "^DE10Y", "DE", "EUR", home=True, watch=True),
    _rate("DE30Y", "Germany 30Y Yield", "^DE30Y", "DE", "EUR"),
    _rate("GB2Y", "UK Gilt 2Y Yield", "^GB2Y", "GB", "GBP"),
    _rate("GB5Y", "UK Gilt 5Y Yield", "^GB5Y", "GB", "GBP"),
    _rate("GB10Y", "UK Gilt 10Y Yield", "^GB10Y", "GB", "GBP"),
    _rate("GB30Y", "UK Gilt 30Y Yield", "^GB30Y", "GB", "GBP"),
    _rate("JP2Y", "Japan Government 2Y Yield", "^JP2Y", "JP", "JPY"),
    _rate("JP5Y", "Japan Government 5Y Yield", "^JP5Y", "JP", "JPY"),
    _rate("JP10Y", "Japan Government 10Y Yield", "^JP10Y", "JP", "JPY"),
    _rate("JP30Y", "Japan Government 30Y Yield", "^JP30Y", "JP", "JPY"),
    _rate("FR2Y", "France OAT 2Y Yield", "^FR2Y", "FR", "EUR"),
    _rate("FR5Y", "France OAT 5Y Yield", "^FR5Y", "FR", "EUR"),
    _rate("FR10Y", "France OAT 10Y Yield", "^FR10Y", "FR", "EUR"),
    _rate("FR30Y", "France OAT 30Y Yield", "^FR30Y", "FR", "EUR"),
    _rate("IT2Y", "Italy BTP 2Y Yield", "^IT2Y", "IT", "EUR"),
    _rate("IT5Y", "Italy BTP 5Y Yield", "^IT5Y", "IT", "EUR"),
    _rate("IT10Y", "Italy BTP 10Y Yield", "^IT10Y", "IT", "EUR"),
    _rate("IT30Y", "Italy BTP 30Y Yield", "^IT30Y", "IT", "EUR"),
    _rate("ES2Y", "Spain Bono 1-2Y Yield", "^ES2Y", "ES", "EUR"),
    _rate("ES5Y", "Spain Bono 5Y Yield", "^ES5Y", "ES", "EUR"),
    _rate("ES10Y", "Spain Bono 10Y Yield", "^ES10Y", "ES", "EUR"),
    _rate("ES15Y", "Spain Bono 15Y Yield", "^ES15Y", "ES", "EUR"),
    _rate("ES30Y", "Spain Bono 30Y Yield", "^ES30Y", "ES", "EUR"),
]

_CREDIT_BENCHMARKS = [
    _credit_benchmark("USCORPIG", "ICE BofA US Corporate IG", "BAMLC0A0CMEY", "IG", aliases=("CORPIG", "USIG"), home=True),
    _credit_benchmark("USCORPHY", "ICE BofA US High Yield", "BAMLH0A0HYM2EY", "HY", aliases=("CORPHY", "USHY"), home=True),
    _credit_benchmark("USCORPAAA", "ICE BofA AAA US Corporate", "BAMLC0A1CAAAEY", "AAA"),
    _credit_benchmark("USCORPAA", "ICE BofA AA US Corporate", "BAMLC0A2CAAEY", "AA"),
    _credit_benchmark("USCORPA", "ICE BofA Single-A US Corporate", "BAMLC0A3CAEY", "A"),
    _credit_benchmark("USCORPBBB", "ICE BofA BBB US Corporate", "BAMLC0A4CBBBEY", "BBB"),
]

_CORPORATE_BONDS = [
    _corporate_bond(
        "AAPL44",
        "Apple Inc.",
        4.450,
        date(2044, 5, 6),
        "USD",
        "SEC EDGAR 2014-04-29 pricing term sheet",
        identifier="US037833AT77",
        aliases=("AAPL4.45", "037833AT7"),
    ),
    _corporate_bond(
        "MSFT36",
        "Microsoft Corporation",
        3.450,
        date(2036, 8, 8),
        "USD",
        "SEC EDGAR 2016-08-01 pricing term sheet",
        aliases=("MSFT3.45",),
    ),
    _corporate_bond(
        "AMZN31",
        "Amazon.com, Inc.",
        2.100,
        date(2031, 5, 12),
        "USD",
        "SEC EDGAR 2021-05-12 prospectus supplement",
        aliases=("AMZN2.10",),
    ),
    _corporate_bond(
        "GOOGL35",
        "Alphabet Inc.",
        4.500,
        date(2035, 5, 15),
        "USD",
        "SEC EDGAR 2025-04-28 pricing term sheet",
        aliases=("GOOGL4.50",),
    ),
    _corporate_bond(
        "GOOGL34E",
        "Alphabet Inc.",
        3.625,
        date(2034, 5, 11),
        "EUR",
        "SEC EDGAR 2026-05-05 pricing term sheet",
        aliases=("GOOGL3.625EUR",),
    ),
    _corporate_bond(
        "META32",
        "Meta Platforms, Inc.",
        3.850,
        date(2032, 8, 15),
        "USD",
        "SEC EDGAR 2022-08-09 supplemental indenture",
        aliases=("META3.85",),
    ),
    _corporate_bond(
        "NVDA31",
        "NVIDIA Corporation",
        4.500,
        date(2031, 6, 15),
        "USD",
        "SEC EDGAR 2026-06-15 pricing term sheet",
        aliases=("NVDA4.50",),
    ),
    _corporate_bond(
        "KO30",
        "The Coca-Cola Company",
        3.450,
        date(2030, 3, 25),
        "USD",
        "SEC EDGAR 2020-03-20 pricing term sheet",
        aliases=("KO3.45",),
    ),
]

_COMMODITIES = [
    _commodity("BRENT", "Brent Crude Oil", "BZ=F", "ENERGY", home=True, watch=True),
    _commodity("WTI", "WTI Crude Oil", "CL=F", "ENERGY", home=True),
    _commodity("NATGAS", "Natural Gas", "NG=F", "ENERGY"),
    _commodity("GASOLINE", "RBOB Gasoline", "RB=F", "ENERGY"),
    _commodity("HEATOIL", "Heating Oil", "HO=F", "ENERGY"),
    _commodity("XAUUSD", "Gold", "GC=F", "METALS", aliases=("GOLD",), home=True, watch=True),
    _commodity("SILVER", "Silver", "SI=F", "METALS", home=True),
    _commodity("COPPER", "Copper", "HG=F", "METALS", home=True),
    _commodity("PLATINUM", "Platinum", "PL=F", "METALS"),
    _commodity("PALLADIUM", "Palladium", "PA=F", "METALS"),
    _commodity("CORN", "Corn", "ZC=F", "AGRICULTURE"),
    _commodity("WHEAT", "Wheat", "ZW=F", "AGRICULTURE"),
    _commodity("SOYBEANS", "Soybeans", "ZS=F", "AGRICULTURE"),
    _commodity("COFFEE", "Coffee", "KC=F", "AGRICULTURE"),
    _commodity("SUGAR", "Sugar", "SB=F", "AGRICULTURE"),
    _commodity("COTTON", "Cotton", "CT=F", "AGRICULTURE"),
    _commodity("COCOA", "Cocoa", "CC=F", "AGRICULTURE"),
]


INSTRUMENT_REGISTRY = InstrumentRegistry(
    _INDICES + _FX + _RATES + _CREDIT_BENCHMARKS + _CORPORATE_BONDS + _COMMODITIES
)
