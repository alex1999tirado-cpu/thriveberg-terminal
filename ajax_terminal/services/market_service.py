from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

from ajax_terminal.analytics.fixed_income import bootstrap_zero_rates
from ajax_terminal.instruments import INSTRUMENT_REGISTRY, InstrumentRegistry
from ajax_terminal.models.fixed_income import CreditBenchmark
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import (
    Curve,
    CurvePoint,
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    MarketSnapshot,
    PriceBar,
    PriceHistory,
    Quote,
    StatementType,
)
from ajax_terminal.providers.ecb import ECBProvider
from ajax_terminal.providers.esef_statements import ESEFFinancialStatementsProvider
from ajax_terminal.providers.banco_de_espana import BancoDeEspanaProvider
from ajax_terminal.providers.fred_credit import FredCreditProvider
from ajax_terminal.providers.fred_yields import FredSovereignYieldProvider
from ajax_terminal.providers.finnhub import FinnhubProvider
from ajax_terminal.providers.japan_mof import JapanMofCurveProvider
from ajax_terminal.providers.mock import MockMarketProvider
from ajax_terminal.providers.sec import SECFilingsProvider
from ajax_terminal.providers.treasury import TreasuryProvider
from ajax_terminal.providers.yahoo import YahooProvider
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period

LOGGER = logging.getLogger(__name__)


