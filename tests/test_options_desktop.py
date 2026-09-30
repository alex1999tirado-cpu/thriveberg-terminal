from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from ajax_terminal.models.options import OptionChain, OptionContract, OptionMarketContext
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.options_desktop import OptionsDesktopLoad, OptionsDesktopWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _chain() -> OptionChain:
    expiry = date.today() + timedelta(days=180)
    call = OptionContract(
        "AAPL-C",
        "call",
        200.0,
        expiry,
        bid=12.0,
        ask=12.4,
        last=12.2,
        volume=120,
        open_interest=400,
        vendor_implied_volatility=0.24,
        delta=0.55,
    )
    put = OptionContract(
        "AAPL-P",
        "put",
        200.0,
        expiry,
        bid=9.0,
        ask=9.4,
        last=9.2,
        volume=80,
        open_interest=350,
        vendor_implied_volatility=0.25,
        delta=-0.45,
    )
    return OptionChain(
        "AAPL",
        "Apple Inc.",
        205.0,
        "USD",
        [expiry],
        expiry,
        [call],
        [put],
        "Yahoo Finance",
        DataQuality.DELAYED,
    )


def test_option_monitor_has_real_columns_and_all_function_tabs() -> None:
    app = _app()
    loaded = OptionsDesktopLoad("OMON", [_chain()], OptionMarketContext(0.04, 0.005, "TEST", "TEST"))
    workspace = OptionsDesktopWorkspace(loaded)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    workspace.show()
    app.processEvents()

    table = workspace.findChild(QTableWidget, "optionChainTable")
    assert table is not None
    assert table.columnCount() == 15
    assert table.rowCount() == 1
    assert table.horizontalHeaderItem(7).text() == "STRIKE"
    buttons = {button.text(): button for button in workspace.findChildren(QPushButton)}
    buttons["3) OVDV  VOLATILITY"].click()
    assert commands[-1] == "OVDV AAPL"
    workspace.close()


def test_option_valuation_calculates_price_and_greeks() -> None:
    _app()
    loaded = OptionsDesktopLoad(
        "OVME",
        [_chain()],
        OptionMarketContext(0.04, 0.005, "TEST CURVE", "TEST DIVIDEND"),
        "call",
        200.0,
    )
    workspace = OptionsDesktopWorkspace(loaded)
    tables = workspace.findChildren(QTableWidget)
    result = next(table for table in tables if table.horizontalHeaderItem(0).text() == "MEASURE")

    assert result.rowCount() == 12
    assert result.item(0, 0).text() == "MODEL PRICE"
    assert float(result.item(0, 1).text().replace(",", "")) > 0
