from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ajax_terminal.models.quote import DataQuality, EquityFundamentals, Quote
from ajax_terminal.services.equity_research_service import EquityResearchService
from ajax_terminal.services.filings_service import FilingsService
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.services.portfolio_risk_service import (
    PortfolioRiskPosition,
    load_portfolio_risk,
)
from ajax_terminal.storage.workstation import (
    AlertEvent,
    AlertRule,
    AlertStore,
    PendingAlertEvent,
    PortfolioStore,
)


ALERT_KIND_LABELS = {
    "MARKET": "MARKET DATA",
    "FUNDAMENTAL": "FUNDAMENTALS",
    "FILING": "REGULATORY FILINGS",
    "NEWS": "NEWS",
    "EVENT": "CORPORATE EVENTS",
    "PORTFOLIO_RISK": "PORTFOLIO RISK",
}
ALERT_KIND_FIELDS = {
    "MARKET": ("PRICE", "CHANGE_PCT", "VOLUME", "BID", "ASK"),
    "FUNDAMENTAL": (
        "MARKET_CAP", "PE", "FORWARD_PE", "DIVIDEND_YIELD", "REVENUE_GROWTH",
        "OPERATING_MARGIN", "ROE", "BETA",
    ),
    "FILING": ("FILING_ANY", "FILING_ANNUAL", "FILING_QUARTERLY"),
    "NEWS": ("NEWS",),
    "EVENT": (
        "EVENT_ANY", "EVENT_EARNINGS", "EVENT_EX_DIVIDEND", "EVENT_DIVIDEND_PAYMENT",
    ),
    "PORTFOLIO_RISK": (
        "VOLATILITY_PCT", "VAR_95_PCT", "VAR_99_PCT", "ES_95_PCT",
        "MAX_DRAWDOWN_PCT", "BETA", "COVERAGE_PCT",
    ),
}
ALERT_INTERVAL_SECONDS = {
    "MARKET": 30,
    "NEWS": 120,
    "FUNDAMENTAL": 15 * 60,
    "FILING": 15 * 60,
    "EVENT": 15 * 60,
    "PORTFOLIO_RISK": 30 * 60,
}
STREAM_KINDS = {"FILING", "NEWS"}
DISCRETE_KINDS = {"EVENT"}
STATE_KINDS = {"MARKET", "FUNDAMENTAL", "PORTFOLIO_RISK"}

_MARKET_FIELDS = {
    "PRICE": "price",
    "CHANGE_PCT": "change_percent",
    "VOLUME": "volume",
    "BID": "bid",
    "ASK": "ask",
}
_FUNDAMENTAL_FIELDS = {
    "MARKET_CAP": "market_cap",
    "PE": "pe",
    "FORWARD_PE": "forward_pe",
    "DIVIDEND_YIELD": "dividend_yield",
    "REVENUE_GROWTH": "revenue_growth",
    "OPERATING_MARGIN": "operating_margin",
    "ROE": "roe",
    "BETA": "beta",
}
_FUNDAMENTAL_PERCENT_FIELDS = {
    "DIVIDEND_YIELD",
    "REVENUE_GROWTH",
    "OPERATING_MARGIN",
    "ROE",
}
_RISK_FIELDS = {
    "VOLATILITY_PCT": "annualized_volatility",
    "VAR_95_PCT": "historical_var_95",
    "VAR_99_PCT": "historical_var_99",
    "ES_95_PCT": "expected_shortfall_95",
    "MAX_DRAWDOWN_PCT": "max_drawdown",
    "BETA": "beta",
    "COVERAGE_PCT": "coverage_percent",
}
_RISK_PERCENT_FIELDS = {
    "VOLATILITY_PCT",
    "VAR_95_PCT",
    "VAR_99_PCT",
    "ES_95_PCT",
    "MAX_DRAWDOWN_PCT",
}


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    rule: AlertRule
    quote: Quote
    value: float | None
    triggered: bool
    new_events: int = 0


@dataclass(frozen=True, slots=True)
class AlertsLoad:
    evaluations: tuple[AlertEvaluation, ...]
    refreshed_at: datetime
    events: tuple[AlertEvent, ...] = ()
    new_events: tuple[AlertEvent, ...] = ()
    evaluated: int = 0
    failures: int = 0
    unacknowledged: int = 0
    background: bool = False