class MarketService:
    QUOTE_TTL = 30
    CURVE_TTL = 3600
    FUNDAMENTALS_TTL = 24 * 3600
    STATEMENTS_TTL = 24 * 3600
    HISTORY_TTL = 15 * 60

    def __init__(
        self,
        cache: SQLiteCache | None = None,
        watchlists: WatchlistStore | None = None,
        registry: InstrumentRegistry = INSTRUMENT_REGISTRY,
        market_providers: list[Any] | None = None,
        mock_provider: MockMarketProvider | None = None,
        enable_mock_data: bool = False,
    ) -> None:
        self.cache = cache or SQLiteCache()
        self.watchlists = watchlists or WatchlistStore()
        self.registry = registry
        if market_providers is None:
            finnhub = FinnhubProvider()
            live_providers = [finnhub] if finnhub.configured else []
            self.market_providers = [
                BancoDeEspanaProvider(),
                FredSovereignYieldProvider(),
                FredCreditProvider(),
                *live_providers,
                YahooProvider(),
            ]
            self.statement_providers = [
                SECFilingsProvider(),
                ESEFFinancialStatementsProvider(),
                *self.market_providers,
            ]
        else:
            self.market_providers = market_providers
            self.statement_providers = self.market_providers
        self.credit_provider = next(
            (provider for provider in self.market_providers if isinstance(provider, FredCreditProvider)),
            None,
        )
        self.mock_provider = mock_provider
        self.enable_mock_data = enable_mock_data or mock_provider is not None
        self.curve_providers = (
            {
                "USD": [TreasuryProvider()],
                "EUR": [ECBProvider()],
                "JPY": [JapanMofCurveProvider()],
            }
            if market_providers is None
            else {}
        )

    async def quote(self, symbol: str, *, allow_mock: bool = False) -> Quote:
        clean = self.registry.resolve(symbol).symbol
        key = f"quote:{clean}"
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            cached_quote = _quote_from_dict(cached, cached_quality=False)
            if cached_quote.quality != DataQuality.MOCK:
                return self._enrich_quote(cached_quote, clean)
        for provider in self.market_providers:
            try:
                quote = await provider.quote(clean)
                self.cache.set_json(key, _quote_to_dict(quote), self.QUOTE_TTL)
                LOGGER.info("quote provider=%s symbol=%s quality=%s", quote.provider, clean, quote.quality)
                return self._enrich_quote(quote, clean)
            except Exception as exc:
                LOGGER.warning("quote fallback provider=%s symbol=%s error=%s", getattr(provider, "name", "?"), clean, exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            stale_quote = _quote_from_dict(stale, cached_quality=True)
            if stale_quote.quality != DataQuality.MOCK:
                return self._enrich_quote(stale_quote, clean)
        if allow_mock and self.enable_mock_data and self.mock_provider is not None:
            quote = await self.mock_provider.quote(clean)
            self.cache.set_json(key, _quote_to_dict(quote), self.QUOTE_TTL)
            return self._enrich_quote(quote, clean)
        return self._unavailable_quote(clean)

    async def bulk_quotes(self, symbols: list[str], *, allow_mock: bool = False) -> list[Quote]:
        return list(await asyncio.gather(*(self.quote(symbol, allow_mock=allow_mock) for symbol in symbols)))

    async def watchlist_quotes(self, name: str = "DEFAULT") -> list[Quote]:
        return await self.bulk_quotes(self.watchlists.symbols(name))

    async def curve(self, currency: str, *, allow_mock: bool = False) -> Curve:
        ccy = currency.upper()
        key = f"curve:v2:{ccy}"
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            cached_curve = _curve_from_dict(cached, cached_quality=False)
            if cached_curve.quality != DataQuality.MOCK:
                return cached_curve
        providers = self.curve_providers.get(ccy, [])
        for provider in providers:
            try:
                curve = await provider.curve(ccy)
                if curve.quality == DataQuality.MOCK and not allow_mock:
                    continue
                self.cache.set_json(key, _curve_to_dict(curve), self.CURVE_TTL)
                return curve
            except Exception as exc:
                LOGGER.warning("curve fallback provider=%s currency=%s error=%s", getattr(provider, "name", "?"), ccy, exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            stale_curve = _curve_from_dict(stale, cached_quality=True)
            if stale_curve.quality != DataQuality.MOCK:
                return stale_curve
        bootstrapped = await self._bootstrap_benchmark_curve(ccy)
        if bootstrapped is not None:
            self.cache.set_json(key, _curve_to_dict(bootstrapped), self.CURVE_TTL)
            return bootstrapped
        return Curve(
            currency=ccy,
            name=f"{ccy} REFERENCE CURVE",
            points=[],
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )

    async def _bootstrap_benchmark_curve(self, currency: str) -> Curve | None:
        prefixes = {"USD": "US", "EUR": "DE", "GBP": "GB", "JPY": "JP"}
        prefix = prefixes.get(currency)
        if prefix is None:
            return None
        symbols = [f"{prefix}{tenor}" for tenor in ("2Y", "5Y", "10Y", "30Y")]
        quotes = await self.bulk_quotes(symbols, allow_mock=False)
        observed: dict[float, float] = {}
        previous: dict[float, float] = {}
        sources: list[str] = []
        timestamps: list[datetime] = []
        observed_symbols: list[str] = []
        qualities: list[DataQuality] = []
        for symbol, quote in zip(symbols, quotes):
            if quote.price is None or quote.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
                continue
            years = float(symbol.removeprefix(prefix).removesuffix("Y"))
            observed[years] = quote.price
            previous_value = quote.previous_close
            if previous_value is None and quote.change is not None:
                previous_value = quote.price - quote.change
            if previous_value is not None:
                previous[years] = previous_value
            if quote.provider not in sources:
                sources.append(quote.provider)
            timestamps.append(quote.timestamp)
            observed_symbols.append(symbol)
            qualities.append(quote.quality)
        if not observed:
            return None

        if len(observed) == 1:
            years, value = next(iter(observed.items()))
            symbol = observed_symbols[0]
            previous_value = previous.get(years)
            return Curve(
                currency=currency,
                name=f"{currency} PARTIAL REFERENCE CURVE",
                points=[
                    CurvePoint(
                        tenor=f"{int(years)}Y",
                        years=years,
                        yield_pct=value,
                        change_bp=(value - previous_value) * 100.0 if previous_value is not None else None,
                    )
                ],
                provider=" + ".join(sources),
                quality=DataQuality.CACHED if DataQuality.CACHED in qualities else DataQuality.DELAYED,
                timestamp=max(timestamps),
                method=f"PARTIAL / SINGLE OBSERVED BENCHMARK {symbol} / NO EXTRAPOLATION",
            )

        all_tenor_years = {
            "1M": 1 / 12,
            "3M": 3 / 12,
            "6M": 6 / 12,
            "1Y": 1.0,
            "2Y": 2.0,
            "3Y": 3.0,
            "5Y": 5.0,
            "7Y": 7.0,
            "10Y": 10.0,
            "20Y": 20.0,
            "30Y": 30.0,
        }
        minimum_years = min(observed)
        maximum_years = max(observed)
        tenor_years = {
            tenor: years
            for tenor, years in all_tenor_years.items()
            if minimum_years <= years <= maximum_years
        }
        current_zero = bootstrap_zero_rates(observed, list(tenor_years.values()))
        previous_zero = bootstrap_zero_rates(previous, list(tenor_years.values())) if previous else {}
        points = [
            CurvePoint(
                tenor=tenor,
                years=years,
                yield_pct=current_zero[years],
                change_bp=(current_zero[years] - previous_zero[years]) * 100.0
                if years in previous_zero
                else None,
            )
            for tenor, years in tenor_years.items()
        ]
        method = f"BOOTSTRAP / LINEAR INTERPOLATION FROM {', '.join(observed_symbols)} / NO EXTRAPOLATION"
        quality = DataQuality.CACHED if DataQuality.CACHED in qualities else DataQuality.DELAYED
        return Curve(
            currency=currency,
            name=f"{currency} ESTIMATED ZERO CURVE",
            points=points,
            provider=" + ".join(sources),
            quality=quality,
            timestamp=max(timestamps),
            method=method,
        )

    async def equity_fundamentals(self, symbol: str) -> EquityFundamentals:
        clean = self.registry.resolve(symbol).symbol
        key = f"fundamentals:{clean}"
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            cached_fundamentals = _fundamentals_from_dict(cached, cached_quality=False)
            if cached_fundamentals.quality != DataQuality.MOCK:
                return cached_fundamentals
        for provider in self.market_providers:
            if not hasattr(provider, "fundamentals"):
                continue
            try:
                fundamentals = await provider.fundamentals(clean)
                self.cache.set_json(key, _fundamentals_to_dict(fundamentals), self.FUNDAMENTALS_TTL)
                return fundamentals
            except Exception as exc:
                LOGGER.warning("fundamentals fallback provider=%s symbol=%s error=%s", getattr(provider, "name", "?"), clean, exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            stale_fundamentals = _fundamentals_from_dict(stale, cached_quality=True)
            if stale_fundamentals.quality != DataQuality.MOCK:
                return stale_fundamentals
        instrument = self.registry.resolve(clean)
        return EquityFundamentals(
            symbol=clean,
            name=instrument.name,
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )

    async def history(
        self,
        symbol: str,
        period: str = "1Y",
        interval: str | None = None,
        *,
        allow_mock: bool = False,
        refresh: bool = False,
    ) -> PriceHistory:
        clean = self.registry.resolve(symbol).symbol
        normalized_period = normalize_history_period(period)
        selected_interval = normalize_history_interval(normalized_period, interval)
        key = f"history:{clean}:{normalized_period}:{selected_interval}"
        if not refresh:
            cached = self.cache.get_json(key)
            if isinstance(cached, dict):
                cached_history = _history_from_dict(cached, cached_quality=False)
                if cached_history.quality != DataQuality.MOCK:
                    return cached_history
        for provider in self.market_providers:
            if not hasattr(provider, "historical"):
                continue
            try:
                history = await provider.historical(clean, normalized_period, selected_interval)
                self.cache.set_json(key, _history_to_dict(history), self.HISTORY_TTL)
                LOGGER.info(
                    "history provider=%s symbol=%s period=%s bars=%s quality=%s",
                    history.provider,
                    clean,
                    normalized_period,
                    len(history.bars),
                    history.quality,
                )
                return history
            except Exception as exc:
                LOGGER.warning(
                    "history fallback provider=%s symbol=%s period=%s error=%s",
                    getattr(provider, "name", "?"),
                    clean,
                    normalized_period,
                    exc,
                )
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            stale_history = _history_from_dict(stale, cached_quality=True)
            if stale_history.quality != DataQuality.MOCK:
                return stale_history
        if allow_mock and self.enable_mock_data and self.mock_provider is not None:
            history = await self.mock_provider.historical(clean, normalized_period, selected_interval)
            self.cache.set_json(key, _history_to_dict(history), self.HISTORY_TTL)
            return history
        return PriceHistory(
            symbol=clean,
            period=normalized_period,
            interval=selected_interval,
            bars=[],
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )

    async def credit_benchmark(self, symbol: str) -> CreditBenchmark:
        clean = self.registry.resolve(symbol).symbol
        instrument = self.registry.get(clean)
        if instrument is None or instrument.instrument_type != "CREDIT_BENCHMARK" or self.credit_provider is None:
            return CreditBenchmark(
                symbol=clean,
                name=instrument.name if instrument else clean,
                rating=instrument.rating if instrument else "",
            )
        try:
            return await self.credit_provider.benchmark(clean)
        except Exception as exc:
            LOGGER.warning("credit benchmark provider=%s symbol=%s error=%s", self.credit_provider.name, clean, exc)
            return CreditBenchmark(symbol=clean, name=instrument.name, rating=instrument.rating)

    async def credit_benchmarks(self, symbols: list[str] | None = None) -> list[CreditBenchmark]:
        selected = symbols or [instrument.symbol for instrument in self.registry.credit_benchmarks()]
        return list(await asyncio.gather(*(self.credit_benchmark(symbol) for symbol in selected)))

    async def government_quotes(self, symbols: list[str]) -> list[Quote]:
        instruments = [self.registry.get(symbol) for symbol in symbols]
        usd_symbols = [
            instrument.symbol
            for instrument in instruments
            if instrument is not None and instrument.country == "US"
        ]
        treasury_quotes: dict[str, Quote] = {}
        if usd_symbols:
            try:
                curve = await self.curve("USD", allow_mock=False)
                if curve.quality != DataQuality.MOCK:
                    by_tenor = {point.tenor: point for point in curve.points}
                    for symbol in usd_symbols:
                        point = by_tenor.get(symbol.removeprefix("US"))
                        instrument = self.registry.get(symbol)
                        if point is None or instrument is None:
                            continue
                        change = point.change_bp / 100.0 if point.change_bp is not None else None
                        previous = point.yield_pct - change if change is not None else None
                        treasury_quotes[symbol] = Quote(
                            symbol=symbol,
                            name=instrument.name,
                            price=point.yield_pct,
                            change=change,
                            change_percent=change / previous * 100.0 if change is not None and previous else None,
                            currency="%",
                            asset_class="RATE",
                            previous_close=previous,
                            provider=curve.provider,
                            quality=curve.quality,
                            timestamp=curve.timestamp,
                        )
            except Exception as exc:
                LOGGER.warning("government curve fallback country=US error=%s", exc)
        remaining = [symbol for symbol in symbols if symbol not in treasury_quotes]
        fallback_quotes = await self.bulk_quotes(remaining, allow_mock=False)
        by_symbol = {quote.symbol: quote for quote in fallback_quotes}
        by_symbol.update(treasury_quotes)
        if "ES30Y" in symbols and by_symbol.get("ES30Y", self._unavailable_quote("ES30Y")).price is None:
            estimated = await self._estimate_spain_30y(by_symbol)
            if estimated is not None:
                by_symbol["ES30Y"] = estimated
        return [by_symbol.get(symbol, self._unavailable_quote(symbol)) for symbol in symbols]

    async def _estimate_spain_30y(self, known: dict[str, Quote]) -> Quote | None:
        ten_year = known.get("ES10Y")
        if ten_year is None or ten_year.price is None:
            ten_year = await self.quote("ES10Y", allow_mock=False)
        if ten_year.price is None or ten_year.quality == DataQuality.UNAVAILABLE:
            return None
        eur_curve = await self.curve("EUR", allow_mock=False)
        eur_10y = eur_curve.point("10Y")
        eur_30y = eur_curve.point("30Y")
        if eur_10y is None or eur_30y is None or eur_curve.quality == DataQuality.UNAVAILABLE:
            return None
        price = ten_year.price + (eur_30y.yield_pct - eur_10y.yield_pct)
        curve_change = None
        if eur_10y.change_bp is not None and eur_30y.change_bp is not None:
            curve_change = (eur_30y.change_bp - eur_10y.change_bp) / 100.0
        change = ten_year.change + curve_change if ten_year.change is not None and curve_change is not None else None
        previous = price - change if change is not None else None
        return Quote(
            symbol="ES30Y",
            name=self.registry.resolve("ES30Y").name,
            price=price,
            change=change,
            change_percent=change / previous * 100.0 if change is not None and previous else None,
            currency="%",
            asset_class="RATE",
            previous_close=previous,
            provider=f"{ten_year.provider} + {eur_curve.provider}",
            quality=DataQuality.CACHED if DataQuality.CACHED in {ten_year.quality, eur_curve.quality} else DataQuality.DELAYED,
            timestamp=min(ten_year.timestamp, eur_curve.timestamp),
            estimated=True,
            methodology=(
                "ESTIMATE: Spain 10Y official benchmark yield plus the ECB EUR AAA 30Y-minus-10Y "
                "zero-curve slope. Assumes the Spanish sovereign spread is constant beyond 10Y."
            ),
        )

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
        *,
        refresh: bool = False,
    ) -> FinancialStatements:
        clean = self.registry.resolve(symbol).symbol
        key = f"statements:v9:{clean}:{statement_type}"
        best_partial: FinancialStatements | None = None
        if not refresh:
            cached = self.cache.get_json(key)
            if isinstance(cached, dict):
                cached_statements = _statements_from_dict(cached, cached_quality=False)
                if cached_statements.quality != DataQuality.MOCK:
                    if _statement_has_professional_coverage(cached_statements):
                        return cached_statements
                    best_partial = cached_statements
                    LOGGER.warning(
                        "statements cache rejected for sparse coverage symbol=%s type=%s lines=%s",
                        clean,
                        statement_type,
                        _statement_line_count(cached_statements),
                    )
        for provider in self.statement_providers:
            if not hasattr(provider, "financial_statements"):
                continue
            try:
                statements = await provider.financial_statements(clean, statement_type)
                if _statement_score(statements) > _statement_score(best_partial):
                    best_partial = statements
                if _statement_has_professional_coverage(statements):
                    self.cache.set_json(key, _statements_to_dict(statements), self.STATEMENTS_TTL)
                    return statements
                LOGGER.warning(
                    "statements provider returned sparse coverage provider=%s symbol=%s type=%s lines=%s",
                    getattr(provider, "name", "?"),
                    clean,
                    statement_type,
                    _statement_line_count(statements),
                )
            except Exception as exc:
                LOGGER.warning(
                    "statements fallback provider=%s symbol=%s type=%s error=%s",
                    getattr(provider, "name", "?"),
                    clean,
                    statement_type,
                    exc,
                )
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            stale_statements = _statements_from_dict(stale, cached_quality=True)
            if stale_statements.quality != DataQuality.MOCK:
                if _statement_has_professional_coverage(stale_statements):
                    return stale_statements
                if _statement_score(stale_statements) > _statement_score(best_partial):
                    best_partial = stale_statements
        if best_partial is not None and best_partial.quality != DataQuality.MOCK:
            self.cache.set_json(key, _statements_to_dict(best_partial), self.STATEMENTS_TTL)
            return best_partial
        instrument = self.registry.resolve(clean)
        return FinancialStatements(
            symbol=clean,
            name=instrument.name,
            statement_type=statement_type,
            annual=[],
            quarterly=[],
            currency=instrument.currency,
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )

    async def market_snapshots(self, symbols: list[str]) -> list[MarketSnapshot]:
        return list(await asyncio.gather(*(self._market_snapshot(symbol) for symbol in symbols)))

    async def _market_snapshot(self, symbol: str) -> MarketSnapshot:
        quote, history = await asyncio.gather(self.quote(symbol), self.history(symbol, "YTD"))
        ytd_change: float | None = None
        if len(history.bars) >= 2 and history.bars[0].close:
            ytd_change = (history.bars[-1].close / history.bars[0].close - 1.0) * 100.0
        status = quote.market_status or self.registry.market_status(symbol)
        return MarketSnapshot(quote=quote, ytd_change_percent=ytd_change, market_status=status)

    async def search(self, query: str) -> list[tuple[str, str, str]]:
        q = query.upper().strip()
        results = [
            (instrument.symbol, instrument.name, str(instrument.asset_class))
            for instrument in self.registry.search(q, limit=20)
        ]
        for provider in self.market_providers:
            if not hasattr(provider, "search") or not q:
                continue
            try:
                results.extend(await provider.search(q, limit=10))
                break
            except Exception as exc:
                LOGGER.warning("search provider=%s query=%s error=%s", getattr(provider, "name", "?"), q, exc)
        deduplicated: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for item in results:
            if item[0] in seen:
                continue
            seen.add(item[0])
            deduplicated.append(item)
        return deduplicated[:20]

    def _enrich_quote(self, quote: Quote, symbol: str) -> Quote:
        instrument = self.registry.resolve(symbol)
        quote.symbol = instrument.symbol
        if self.registry.get(symbol) is not None:
            quote.name = instrument.name
            if instrument.instrument_type in {"CREDIT_BENCHMARK", "GOVT_BENCHMARK"}:
                quote.currency = "%"
            else:
                quote.currency = instrument.currency or quote.currency
        quote.asset_class = "RATE" if instrument.instrument_type in {"CREDIT_BENCHMARK", "GOVT_BENCHMARK"} else str(instrument.asset_class)
        quote.market_status = quote.market_status or self.registry.market_status(symbol)
        return quote

    def _unavailable_quote(self, symbol: str) -> Quote:
        instrument = self.registry.resolve(symbol)
        return Quote(
            symbol=instrument.symbol,
            name=instrument.name,
            price=None,
            currency="%" if instrument.asset_class == AssetClass.RATE else instrument.currency,
            asset_class="RATE" if instrument.asset_class == AssetClass.RATE else str(instrument.asset_class),
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )


def _quote_to_dict(quote: Quote) -> dict[str, Any]:
    data = asdict(quote)
    data["quality"] = str(quote.quality)
    data["timestamp"] = quote.timestamp.isoformat()
    return data


def _quote_from_dict(data: dict[str, Any], cached_quality: bool) -> Quote:
    copy = dict(data)
    copy["quality"] = _cached_quality(copy.get("quality"), cached_quality)
    copy["timestamp"] = _parse_datetime(copy.get("timestamp"))
    return Quote(**copy)


def _curve_to_dict(curve: Curve) -> dict[str, Any]:
    data = asdict(curve)
    data["quality"] = str(curve.quality)
    data["timestamp"] = curve.timestamp.isoformat()
    return data


def _curve_from_dict(data: dict[str, Any], cached_quality: bool) -> Curve:
    copy = dict(data)
    copy["quality"] = _cached_quality(copy.get("quality"), cached_quality)
    copy["timestamp"] = _parse_datetime(copy.get("timestamp"))
    copy["points"] = [CurvePoint(**point) for point in copy.get("points", [])]
    return Curve(**copy)


def _fundamentals_to_dict(fundamentals: EquityFundamentals) -> dict[str, Any]:
    data = asdict(fundamentals)
    data["quality"] = str(fundamentals.quality)
    data["timestamp"] = fundamentals.timestamp.isoformat()
    return data


def _fundamentals_from_dict(data: dict[str, Any], cached_quality: bool) -> EquityFundamentals:
    copy = dict(data)
    copy["quality"] = _cached_quality(copy.get("quality"), cached_quality)
    copy["timestamp"] = _parse_datetime(copy.get("timestamp"))
    non_numeric = {"symbol", "name", "provider", "quality", "timestamp"}
    for key, value in copy.items():
        if key not in non_numeric and (isinstance(value, bool) or not isinstance(value, (int, float))):
            copy[key] = None
    return EquityFundamentals(**copy)


def _history_to_dict(history: PriceHistory) -> dict[str, Any]:
    return {
        "symbol": history.symbol,
        "period": history.period,
        "interval": history.interval,
        "bars": [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in history.bars
        ],
        "currency": history.currency,
        "provider": history.provider,
        "quality": str(history.quality),
        "timestamp": history.timestamp.isoformat(),
    }


def _history_from_dict(data: dict[str, Any], cached_quality: bool) -> PriceHistory:
    bars = [
        PriceBar(
            timestamp=_parse_datetime(bar.get("timestamp")),
            open=float(bar["open"]),
            high=float(bar["high"]),
            low=float(bar["low"]),
            close=float(bar["close"]),
            volume=float(bar["volume"]) if bar.get("volume") is not None else None,
        )
        for bar in data.get("bars", [])
    ]
    quality = _cached_quality(data.get("quality"), cached_quality)
    return PriceHistory(
        symbol=data.get("symbol", ""),
        period=data.get("period", "1Y"),
        interval=data.get("interval", "1d"),
        bars=bars,
        currency=data.get("currency", ""),
        provider=data.get("provider", "UNKNOWN"),
        quality=quality,
        timestamp=_parse_datetime(data.get("timestamp")),
    )


_MINIMUM_STATEMENT_LINES = {
    StatementType.INCOME: 10,
    StatementType.BALANCE_SHEET: 18,
    StatementType.CASH_FLOW: 14,
}


def _statement_line_count(statements: FinancialStatements | None) -> int:
    if statements is None:
        return 0
    periods = statements.annual or statements.quarterly
    return max((len(period.values) for period in periods), default=0)


def _statement_score(statements: FinancialStatements | None) -> int:
    if statements is None:
        return -1
    periods = statements.annual or statements.quarterly
    latest_lines = _statement_line_count(statements)
    populated_cells = sum(len(period.values) for period in periods[:8])
    return latest_lines * 1_000 + populated_cells


def _statement_has_professional_coverage(statements: FinancialStatements) -> bool:
    if statements.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
        return False
    return _statement_line_count(statements) >= _MINIMUM_STATEMENT_LINES[statements.statement_type]


def _statements_to_dict(statements: FinancialStatements) -> dict[str, Any]:
    return {
        "symbol": statements.symbol,
        "name": statements.name,
        "statement_type": str(statements.statement_type),
        "annual": [_financial_period_to_dict(period) for period in statements.annual],
        "quarterly": [_financial_period_to_dict(period) for period in statements.quarterly],
        "currency": statements.currency,
        "provider": statements.provider,
        "quality": str(statements.quality),
        "metric_labels": statements.metric_labels,
        "metric_order": statements.metric_order,
        "metric_sections": statements.metric_sections,
        "source_url": statements.source_url,
        "timestamp": statements.timestamp.isoformat(),
    }


def _statements_from_dict(data: dict[str, Any], cached_quality: bool) -> FinancialStatements:
    quality = _cached_quality(data.get("quality"), cached_quality)
    return FinancialStatements(
        symbol=data.get("symbol", ""),
        name=data.get("name", ""),
        statement_type=StatementType(data.get("statement_type", StatementType.INCOME)),
        annual=[_financial_period_from_dict(period) for period in data.get("annual", [])],
        quarterly=[_financial_period_from_dict(period) for period in data.get("quarterly", [])],
        currency=data.get("currency", ""),
        provider=data.get("provider", "UNKNOWN"),
        quality=quality,
        metric_labels=data.get("metric_labels", {}),
        metric_order=data.get("metric_order", []),
        metric_sections=data.get("metric_sections", {}),
        source_url=data.get("source_url", ""),
        timestamp=_parse_datetime(data.get("timestamp")),
    )


def _financial_period_to_dict(period: FinancialPeriod) -> dict[str, Any]:
    return {
        "period": period.period,
        "end_date": period.end_date.isoformat() if period.end_date else None,
        "values": period.values,
        "source_form": period.source_form,
        "filed_date": period.filed_date.isoformat() if period.filed_date else None,
        "accession_number": period.accession_number,
        "derived": period.derived,
    }


def _financial_period_from_dict(data: dict[str, Any]) -> FinancialPeriod:
    raw_date = data.get("end_date")
    end_date: date | None = None
    if isinstance(raw_date, str):
        try:
            end_date = date.fromisoformat(raw_date)
        except ValueError:
            pass
    raw_filed_date = data.get("filed_date")
    filed_date: date | None = None
    if isinstance(raw_filed_date, str):
        try:
            filed_date = date.fromisoformat(raw_filed_date)
        except ValueError:
            pass
    return FinancialPeriod(
        period=data.get("period", "--"),
        end_date=end_date,
        values=data.get("values", {}),
        source_form=data.get("source_form", ""),
        filed_date=filed_date,
        accession_number=data.get("accession_number", ""),
        derived=bool(data.get("derived", False)),
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _cached_quality(value: Any, stale: bool) -> DataQuality:
    original = DataQuality(value or DataQuality.CACHED)
    if original == DataQuality.MOCK:
        return DataQuality.MOCK
    return DataQuality.CACHED if stale else original
