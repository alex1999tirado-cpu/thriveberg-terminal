from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from ajax_terminal.models.equity import CorporateEvent
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import DataQuality, EquityFundamentals, Quote
from ajax_terminal.services import workstation_service
from ajax_terminal.services.alert_service import AlertsLoad, evaluate_alerts, load_alert_dashboard
from ajax_terminal.storage.cache import SQLiteCache
from ajax_terminal.storage.workstation import AlertStore, PortfolioStore
from ajax_terminal.workstation_desktop import AlertsWorkspace


class _Market:
    def __init__(self, database, price: float = 101.0) -> None:
        self.cache = SQLiteCache(database)
        self.price = price

    async def quote(self, symbol: str, *, allow_mock: bool = False) -> Quote:
        assert not allow_mock
        return Quote(
            symbol,
            symbol,
            self.price,
            currency="USD",
            provider="TEST MARKET",
            quality=DataQuality.DELAYED,
        )

    async def bulk_quotes(self, symbols, *, allow_mock: bool = False):
        return [await self.quote(symbol, allow_mock=allow_mock) for symbol in symbols]

    async def equity_fundamentals(self, symbol: str) -> EquityFundamentals:
        return EquityFundamentals(
            symbol,
            symbol,
            pe=18.0,
            revenue_growth=0.12,
            provider="TEST FUNDAMENTALS",
            quality=DataQuality.DELAYED,
        )


class _News:
    def __init__(self, items: list[NewsItem]) -> None:
        self.items = items

    async def headlines(self, _topic: str, limit: int = 20):
        return self.items[:limit]


class _Research:
    def __init__(self, events: list[CorporateEvent]) -> None:
        self._events = events

    async def events(self, _symbol: str):
        return self._events


def _services(database, *, market=None, news=None, research=None):
    return {
        "market": market or _Market(database),
        "news": news or _News([]),
        "filings": object(),
        "research": research or _Research([]),
    }


def test_numeric_alert_triggers_on_crossing_and_rearms(tmp_path) -> None:
    database = tmp_path / "alerts.sqlite3"
    store = AlertStore(database)
    market = _Market(database, 101.0)
    store.add("AAPL", "PRICE", ">", 100)

    first = evaluate_alerts(store, **_services(database, market=market))
    repeated = evaluate_alerts(store, **_services(database, market=market))
    market.price = 99.0
    cleared = evaluate_alerts(store, **_services(database, market=market))
    market.price = 102.0
    rearmed = evaluate_alerts(store, **_services(database, market=market))

    assert len(first.new_events) == 1
    assert not repeated.new_events
    assert not cleared.new_events
    assert len(rearmed.new_events) == 1
    assert len(store.events()) == 2
    assert store.list()[0].trigger_count == 2

    first_event = store.events()[0]
    store.acknowledge(first_event.id)
    assert len(store.events()) == 2
    assert len(store.events(unacknowledged_only=True)) == 1