@dataclass(frozen=True, slots=True)
class _Outcome:
    mode: str
    value: float | None = None
    active: bool = False
    items: tuple[PendingAlertEvent, ...] = ()
    provider: str = ""
    quality: str = "UNAVAILABLE"
    title: str = ""
    detail: str = ""
    url: str = ""
    error: str = ""


def evaluate_alerts(
    store: AlertStore | None = None,
    *,
    force: bool = True,
    background: bool = False,
    now: datetime | None = None,
    market: MarketService | None = None,
    news: NewsService | None = None,
    filings: FilingsService | None = None,
    research: EquityResearchService | None = None,
    risk_loader: Callable[..., object] = load_portfolio_risk,
) -> AlertsLoad:
    ledger = store or AlertStore()
    observed_at = _aware(now or datetime.now(timezone.utc))
    rules = ledger.list(enabled_only=True)
    due = [rule for rule in rules if force or _is_due(rule, observed_at)]
    if not due:
        return load_alert_dashboard(ledger, now=observed_at, background=background)

    market_service = market or MarketService()
    news_service = news or NewsService(market_service.cache)
    filings_service = filings or FilingsService(market_service.cache)
    research_service = research or EquityResearchService(market_service)
    remote_rules = [rule for rule in due if rule.kind != "PORTFOLIO_RISK"]

    async def load_remote() -> list[_Outcome | Exception]:
        return await asyncio.gather(
            *(
                _evaluate_remote(
                    rule,
                    observed_at,
                    market_service,
                    news_service,
                    filings_service,
                    research_service,
                )
                for rule in remote_rules
            ),
            return_exceptions=True,
        )

    outcomes: dict[int, _Outcome | Exception] = {}
    if remote_rules:
        loaded = asyncio.run(load_remote())
        outcomes.update(
            (int(rule.id), result)
            for rule, result in zip(remote_rules, loaded)
            if rule.id is not None
        )
    for rule in due:
        if rule.kind != "PORTFOLIO_RISK" or rule.id is None:
            continue
        try:
            outcomes[int(rule.id)] = _portfolio_risk_outcome(
                rule,
                market_service,
                ledger.path,
                risk_loader,
            )
        except Exception as exc:
            outcomes[int(rule.id)] = exc

    created: list[AlertEvent] = []
    failures = 0
    observed_iso = observed_at.isoformat()
    for rule in due:
        if rule.id is None:
            continue
        outcome = outcomes.get(int(rule.id))
        if isinstance(outcome, Exception):
            failures += 1
            ledger.record_failure(
                rule.id,
                str(outcome) or outcome.__class__.__name__,
                observed_at=observed_iso,
            )
            continue
        if outcome is None or outcome.error:
            failures += 1
            ledger.record_failure(
                rule.id,
                outcome.error if outcome is not None else "ALERT EVALUATION RETURNED NO RESULT",
                provider=outcome.provider if outcome is not None else "",
                quality=outcome.quality if outcome is not None else "UNAVAILABLE",
                observed_at=observed_iso,
            )
            continue
        if outcome.mode == "STATE":
            event = ledger.record_numeric_evaluation(
                rule.id,
                outcome.value,
                outcome.active,
                provider=outcome.provider,
                quality=outcome.quality,
                title=outcome.title,
                detail=outcome.detail,
                url=outcome.url,
                observed_at=observed_iso,
            )
            if event is not None:
                created.append(event)
            continue
        created.extend(
            ledger.record_feed_evaluation(
                rule.id,
                list(outcome.items),
                prime_initial=outcome.mode == "STREAM",
                provider=outcome.provider,
                quality=outcome.quality,
                current_value=outcome.value,
                observed_at=observed_iso,
            )
        )

    return load_alert_dashboard(
        ledger,
        now=observed_at,
        new_events=tuple(created),
        evaluated=len(due),
        failures=failures,
        background=background,
    )


