from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget
from PySide6.QtCore import QSettings

from ajax_terminal.desktop_app import AjaxDesktopWindow, DesktopRoute
from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.services.workstation_service import (
    AlertsLoad,
    AlertEvaluation,
    DataAuditEntry,
    DataAuditLoad,
    EventCalendarLoad,
    PortfolioLine,
    PortfolioLoad,
    WatchlistLoad,
    load_event_calendar,
    scan_beta_releases,
)
from ajax_terminal.storage.cache import WatchlistStore
from ajax_terminal.storage.workstation import (
    AlertRule,
    AlertStore,
    PortfolioPosition,
    PortfolioStore,
    SavedScreenStore,
    WorkspaceSnapshot,
    WorkspaceStore,
)
from ajax_terminal.workstation_desktop import (
    AlertsWorkspace,
    DataAuditWorkspace,
    EventCalendarWorkspace,
    PortfolioWorkspace,
    WatchlistWorkspace,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_persistent_workstation_stores_round_trip(tmp_path) -> None:
    database = tmp_path / "terminal.sqlite3"

    watchlists = WatchlistStore(database)
    watchlists.create("TECH")
    watchlists.add("AAPL", "TECH")
    watchlists.add("MSFT", "TECH")
    watchlists.move("MSFT", -1, "TECH")
    assert watchlists.symbols("TECH") == ["MSFT", "AAPL"]
    assert watchlists.rename("TECH", "QUALITY") == "QUALITY"
    assert watchlists.symbols("QUALITY") == ["MSFT", "AAPL"]

    portfolios = PortfolioStore(database)
    portfolios.upsert("AAPL", 12.5, 180.0, "USD", "MAIN")
    position = portfolios.positions("MAIN")[0]
    assert (position.symbol, position.quantity, position.cost_basis) == ("AAPL", 12.5, 180.0)

    alerts = AlertStore(database)
    alert = alerts.add("AAPL", "PRICE", ">", 200)
    alerts.record_evaluation(alert.id or 0, 205.0, True)
    persisted_alert = alerts.list()[0]
    assert persisted_alert.last_value == 205.0
    assert persisted_alert.last_triggered_at

    workspaces = WorkspaceStore(database)
    saved = workspaces.save(WorkspaceSnapshot("TRADING", "AAPL GP 1Y", "AAPL", ("HOME", "AAPL", "AAPL GP 1Y")))
    assert workspaces.get("TRADING") == saved

    screens = SavedScreenStore(database)
    screens.save("VALUE", "MARKETCAP>10B PE<15")
    assert screens.list() == [("VALUE", "MARKETCAP>10B PE<15")]


def test_beta_release_scan_verifies_checksum(tmp_path) -> None:
    executable = tmp_path / "THRIVEBERG_Terminal_BETA_007.exe"
    executable.write_bytes(b"test beta")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest().upper()
    executable.with_suffix(".sha256").write_text(f"{digest}  {executable.name}\n", encoding="utf-8")

    releases = scan_beta_releases(tmp_path)

    assert len(releases) == 1
    assert releases[0].version == 7
    assert releases[0].verified


def test_workstation_widgets_use_structured_tables() -> None:
    app = _app()
    now = datetime.now(timezone.utc)
    quote = Quote("AAPL", "Apple Inc.", 200.0, change=2.0, change_percent=1.0, provider="TEST", quality=DataQuality.DELAYED)
    audit = DataAuditWorkspace(
        DataAuditLoad("AAPL", (DataAuditEntry("QUOTE.PRICE", "200", "TEST", DataQuality.DELAYED, now, "USD"),))
    )
    watchlist = WatchlistWorkspace(WatchlistLoad("TEST", ("TEST",), (quote,)), WatchlistStore(":memory:"))
    position = PortfolioPosition("MAIN", "AAPL", 2, 150, "USD")
    portfolio = PortfolioWorkspace(
        PortfolioLoad("MAIN", ("MAIN",), "USD", (PortfolioLine(position, quote, 400, 300, 100, 33.33, 100),), 400, 300, 100),
        PortfolioStore(":memory:"),
    )
    rule = AlertRule(1, "AAPL", "PRICE", ">", 190)
    alerts = AlertsWorkspace(AlertsLoad((AlertEvaluation(rule, quote, 200, True),), now), AlertStore(":memory:"))

    for widget in (audit, watchlist, portfolio, alerts):
        table = widget.findChild(QTableWidget)
        assert table is not None
        assert table.columnCount() >= 8
        widget.close()
    app.processEvents()


def test_desktop_marks_clean_shutdown_and_persists_last_route(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=True, settings=settings)
    window.current_symbol = "MSFT"
    window.current_route = DesktopRoute("price", "MSFT", "1Y", "1d", "MSFT GP 1Y")
    window._history = [DesktopRoute("home", "", raw="HOME"), window.current_route]
    window._history_index = 1
    window.close()
    app.processEvents()

    assert settings.value("session/clean_shutdown", False, type=bool)
    assert settings.value("session/last_command") == "MSFT GP 1Y"
    assert settings.value("session/current_symbol") == "MSFT"


def test_evt_toolbar_uses_the_active_security_context(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "evt-toolbar.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    commands: list[str] = []
    window.execute_text = commands.append  # type: ignore[method-assign]
    evt_button = next(button for button in window.findChildren(QPushButton) if button.text() == "EVT")

    evt_button.click()
    app.processEvents()

    assert commands == ["EVT"]
    window.close()


def test_evt_global_calendar_pages_the_real_equity_universe(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    captured: list[str] = []

    async def equity_page(_provider, offset=0, limit=20, **filters):
        assert (offset, limit) == (20, 20)
        assert filters == {
            "minimum_market_cap": 0.0,
            "maximum_market_cap": None,
            "industry": "",
            "exchanges": ("NMS", "NYQ", "ASE"),
        }
        return [f"TEST{index:02d}" for index in range(20, 40)], 55

    async def no_events(_service, symbols, days=7):
        captured.extend(symbols)
        return []

    monkeypatch.setattr("ajax_terminal.providers.yahoo.YahooProvider.equity_universe_page", equity_page)
    monkeypatch.setattr("ajax_terminal.services.equity_research_service.EquityResearchService.event_schedule", no_events)

    calendar = load_event_calendar(30, page=2)

    assert calendar.universe == "ALL EQUITIES / LARGEST FIRST / ALL INDUSTRIES / US LISTED"
    assert calendar.page == 2
    assert calendar.total_symbols == 55
    assert len(calendar.symbols) == 20
    assert tuple(captured) == calendar.symbols


def test_evt_calendar_menu_lists_each_watchlist_and_portfolio() -> None:
    app = _app()
    model = EventCalendarLoad(
        (),
        ("AAPL",),
        30,
        "WATCHLIST / TECH STOCKS",
        "WATCHLIST",
        "TECH STOCKS",
        1,
        20,
        1,
        ("DEFAULT", "TECH STOCKS"),
        ("MAIN", "RETIREMENT"),
    )
    workspace = EventCalendarWorkspace(model)
    labels = [workspace.universe.itemText(index) for index in range(workspace.universe.count())]

    assert labels == [
        "ALL EQUITIES",
        "WATCHLIST  DEFAULT",
        "WATCHLIST  TECH STOCKS",
        "PORTFOLIO  MAIN",
        "PORTFOLIO  RETIREMENT",
    ]
    assert workspace.universe.currentText() == "WATCHLIST  TECH STOCKS"
    assert workspace.table.rowCount() == 1
    assert workspace.table.item(0, 1).text() == "AAPL"
    assert workspace.table.item(0, 3).text() == "NO EVENT IN WINDOW"
    workspace.close()
    app.processEvents()


def test_evt_calendar_filters_emit_a_paged_global_query() -> None:
    app = _app()
    model = EventCalendarLoad(
        events=(),
        symbols=("AAPL", "MSFT"),
        days=30,
        universe="ALL EQUITIES / LARGEST FIRST / ALL INDUSTRIES / US LISTED",
        total_symbols=100,
    )
    workspace = EventCalendarWorkspace(model)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)

    assert workspace.market_cap.currentData() == "LARGEST"
    assert workspace.industry.currentData() == "ALL"
    assert workspace.geography.currentData() == "US_LISTED"

    workspace.market_cap.setCurrentIndex(workspace.market_cap.findData("MEGA"))
    workspace.industry.setCurrentIndex(workspace.industry.findData("SEMICONDUCTORS"))
    workspace.geography.setCurrentIndex(workspace.geography.findData("NORTH_AMERICA"))
    app.processEvents()

    assert commands[-1] == (
        "EVT ALL 30 1 MCAP:MEGA IND:SEMICONDUCTORS GEO:NORTH_AMERICA"
    )
    workspace.close()
    app.processEvents()
