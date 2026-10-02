from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ajax_terminal.config import setting
from ajax_terminal.country_registry import COUNTRY_REGISTRY
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.providers.banco_de_espana import BancoDeEspanaProvider, SERIES as BDE_SERIES
from ajax_terminal.providers.ecb import ECBProvider
from ajax_terminal.providers.finnhub import FinnhubProvider
from ajax_terminal.providers.fred_credit import FredCreditProvider, SERIES as CREDIT_SERIES
from ajax_terminal.providers.fred_yields import FredSovereignYieldProvider, SERIES as YIELD_SERIES
from ajax_terminal.providers.global_filings import ESEFFilingsProvider
from ajax_terminal.providers.japan_mof import JapanMofCurveProvider
from ajax_terminal.providers.sec import SECFilingsProvider
from ajax_terminal.providers.treasury import TreasuryProvider
from ajax_terminal.providers.world_bank import WorldBankProvider
from ajax_terminal.providers.eurostat import EurostatProvider
from ajax_terminal.providers.yahoo import YahooProvider
from ajax_terminal.providers.yahoo_options import YahooOptionsProvider
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.services.social_service import SocialService
from ajax_terminal.storage.data_quality import DataQualityStore, ProviderHealthRecord
from ajax_terminal.storage.database import DEFAULT_DB_PATH, get_connection


COVERAGE_DOMAINS = (
    "QUOTES",
    "HISTORY",
    "FUNDAMENTALS",
    "STATEMENTS",
    "FILINGS",
    "MACRO",
    "CURVES",
    "CREDIT",
    "OPTIONS",
    "NEWS",
    "SOCIAL",
)


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider: str
    group: str
    health_domain: str
    configured: bool
    configuration: str
    domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderHealthRow:
    provider: str
    group: str
    domain: str
    configured: bool
    configuration: str
    status: str
    quality: DataQuality
    latency_ms: float | None
    success_count: int
    failure_count: int
    last_checked_at: datetime | None
    message: str


@dataclass(frozen=True, slots=True)
class CacheDomainStatus:
    domain: str
    total: int
    fresh: int
    stale: int
    mock: int
    unavailable: int
    oldest_at: datetime | None
    newest_at: datetime | None
    providers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuoteComparison:
    provider: str
    status: str
    price: float | None
    currency: str
    quality: DataQuality
    timestamp: datetime | None
    difference_bp: float | None
    latency_ms: float | None
    message: str = ""
    alignment: str = ""


@dataclass(frozen=True, slots=True)
class DataQualityDashboard:
    providers: tuple[ProviderHealthRow, ...]
    cache: tuple[CacheDomainStatus, ...]
    capabilities: tuple[ProviderCapability, ...]
    comparisons: tuple[QuoteComparison, ...]
    symbol: str = ""
    generated_at: datetime = datetime.min.replace(tzinfo=timezone.utc)
    probes_run: bool = False

    @property
    def available_count(self) -> int:
        return sum(row.status == "AVAILABLE" for row in self.providers)

    @property
    def degraded_count(self) -> int:
        return sum(row.status == "DEGRADED" for row in self.providers)

    @property
    def failed_count(self) -> int:
        return sum(row.status == "FAILED" for row in self.providers)

    @property
    def fresh_cache_count(self) -> int:
        return sum(row.fresh for row in self.cache)

    @property
    def stale_cache_count(self) -> int:
        return sum(row.stale for row in self.cache)


@dataclass(frozen=True, slots=True)
class ProviderProbe:
    provider: str
    domain: str
    operation: Callable[[], Awaitable[Any]]