def load_alert_dashboard(
    store: AlertStore | None = None,
    *,
    now: datetime | None = None,
    new_events: tuple[AlertEvent, ...] = (),
    evaluated: int = 0,
    failures: int = 0,
    background: bool = False,
) -> AlertsLoad:
    ledger = store or AlertStore()
    rules = ledger.list()
    new_by_rule: dict[int, int] = {}
    for event in new_events:
        new_by_rule[event.alert_id] = new_by_rule.get(event.alert_id, 0) + 1
    evaluations: list[AlertEvaluation] = []
    for rule in rules:
        quality = _quality(rule.last_quality)
        quote = Quote(
            rule.symbol,
            rule.symbol,
            rule.last_value if rule.kind == "MARKET" and rule.field == "PRICE" else None,
            provider=rule.last_provider or "UNAVAILABLE",
            quality=quality,
        )
        current_new = new_by_rule.get(int(rule.id or 0), 0)
        triggered = bool(rule.last_state) if rule.kind in STATE_KINDS else current_new > 0
        evaluations.append(
            AlertEvaluation(rule, quote, rule.last_value, triggered, current_new)
        )
    return AlertsLoad(
        evaluations=tuple(evaluations),
        refreshed_at=(now or datetime.now(timezone.utc)).astimezone(),
        events=tuple(ledger.events(limit=500)),
        new_events=new_events,
        evaluated=evaluated,
        failures=failures,
        unacknowledged=ledger.unacknowledged_count(),
        background=background,
    )


