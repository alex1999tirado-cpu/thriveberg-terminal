from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ajax_terminal.desktop_app import AjaxDesktopWindow
from ajax_terminal.markets_desktop import (
    MarketGroup,
    MarketMonitorLoad,
    MarketMonitorWorkspace,
    build_market_movers_option,
)
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import DataQuality, Quote


NOW = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)


def _quote(
    symbol: str,
    change_percent: float | None,
    *,
    asset_class: str = "INDEX",
    quality: DataQuality = DataQuality.DELAYED,
) -> Quote:
    return Quote(
        symbol=symbol,
        name=f"{symbol} TEST",
        price=100.0 if quality != DataQuality.UNAVAILABLE else None,
        change=change_percent,
        change_percent=change_percent,
        currency="USD",
        asset_class=asset_class,
        provider="TEST PROVIDER",
        quality=quality,
        timestamp=NOW,
    )


def _model() -> MarketMonitorLoad:
    return MarketMonitorLoad(
        groups=(
            MarketGroup("GLOBAL EQUITIES", (_quote("SPX", 1.2), _quote("NDX", -0.8))),
            MarketGroup("FX", (_quote("EURUSD", 0.3, asset_class="FX"),)),
            MarketGroup("RATES", (_quote("US10Y", 2.0, asset_class="RATE"),)),
            MarketGroup(
                "COMMODITIES",
                (
                    _quote("BRENT", -1.8, asset_class="COMMODITY"),
                    _quote("SILVER", None, quality=DataQuality.UNAVAILABLE),
                ),
            ),
        ),
        events=(),
        news=(
            NewsItem(
                timestamp=NOW,
                source="TEST WIRE",
                headline="Markets move after policy decision",
                link="https://example.com/story",
                summary="A verified market summary.",
                provider="TEST",
                quality=DataQuality.DELAYED,
            ),
        ),
        loaded_at=NOW,
    )


def test_market_monitor_excludes_mock_and_unavailable_from_coverage() -> None:
    model = _model()

    assert {quote.symbol for quote in model.available} == {"SPX", "NDX", "EURUSD", "US10Y", "BRENT"}


def test_movers_chart_uses_only_comparable_price_assets() -> None:
    option = build_market_movers_option(_model())
    names = {item["name"] for item in option["series"][0]["data"]}

    assert option["series"][0]["type"] == "bar"
    assert names == {"SPX", "NDX", "EURUSD", "BRENT"}
    assert "US10Y" not in names
    assert "SILVER" not in names


def test_market_matrix_double_click_opens_native_chart() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = MarketMonitorWorkspace(_model())
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    try:
        row = workspace._row_by_symbol["SPX"]
        workspace._open_matrix_row(row, 0)
        assert commands == ["GP SPX 1Y 1D"]
    finally:
        workspace.close()
        app.processEvents()


def test_market_monitor_compacts_to_the_essential_columns() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = MarketMonitorWorkspace(_model())
    workspace.resize(900, 500)
    workspace.show()
    app.processEvents()
    try:
        assert workspace.visual_column.isHidden()
        assert workspace.lower.isHidden()
        assert workspace.table.isColumnHidden(1)
        assert workspace.table.isColumnHidden(3)
        assert not workspace.table.isColumnHidden(8)
    finally:
        workspace.close()
        app.processEvents()


def test_market_news_click_previews_and_double_click_opens_once(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(
        "ajax_terminal.markets_desktop.open_external_url",
        lambda url: opened.append(str(url)) or True,
    )
    workspace = MarketMonitorWorkspace(_model())
    try:
        workspace._story_clicked(0, 2)
        assert opened == []
        assert "verified market summary" in workspace.news_preview.text().lower()

        workspace._open_story(0, 2)
        workspace._open_story(0, 2)
        assert opened == ["https://example.com/story"]
    finally:
        workspace.close()
        app.processEvents()


def test_desktop_mounts_home_as_native_market_monitor(monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "markets.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    monkeypatch.setattr(window, "_load_workspace", lambda _engine, _loader, mount: mount(_model()))
    try:
        window.execute_text("MARKETS")
        app.processEvents()
        assert isinstance(window.stack.currentWidget(), MarketMonitorWorkspace)
        assert "NATIVE QT" in window.engine_label.text()
    finally:
        window.close()