def provider_capabilities() -> tuple[ProviderCapability, ...]:
    finnhub_configured = FinnhubProvider().configured
    social = SocialService()
    companies_house = bool(setting("COMPANIES_HOUSE_API_KEY"))
    return (
        ProviderCapability(
            "YAHOO FINANCE", "MARKET DATA", "MARKET", True, "PUBLIC SESSION",
            ("QUOTES", "HISTORY", "FUNDAMENTALS", "STATEMENTS"),
        ),
        ProviderCapability(
            "YAHOO LISTED OPTIONS", "DERIVATIVES", "OPTIONS", True, "PUBLIC SESSION", ("OPTIONS",),
        ),
        ProviderCapability(
            "FINNHUB", "MARKET DATA", "REALTIME", finnhub_configured,
            "USER KEY" if finnhub_configured else "KEY NOT CONFIGURED", ("QUOTES",),
        ),
        ProviderCapability("US TREASURY", "OFFICIAL", "CURVES", True, "PUBLIC", ("CURVES",)),
        ProviderCapability("ECB", "OFFICIAL", "CURVES", True, "PUBLIC", ("CURVES", "MACRO")),
        ProviderCapability("JAPAN MOF", "OFFICIAL", "CURVES", True, "PUBLIC", ("CURVES",)),
        ProviderCapability("BANCO DE ESPANA", "OFFICIAL", "RATES", True, "PUBLIC", ("QUOTES", "HISTORY")),
        ProviderCapability("FRED / OECD", "OFFICIAL", "RATES", True, "PUBLIC", ("QUOTES", "HISTORY", "MACRO")),
        ProviderCapability("FRED / ICE BOFA", "OFFICIAL", "CREDIT", True, "PUBLIC", ("QUOTES", "HISTORY", "CREDIT")),
        ProviderCapability("WORLD BANK", "OFFICIAL", "MACRO", True, "PUBLIC", ("MACRO",)),
        ProviderCapability("EUROSTAT", "OFFICIAL", "MACRO", True, "PUBLIC", ("MACRO",)),
        ProviderCapability("SEC EDGAR", "REGULATORY", "FILINGS", True, "FAIR ACCESS", ("FILINGS", "STATEMENTS")),
        ProviderCapability("ESEF / FILINGS.XBRL.ORG", "REGULATORY", "FILINGS", True, "PUBLIC", ("FILINGS", "STATEMENTS")),
        ProviderCapability(
            "COMPANIES HOUSE", "REGULATORY", "FILINGS", companies_house,
            "USER KEY" if companies_house else "KEY NOT CONFIGURED", ("FILINGS",),
        ),
        ProviderCapability("RSS NEWS", "NEWS", "NEWS", True, "PUBLIC", ("NEWS",)),
        ProviderCapability(
            "SUPABASE SOCIAL", "COLLABORATION", "SOCIAL", social.configured,
            "PUBLIC CLIENT" if social.configured else "NOT CONFIGURED", ("SOCIAL",),
        ),
    )


def default_provider_probes() -> tuple[ProviderProbe, ...]:
    probes: list[ProviderProbe] = [
        ProviderProbe("YAHOO FINANCE", "MARKET", lambda: YahooProvider().quote("SPY")),
        ProviderProbe("YAHOO LISTED OPTIONS", "OPTIONS", lambda: YahooOptionsProvider().option_chain("AAPL")),
        ProviderProbe("US TREASURY", "CURVES", lambda: TreasuryProvider().curve("USD")),
        ProviderProbe("ECB", "CURVES", lambda: ECBProvider().curve("EUR")),
        ProviderProbe("JAPAN MOF", "CURVES", lambda: JapanMofCurveProvider().curve("JPY")),
        ProviderProbe("BANCO DE ESPANA", "RATES", lambda: BancoDeEspanaProvider().quote("ES10Y")),
        ProviderProbe("FRED / OECD", "RATES", lambda: FredSovereignYieldProvider().quote("DE10Y")),
        ProviderProbe("FRED / ICE BOFA", "CREDIT", lambda: FredCreditProvider().quote("USCORPIG")),
        ProviderProbe("WORLD BANK", "MACRO", lambda: WorldBankProvider().latest(["USA"], "GDP")),
        ProviderProbe("RSS NEWS", "NEWS", lambda: NewsService().headlines(limit=1)),
        ProviderProbe("SEC EDGAR", "FILINGS", lambda: SECFilingsProvider().filings("AAPL", limit=1)),
        ProviderProbe("ESEF / FILINGS.XBRL.ORG", "FILINGS", lambda: ESEFFilingsProvider().filings("SAN.MC", limit=1)),
    ]
    spain = COUNTRY_REGISTRY.resolve("ES")
    if spain is not None:
        probes.append(ProviderProbe("EUROSTAT", "MACRO", lambda: EurostatProvider().latest([spain], "CPI")))
    finnhub = FinnhubProvider()
    if finnhub.configured:
        probes.append(ProviderProbe("FINNHUB", "REALTIME", lambda: finnhub.quote("AAPL")))
    social = SocialService()
    if social.provider is not None:
        probes.append(
            ProviderProbe(
                "SUPABASE SOCIAL",
                "SOCIAL",
                lambda: _social_health(social.provider),
            )
        )
    return tuple(probes)