def test_concurrent_numeric_evaluations_create_one_transition_event(tmp_path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    rule = store.add("AAPL", "PRICE", ">", 100)
    observed = datetime.now(timezone.utc)

    def record(offset: int):
        return store.record_numeric_evaluation(
            rule.id or 0,
            101 + offset,
            True,
            provider="TEST",
            quality="DELAYED",
            observed_at=(observed + timedelta(microseconds=offset)).isoformat(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, (1, 2)))

    assert sum(item is not None for item in results) == 1
    assert len(store.events()) == 1


def test_alert_store_rejects_incompatible_operator_and_event_horizon(tmp_path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")

    with pytest.raises(ValueError, match="numeric operator"):
        store.add("AAPL", "PRICE", "NEW", 0)
    with pytest.raises(ValueError, match="<= operator"):
        store.add("AAPL", "EVENT_ANY", ">", 7, kind="EVENT")
    with pytest.raises(ValueError, match="between 0 and 365"):
        store.add("AAPL", "EVENT_ANY", "<=", 500, kind="EVENT")


def test_news_alert_primes_existing_feed_then_records_only_new_items(tmp_path) -> None:
    database = tmp_path / "alerts.sqlite3"
    store = AlertStore(database)
    store.add("AAPL", "NEWS", "NEW", 0, kind="NEWS")
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    old = NewsItem(
        now - timedelta(minutes=2), "TEST", "Existing headline", "https://example.com/old",
        provider="TEST NEWS", quality=DataQuality.DELAYED,
    )
    feed = _News([old])

    primed = evaluate_alerts(store, now=now, **_services(database, news=feed))
    fresh = NewsItem(
        now + timedelta(minutes=1), "TEST", "Fresh headline", "https://example.com/new",
        provider="TEST NEWS", quality=DataQuality.DELAYED,
    )
    late_old = NewsItem(
        now - timedelta(minutes=1), "TEST", "Late old headline", "https://example.com/late-old",
        provider="TEST NEWS", quality=DataQuality.DELAYED,
    )
    feed.items = [fresh, late_old, old]
    triggered = evaluate_alerts(
        store, now=now + timedelta(minutes=2), **_services(database, news=feed)
    )
    repeated = evaluate_alerts(
        store, now=now + timedelta(minutes=3), **_services(database, news=feed)
    )

    assert not primed.new_events
    assert [event.title for event in triggered.new_events] == ["Fresh headline"]
    assert not repeated.new_events
    assert len(store.events()) == 1


def test_upcoming_event_alert_is_immediate_and_deduplicated(tmp_path) -> None:
    database = tmp_path / "alerts.sqlite3"
    store = AlertStore(database)
    store.add("AAPL", "EVENT_EARNINGS", "<=", 7, kind="EVENT")
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    event = CorporateEvent(
        "AAPL",
        "Apple Inc.",
        "EARNINGS",
        now + timedelta(days=3),
        "EPS consensus 2.00",
        True,
        "TEST EVENTS",
        DataQuality.DELAYED,
    )
    research = _Research([event])

    first = evaluate_alerts(
        store, now=now, **_services(database, research=research)
    )
    second = evaluate_alerts(
        store, now=now + timedelta(minutes=1), **_services(database, research=research)
    )

    assert len(first.new_events) == 1
    assert first.new_events[0].value == 3.0
    assert not second.new_events


def test_fundamental_percent_alert_uses_display_percent_units(tmp_path) -> None:
    database = tmp_path / "alerts.sqlite3"
    store = AlertStore(database)
    store.add("AAPL", "REVENUE_GROWTH", ">", 10, kind="FUNDAMENTAL")

    load = evaluate_alerts(store, **_services(database))

    assert load.evaluations[0].value == 12.0
    assert len(load.new_events) == 1


def test_portfolio_risk_alert_uses_named_portfolio_and_real_positions(tmp_path) -> None:
    database = tmp_path / "alerts.sqlite3"
    portfolio = PortfolioStore(database)
    portfolio.create("RETIREMENT FUND", "USD")
    portfolio.record_cash_flow(
        "DEPOSIT", 10_000, name="RETIREMENT FUND", external_id="D1", source="TEST"
    )
    portfolio.record_trade(
        "AAPL", "BUY", 10, 100, currency="USD", trade_date="2026-01-02",
        name="RETIREMENT FUND", external_id="B1", source="TEST",
    )
    alerts = AlertStore(database)
    alerts.add(
        "RETIREMENT FUND", "VAR_95_PCT", ">", 2,
        kind="PORTFOLIO_RISK",
    )

    def risk_loader(positions, **kwargs):
        assert positions[0].symbol == "AAPL"
        assert kwargs["net_asset_value"] > 10_000
        return SimpleNamespace(
            available=True,
            historical_var_95=0.03,
            historical_var_99=0.04,
            expected_shortfall_95=0.05,
            annualized_volatility=0.20,
            max_drawdown=-0.15,
            beta=1.1,
            coverage_percent=100.0,
            methodology="TEST RISK METHODOLOGY",
        )

    load = evaluate_alerts(
        alerts,
        risk_loader=risk_loader,
        **_services(database),
    )

    assert load.evaluations[0].value == 3.0
    assert len(load.new_events) == 1


def test_alert_command_parses_multiword_portfolio_risk_target(tmp_path, monkeypatch) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    monkeypatch.setattr(
        workstation_service,
        "evaluate_alerts",
        lambda ledger, **_kwargs: load_alert_dashboard(ledger),
    )

    workstation_service.load_alerts(
        ("ADD", "RISK", "RETIREMENT", "FUND", "VAR_95_PCT", ">", "3%"),
        store,
    )

    rule = store.list()[0]
    assert (rule.kind, rule.symbol, rule.field, rule.operator, rule.threshold) == (
        "PORTFOLIO_RISK", "RETIREMENT FUND", "VAR_95_PCT", ">", 3.0,
    )


def test_alert_workspace_has_rules_and_trigger_history_tabs(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.add("AAPL", "PRICE", ">", 200)
    workspace = AlertsWorkspace(load_alert_dashboard(store), store)
    tabs = workspace.findChild(QTabWidget)

    assert tabs is not None
    assert tabs.count() == 2
    assert tabs.tabText(0) == "1) ACTIVE RULES"
    assert tabs.tabText(1).startswith("2) TRIGGER HISTORY")
    workspace.kind.setCurrentIndex(workspace.kind.findData("NEWS"))
    assert not workspace.threshold.isEnabled()
    assert workspace.operator.currentText() == "NEW"
    workspace.close()
    app.processEvents()
