from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget

from ajax_terminal.desktop_app import AjaxDesktopWindow
from ajax_terminal.equity_research_desktop import RelativeValuationWorkspace, ScreenerWorkspace
from ajax_terminal.models.equity import PeerCompany, RelativeValuation, ScreenerPage, ScreenerResult
from ajax_terminal.models.quote import DataQuality


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_relative_valuation_uses_real_columns_and_aggregate_rows() -> None:
    _app()
    valuation = RelativeValuation(
        symbol="KRI.AT",
        peers=[
            PeerCompany("KRI.AT", "Kri-Kri Milk", price=18.2, pe=14.0, quality=DataQuality.DELAYED),
            PeerCompany("BN.PA", "Danone", price=63.5, pe=19.0, quality=DataQuality.DELAYED),
        ],
        automatic=True,
        provider="Yahoo Finance",
        quality=DataQuality.DELAYED,
        peer_sector="Consumer Defensive",
        peer_industry="Packaged Foods",
    )

    workspace = RelativeValuationWorkspace(valuation)
    table = workspace.findChild(QTableWidget)

    assert table is not None
    assert table.columnCount() == 12
    assert table.rowCount() == 4
    assert table.horizontalHeaderItem(0).text() == "SYMBOL"
    assert table.horizontalHeaderItem(1).text() == "COMPANY"
    assert table.item(0, 0).text() == "KRI.AT"
    assert {table.item(row, 0).text() for row in (2, 3)} == {"MEAN", "MEDIAN"}
    assert table.showGrid()


def test_screener_sorts_without_qt_item_subclasses_and_opens_visible_result() -> None:
    app = _app()
    page = ScreenerPage(
        filters=[],
        results=[
            ScreenerResult("SMALL", "Small Co", market_cap=2_000_000),
            ScreenerResult("LARGE", "Large Co", market_cap=90_000_000_000),
            ScreenerResult("EMPTY", "No Market Cap"),
        ],
        universe="TEST",
    )
    workspace = ScreenerWorkspace(page)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    workspace.show()
    app.processEvents()

    workspace._sort_by_column(6)
    assert [workspace.table.item(row, 0).text() for row in range(3)] == ["SMALL", "LARGE", "EMPTY"]

    workspace._sort_by_column(6)
    assert [workspace.table.item(row, 0).text() for row in range(3)] == ["LARGE", "SMALL", "EMPTY"]
    workspace._open_result(0, 0)
    assert commands == ["LARGE DES"]

    workspace.close()
    app.processEvents()


def test_workspace_loaders_survive_fast_route_changes() -> None:
    app = _app()
    window = AjaxDesktopWindow(require_login=False)
    mounted: list[str] = []

    def delayed(value: str, seconds: float) -> str:
        time.sleep(seconds)
        return value

    window._load_workspace("FIRST", lambda: delayed("first", 0.12), mounted.append)
    first = window._loader
    window._load_workspace("SECOND", lambda: delayed("second", 0.02), mounted.append)
    second = window._loader

    assert first is not None and second is not None
    assert first in window._workspace_loaders
    assert second in window._workspace_loaders

    deadline = time.monotonic() + 2.0
    while window._workspace_loaders and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert not window._workspace_loaders
    assert mounted == ["second"]
    window.close()
    app.processEvents()