async def run_provider_probes(
    probes: Iterable[ProviderProbe],
    store: DataQualityStore,
) -> tuple[ProviderHealthRecord, ...]:
    async def run(probe: ProviderProbe) -> ProviderHealthRecord:
        started = time.perf_counter()
        try:
            payload = await probe.operation()
            latency = (time.perf_counter() - started) * 1_000.0
            if not _has_data(payload):
                return store.record(
                    probe.provider,
                    probe.domain,
                    status="FAILED",
                    latency_ms=latency,
                    message="Provider responded without a usable observation",
                )
            quality = _payload_quality(payload)
            status = "DEGRADED" if quality == DataQuality.CACHED else "AVAILABLE"
            return store.record(
                probe.provider,
                probe.domain,
                status=status,
                quality=quality,
                latency_ms=latency,
                message=_payload_message(payload),
            )
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1_000.0
            return store.record(
                probe.provider,
                probe.domain,
                status="FAILED",
                latency_ms=latency,
                message=_safe_error(exc),
            )

    return tuple(await asyncio.gather(*(run(probe) for probe in probes)))


def load_data_quality_dashboard(
    args: Iterable[str] = (),
    *,
    store: DataQualityStore | None = None,
    cache_path: Path | str = DEFAULT_DB_PATH,
    probes: Iterable[ProviderProbe] | None = None,
    quote_providers: Iterable[Any] | None = None,
) -> DataQualityDashboard:
    tokens = tuple(str(token).strip().upper() for token in args if str(token).strip())
    run_probes = "PROBE" in tokens or "REFRESH" in tokens
    symbol = next((token for token in tokens if token not in {"PROBE", "REFRESH"}), "")
    health_store = store or DataQualityStore(cache_path)
    if run_probes:
        asyncio.run(run_provider_probes(default_provider_probes() if probes is None else probes, health_store))
    comparisons: tuple[QuoteComparison, ...] = ()
    if symbol:
        selected = tuple(quote_providers) if quote_providers is not None else _comparison_providers(symbol)
        comparisons = asyncio.run(compare_quote_providers(symbol, selected, health_store))
    capabilities = provider_capabilities()
    return DataQualityDashboard(
        providers=_provider_rows(capabilities, health_store.records()),
        cache=cache_inventory(cache_path),
        capabilities=capabilities,
        comparisons=comparisons,
        symbol=symbol,
        generated_at=datetime.now(timezone.utc),
        probes_run=run_probes,
    )