async def _evaluate_remote(
    rule: AlertRule,
    now: datetime,
    market: MarketService,
    news: NewsService,
    filings: FilingsService,
    research: EquityResearchService,
) -> _Outcome:
    if rule.kind == "MARKET":
        quote = await market.quote(rule.symbol, allow_mock=False)
        value = getattr(quote, _MARKET_FIELDS[rule.field], None)
        if value is None or quote.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
            return _Outcome(
                "STATE", provider=quote.provider, quality=str(quote.quality),
                error="VERIFIED MARKET VALUE UNAVAILABLE",
            )
        return _numeric_outcome(
            rule,
            float(value),
            quote.provider,
            quote.quality,
            f"{rule.symbol} {rule.field} ALERT",
        )

    if rule.kind == "FUNDAMENTAL":
        fundamentals = await market.equity_fundamentals(rule.symbol)
        value = _fundamental_value(fundamentals, rule.field)
        if value is None or fundamentals.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
            return _Outcome(
                "STATE", provider=fundamentals.provider, quality=str(fundamentals.quality),
                error="VERIFIED FUNDAMENTAL VALUE UNAVAILABLE",
            )
        return _numeric_outcome(
            rule,
            value,
            fundamentals.provider,
            fundamentals.quality,
            f"{rule.symbol} {rule.field} FUNDAMENTAL ALERT",
        )

    if rule.kind == "FILING":
        forms = {
            "FILING_ANNUAL": ("10-K",),
            "FILING_QUARTERLY": ("10-Q",),
        }.get(rule.field, ("10-K", "10-Q"))
        collection = await filings.filings(rule.symbol, forms=forms, limit=20)
        if not collection.filings and collection.quality == DataQuality.UNAVAILABLE:
            return _Outcome(
                "STREAM", provider=collection.provider, quality=str(collection.quality),
                error=collection.message or "REGULATORY FILING FEED UNAVAILABLE",
            )
        items = tuple(
            PendingAlertEvent(
                fingerprint=_fingerprint(
                    "FILING",
                    filing.jurisdiction,
                    filing.accession_number,
                    filing.document_url,
                    filing.form,
                    filing.filing_date.isoformat(),
                ),
                occurred_at=datetime.combine(
                    filing.filing_date, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                title=f"{rule.symbol} {filing.form} FILED",
                detail=(
                    f"{filing.description or collection.company_name} | "
                    f"REPORT {filing.report_date.isoformat() if filing.report_date else '--'}"
                ),
                url=filing.document_url,
                provider=collection.provider,
                quality=str(collection.quality),
            )
            for filing in collection.filings
        )
        return _Outcome(
            "STREAM", items=items, provider=collection.provider,
            quality=str(collection.quality),
        )

    if rule.kind == "NEWS":
        headlines = await news.headlines(rule.symbol, limit=20)
        verified = [
            item for item in headlines
            if item.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        if not verified:
            return _Outcome("STREAM", error="NO VERIFIED NEWS FEED RETURNED")
        items = tuple(
            PendingAlertEvent(
                fingerprint=_fingerprint(
                    "NEWS", item.link, item.headline, item.timestamp.isoformat()
                ),
                occurred_at=_aware(item.timestamp).isoformat(),
                title=item.headline,
                detail=item.summary,
                url=item.link,
                provider=item.provider or item.source,
                quality=str(item.quality),
            )
            for item in verified
        )
        return _Outcome(
            "STREAM",
            items=items,
            provider=" / ".join(dict.fromkeys(item.provider or item.source for item in verified)),
            quality=str(_combined_quality(item.quality for item in verified)),
        )

    if rule.kind == "EVENT":
        events = [
            event for event in await research.events(rule.symbol)
            if event.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        maximum_days = max(0.0, rule.threshold)
        matching = []
        for event in events:
            event_time = _aware(event.event_date)
            days = (event_time - now).total_seconds() / 86_400
            if 0 <= days <= maximum_days and _event_matches(rule.field, event.event_type):
                matching.append((days, event, event_time))
        matching.sort(key=lambda item: item[2])
        items = tuple(
            PendingAlertEvent(
                fingerprint=_fingerprint(
                    "EVENT", event.symbol, event.event_type, event_time.isoformat()
                ),
                occurred_at=now.isoformat(),
                title=f"{event.symbol} {event.event_type}",
                detail=(
                    f"SCHEDULED {event_time:%Y-%m-%d %H:%M %Z} | "
                    f"{event.detail or 'NO ADDITIONAL DETAIL'}"
                ),
                value=days,
                provider=event.provider,
                quality=str(event.quality),
            )
            for days, event, event_time in matching
        )
        all_providers = " / ".join(dict.fromkeys(event.provider for event in events))
        quality = _combined_quality(event.quality for event in events)
        return _Outcome(
            "DISCRETE",
            value=matching[0][0] if matching else None,
            items=items,
            provider=all_providers or "YAHOO FINANCE",
            quality=str(quality),
        )

    return _Outcome("STATE", error=f"UNSUPPORTED ALERT KIND {rule.kind}")


def _portfolio_risk_outcome(
    rule: AlertRule,
    market: MarketService,
    database_path,
    risk_loader: Callable[..., object],
) -> _Outcome:
    portfolio_store = PortfolioStore(database_path)
    positions = portfolio_store.positions(rule.symbol)
    if not positions:
        return _Outcome("STATE", error=f"PORTFOLIO {rule.symbol} HAS NO POSITIONS")
    base_currency = portfolio_store.base_currency(rule.symbol)

    async def values() -> tuple[list[PortfolioRiskPosition], float, list[Quote]]:
        quotes = await market.bulk_quotes(
            [position.symbol for position in positions], allow_mock=False
        )
        by_symbol = {quote.symbol: quote for quote in quotes}
        currencies = {
            (by_symbol.get(position.symbol).currency if by_symbol.get(position.symbol) else "")
            or position.currency
            or base_currency
            for position in positions
        }

        async def fx_rate(currency: str) -> float | None:
            clean = currency.strip().upper()
            if not clean or clean == base_currency.upper():
                return 1.0
            direct = await market.quote(f"{clean}{base_currency}", allow_mock=False)
            if direct.price is not None and direct.price > 0:
                return direct.price
            inverse = await market.quote(f"{base_currency}{clean}", allow_mock=False)
            if inverse.price is not None and inverse.price > 0:
                return 1.0 / inverse.price
            return None

        rates = await asyncio.gather(*(fx_rate(currency) for currency in sorted(currencies)))
        by_currency = dict(zip(sorted(currencies), rates))
        risk_positions: list[PortfolioRiskPosition] = []
        for position in positions:
            quote = by_symbol.get(position.symbol)
            if quote is None or quote.price is None or quote.quality in {
                DataQuality.MOCK,
                DataQuality.UNAVAILABLE,
            }:
                continue
            currency = (quote.currency or position.currency or base_currency).upper()
            rate = by_currency.get(currency)
            if rate is None:
                continue
            risk_positions.append(
                PortfolioRiskPosition(
                    position.symbol,
                    position.quantity * quote.price * rate,
                    currency,
                )
            )
        cash = sum(
            flow.amount * flow.fx_rate
            for flow in portfolio_store.cash_flows(rule.symbol, limit=10_000)
        )
        return risk_positions, sum(item.market_value for item in risk_positions) + cash, quotes

    risk_positions, net_asset_value, quotes = asyncio.run(values())
    if not risk_positions or net_asset_value <= 0:
        return _Outcome("STATE", error="VERIFIED PORTFOLIO VALUE UNAVAILABLE")
    report = risk_loader(
        risk_positions,
        net_asset_value=net_asset_value,
        base_currency=base_currency,
        benchmark="SPY",
        period="1Y",
        market=market,
    )
    if not getattr(report, "available", False):
        return _Outcome("STATE", error=getattr(report, "message", "PORTFOLIO RISK UNAVAILABLE"))
    raw = getattr(report, _RISK_FIELDS[rule.field], None)
    if raw is None:
        return _Outcome("STATE", error=f"{rule.field} UNAVAILABLE")
    value = float(raw)
    if rule.field in _RISK_PERCENT_FIELDS:
        value = abs(value) * 100.0
    quality = _combined_quality(quote.quality for quote in quotes)
    providers = " / ".join(dict.fromkeys(quote.provider for quote in quotes if quote.provider))
    return _numeric_outcome(
        rule,
        value,
        providers or "PORTFOLIO RISK",
        quality,
        f"{rule.symbol} {rule.field} RISK ALERT",
        detail=getattr(report, "methodology", ""),
    )


def _numeric_outcome(
    rule: AlertRule,
    value: float,
    provider: str,
    quality: DataQuality,
    title: str,
    *,
    detail: str = "",
) -> _Outcome:
    if not math.isfinite(value):
        return _Outcome("STATE", provider=provider, quality=str(quality), error="NON-FINITE VALUE")
    active = _compare(value, rule.operator, rule.threshold)
    return _Outcome(
        "STATE",
        value=value,
        active=active,
        provider=provider,
        quality=str(quality),
        title=title,
        detail=detail or f"OBSERVED {value:,.6g}; RULE {rule.operator} {rule.threshold:,.6g}",
    )


def _fundamental_value(fundamentals: EquityFundamentals, field: str) -> float | None:
    raw = getattr(fundamentals, _FUNDAMENTAL_FIELDS[field], None)
    if raw is None:
        return None
    value = float(raw)
    return value * 100.0 if field in _FUNDAMENTAL_PERCENT_FIELDS else value


def _event_matches(field: str, event_type: str) -> bool:
    normalized = " ".join(event_type.upper().replace("-", " ").split())
    return {
        "EVENT_ANY": True,
        "EVENT_EARNINGS": "EARNINGS" in normalized,
        "EVENT_EX_DIVIDEND": "EX DIVIDEND" in normalized,
        "EVENT_DIVIDEND_PAYMENT": "DIVIDEND PAYMENT" in normalized,
    }.get(field, False)


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    return math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)


def _is_due(rule: AlertRule, now: datetime) -> bool:
    if not rule.enabled or not rule.last_evaluated_at:
        return rule.enabled
    try:
        last = _aware(datetime.fromisoformat(rule.last_evaluated_at))
    except ValueError:
        return True
    interval = ALERT_INTERVAL_SECONDS.get(rule.kind, 15 * 60)
    return (now - last).total_seconds() >= interval


def _combined_quality(values) -> DataQuality:
    qualities = {value if isinstance(value, DataQuality) else _quality(str(value)) for value in values}
    if not qualities:
        return DataQuality.UNAVAILABLE
    for quality in (
        DataQuality.UNAVAILABLE,
        DataQuality.CACHED,
        DataQuality.DELAYED,
        DataQuality.REALTIME,
    ):
        if quality in qualities:
            return quality
    return DataQuality.UNAVAILABLE


def _quality(value: str) -> DataQuality:
    try:
        return DataQuality(value)
    except ValueError:
        return DataQuality.UNAVAILABLE


def _fingerprint(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part).strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