async def compare_quote_providers(
    symbol: str,
    providers: Iterable[Any],
    store: DataQualityStore | None = None,
) -> tuple[QuoteComparison, ...]:
    clean = INSTRUMENT_REGISTRY.resolve(symbol).symbol

    async def read(provider: Any) -> QuoteComparison:
        name = str(getattr(provider, "name", provider.__class__.__name__)).upper()
        configured = bool(getattr(provider, "configured", True))
        if not configured:
            return QuoteComparison(
                name, "DISABLED", None, "", DataQuality.UNAVAILABLE, None, None, None,
                "Provider credentials are not configured",
            )
        started = time.perf_counter()
        try:
            quote = await provider.quote(clean)
            latency = (time.perf_counter() - started) * 1_000.0
            if quote.price is None or not math.isfinite(quote.price):
                raise ValueError("Provider returned no finite price")
            status = "DEGRADED" if quote.quality == DataQuality.CACHED else "AVAILABLE"
            if store is not None:
                store.record(name, "QUOTE COMPARISON", status=status, quality=quote.quality, latency_ms=latency)
            return QuoteComparison(
                name, status, quote.price, quote.currency, quote.quality, quote.timestamp, None, latency,
            )
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1_000.0
            message = _safe_error(exc)
            if store is not None:
                store.record(name, "QUOTE COMPARISON", status="FAILED", latency_ms=latency, message=message)
            return QuoteComparison(
                name, "FAILED", None, "", DataQuality.UNAVAILABLE, None, None, latency, message,
            )

    rows = list(await asyncio.gather(*(read(provider) for provider in providers)))
    prices = sorted(row.price for row in rows if row.price is not None and row.status in {"AVAILABLE", "DEGRADED"})
    reference = _median(prices)
    source_count = len(prices)
    return tuple(
        QuoteComparison(
            row.provider,
            row.status,
            row.price,
            row.currency,
            row.quality,
            row.timestamp,
            ((row.price / reference) - 1.0) * 10_000.0 if row.price is not None and reference else None,
            row.latency_ms,
            row.message,
            (
                "SINGLE SOURCE"
                if row.price is not None and source_count < 2
                else "DIVERGENT"
                if row.price is not None
                and reference
                and abs(((row.price / reference) - 1.0) * 10_000.0) > 50.0
                else "ALIGNED"
                if row.price is not None
                else ""
            ),
        )
        for row in rows
    )


def cache_inventory(path: Path | str = DEFAULT_DB_PATH) -> tuple[CacheDomainStatus, ...]:
    now = time.time()
    with get_connection(path) as connection:
        rows = connection.execute(
            "SELECT key, value, expires_at, updated_at FROM cache ORDER BY key"
        ).fetchall()
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        groups[_cache_domain(str(row["key"]))].append(row)
    result: list[CacheDomainStatus] = []
    for domain, entries in sorted(groups.items()):
        fresh = sum(float(row["expires_at"]) >= now for row in entries)
        providers: set[str] = set()
        mock = 0
        unavailable = 0
        timestamps: list[datetime] = []
        for row in entries:
            try:
                payload = json.loads(row["value"])
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = None
            payload_providers, qualities = _payload_metadata(payload)
            providers.update(payload_providers)
            mock += sum(quality == "MOCK" for quality in qualities)
            unavailable += sum(quality == "UNAVAILABLE" for quality in qualities)
            parsed = _datetime(row["updated_at"])
            if parsed is not None:
                timestamps.append(parsed)
        result.append(
            CacheDomainStatus(
                domain=domain,
                total=len(entries),
                fresh=fresh,
                stale=len(entries) - fresh,
                mock=mock,
                unavailable=unavailable,
                oldest_at=min(timestamps) if timestamps else None,
                newest_at=max(timestamps) if timestamps else None,
                providers=tuple(sorted(providers)),
            )
        )
    return tuple(result)


def _provider_rows(
    capabilities: tuple[ProviderCapability, ...],
    records: tuple[ProviderHealthRecord, ...],
) -> tuple[ProviderHealthRow, ...]:
    health = {(row.provider, row.domain): row for row in records}
    rows: list[ProviderHealthRow] = []
    for capability in capabilities:
        record = health.get((capability.provider, capability.health_domain))
        if not capability.configured:
            status = "DISABLED"
        elif record is None:
            status = "UNTESTED"
        else:
            status = record.status
        rows.append(
            ProviderHealthRow(
                provider=capability.provider,
                group=capability.group,
                domain=capability.health_domain,
                configured=capability.configured,
                configuration=capability.configuration,
                status=status,
                quality=record.quality if record is not None else DataQuality.UNAVAILABLE,
                latency_ms=record.latency_ms if record is not None else None,
                success_count=record.success_count if record is not None else 0,
                failure_count=record.failure_count if record is not None else 0,
                last_checked_at=record.last_checked_at if record is not None else None,
                message=record.message if record is not None else "",
            )
        )
    return tuple(rows)


def _comparison_providers(symbol: str) -> tuple[Any, ...]:
    clean = INSTRUMENT_REGISTRY.resolve(symbol).symbol
    instrument = INSTRUMENT_REGISTRY.resolve(clean)
    providers: list[Any] = []
    if instrument.asset_class == AssetClass.EQUITY:
        providers.append(FinnhubProvider())
        providers.append(YahooProvider())
    else:
        if clean in BDE_SERIES:
            providers.append(BancoDeEspanaProvider())
        if clean in YIELD_SERIES:
            providers.append(FredSovereignYieldProvider())
        if clean in CREDIT_SERIES:
            providers.append(FredCreditProvider())
        if not providers:
            providers.append(YahooProvider())
    return tuple(providers)


def _has_data(payload: Any) -> bool:
    if payload is None:
        return False
    quality = _payload_quality(payload)
    if quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
        return False
    if isinstance(payload, Quote):
        return payload.price is not None and math.isfinite(payload.price)
    if isinstance(payload, dict):
        return bool(payload)
    if isinstance(payload, (list, tuple, set)):
        return bool(payload) and any(_has_data(item) for item in payload)
    for attribute in ("points", "filings", "bars", "calls", "items"):
        if hasattr(payload, attribute):
            return bool(getattr(payload, attribute))
    return True


def _payload_quality(payload: Any) -> DataQuality:
    raw = getattr(payload, "quality", None)
    if raw is not None:
        try:
            return DataQuality(str(raw))
        except ValueError:
            pass
    if isinstance(payload, dict) and payload:
        return _combined_quality(_payload_quality(value) for value in payload.values())
    if isinstance(payload, (list, tuple)) and payload:
        return _combined_quality(_payload_quality(value) for value in payload)
    return DataQuality.DELAYED


def _combined_quality(qualities: Iterable[DataQuality]) -> DataQuality:
    values = set(qualities)
    for quality in (
        DataQuality.UNAVAILABLE,
        DataQuality.MOCK,
        DataQuality.CACHED,
        DataQuality.DELAYED,
        DataQuality.REALTIME,
    ):
        if quality in values:
            return quality
    return DataQuality.DELAYED


def _payload_message(payload: Any) -> str:
    message = getattr(payload, "message", "")
    return " ".join(str(message).split())[:240]


def _safe_error(exc: Exception) -> str:
    message = " ".join((str(exc).strip() or exc.__class__.__name__).split())
    message = re.sub(r"(?i)(token|api[_ -]?key|secret|password)=([^&\s]+)", r"\1=[REDACTED]", message)
    message = re.sub(r"https://([^/?\s]+)[^\s]*", r"https://\1/[REDACTED]", message)
    return message[:240]


def _cache_domain(key: str) -> str:
    prefix = key.split(":", 1)[0].upper()
    return {
        "QUOTE": "QUOTES",
        "HISTORY": "HISTORY",
        "FUNDAMENTALS": "FUNDAMENTALS",
        "STATEMENTS": "STATEMENTS",
        "FILINGS": "FILINGS",
        "MACRO": "MACRO",
        "CURVE": "CURVES",
        "NEWS": "NEWS",
        "OPTIONS": "OPTIONS",
        "RESEARCH": "RESEARCH",
        "EVENT-UNIVERSE": "EVENTS",
    }.get(prefix, prefix or "OTHER")


def _payload_metadata(payload: Any) -> tuple[set[str], list[str]]:
    providers: set[str] = set()
    qualities: list[str] = []
    if isinstance(payload, dict):
        provider = payload.get("provider") or payload.get("source")
        if isinstance(provider, str) and provider.strip():
            providers.add(provider.strip().upper())
        quality = payload.get("quality")
        if isinstance(quality, str):
            qualities.append(quality.upper())
        for value in payload.values():
            if isinstance(value, (dict, list)):
                nested_providers, nested_qualities = _payload_metadata(value)
                providers.update(nested_providers)
                qualities.extend(nested_qualities)
    elif isinstance(payload, list):
        for value in payload:
            nested_providers, nested_qualities = _payload_metadata(value)
            providers.update(nested_providers)
            qualities.extend(nested_qualities)
    return providers, qualities


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


async def _social_health(provider: Any) -> bool:
    await provider.health_check()
    return True
