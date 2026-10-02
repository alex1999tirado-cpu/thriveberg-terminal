from __future__ import annotations

import sys
import urllib.parse
from datetime import date
from math import ceil
from pathlib import Path

from PySide6.QtCore import QByteArray, QProcess, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.charts.theme import (
    AJAX_AMBER,
    AJAX_CYAN,
    AJAX_GREEN,
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
)
from ajax_terminal.desktop_security import open_external_url, open_local_path
from ajax_terminal.services.workstation_service import (
    AlertsLoad,
    BetaRelease,
    DataAuditLoad,
    EVENT_GEOGRAPHY_FILTERS,
    EVENT_INDUSTRY_FILTERS,
    EVENT_MARKET_CAP_FILTERS,
    EventCalendarLoad,
    PortfolioLoad,
    WatchlistLoad,
)
from ajax_terminal.services.portfolio_import_service import (
    BrokerImportPreview,
    apply_broker_import,
    preview_broker_csv,
)
from ajax_terminal.storage.cache import WatchlistStore
from ajax_terminal.storage.workstation import (
    AlertStore,
    PortfolioStore,
    WorkspaceSnapshot,
    WorkspaceStore,
)
from ajax_terminal.utils.formatting import fmt_number, fmt_percent, fmt_timestamp


class DataAuditWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: DataAuditLoad) -> None:
        super().__init__()
        self.model = model
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("FLDS  DATA AUDIT", AJAX_CYAN, bold=True))
        self.search = QLineEdit(model.field_filter)
        self.search.setPlaceholderText("FIELD FILTER: PRICE, REVENUE, CASH...")
        self.search.returnPressed.connect(self._filter)
        row.addWidget(self.search, 1)
        row.addWidget(_button("APPLY", self._filter, amber=True))
        row.addWidget(_button("REFRESH", self._refresh))
        root.addWidget(controls)
        root.addWidget(_heading(f"FLDS  {model.symbol}  FIELD PROVENANCE"))
        root.addWidget(
            _subheading(
                "DOUBLE-CLICK A ROW TO OPEN ITS PRIMARY SOURCE  |  "
                "OBSERVED, FILED, DERIVED AND ESTIMATED VALUES ARE LABELLED EXPLICITLY"
            )
        )
        self.action_status = _label("LEDGER READY", AJAX_MUTED)
        root.addWidget(self.action_status)
        self.table = _table(("FIELD", "VALUE", "UNIT", "SOURCE", "QUALITY", "AS OF", "BASIS", "DOCUMENT"))
        self.table.setRowCount(max(len(model.entries), 1))
        if model.entries:
            for table_row, entry in enumerate(model.entries):
                values = (
                    entry.field,
                    entry.value,
                    entry.unit or "--",
                    entry.provider,
                    str(entry.quality),
                    fmt_timestamp(entry.timestamp),
                    entry.basis,
                    "OPEN" if entry.source_url else "--",
                )
                for column, value in enumerate(values):
                    color = AJAX_AMBER if column in {1, 7} else AJAX_TEXT
                    item = _item(value, color=color, right=column == 1)
                    item.setData(Qt.ItemDataRole.UserRole, entry.source_url)
                    self.table.setItem(table_row, column, item)
        else:
            self.table.setItem(0, 0, _item("NO FIELDS MATCH THE CURRENT FILTER", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_source)
        root.addWidget(self.table, 1)

    @Slot()
    def _filter(self) -> None:
        suffix = " ".join(self.search.text().strip().upper().split())
        self.command_requested.emit(f"{self.model.symbol} FLDS {suffix}".strip())

    @Slot()
    def _refresh(self) -> None:
        self.command_requested.emit(f"{self.model.symbol} FLDS {self.model.field_filter}".strip())

    @Slot(int, int)
    def _open_source(self, row: int, column: int) -> None:
        item = self.table.item(row, column)
        url = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            open_external_url(url)


class WatchlistWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: WatchlistLoad, store: WatchlistStore | None = None) -> None:
        super().__init__()
        self.model = model
        self.store = store or WatchlistStore()
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("WATC", AJAX_CYAN, bold=True))
        self.list_selector = QComboBox()
        self.list_selector.setObjectName("amberField")
        self.list_selector.addItems(model.names)
        self.list_selector.setCurrentText(model.name)
        self.list_selector.currentTextChanged.connect(self._switch)
        row.addWidget(self.list_selector)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("NEW LIST NAME")
        self.new_name.setMaximumWidth(190)
        row.addWidget(self.new_name)
        row.addWidget(_button("NEW", self._create))
        row.addWidget(_button("DELETE LIST", self._delete_list))
        row.addSpacing(12)
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText("SYMBOL")
        self.symbol.setMaximumWidth(130)
        self.symbol.returnPressed.connect(self._add)
        row.addWidget(self.symbol)
        row.addWidget(_button("ADD", self._add, amber=True))
        row.addWidget(_button("REMOVE", self._remove))
        row.addWidget(_button("UP", lambda: self._move(-1)))
        row.addWidget(_button("DOWN", lambda: self._move(1)))
        row.addWidget(_button("REFRESH", self._refresh))
        root.addWidget(controls)
        root.addWidget(_heading(f"WATC  {model.name}  EDITABLE WATCHLIST"))
        self.table = _table(("#", "SECURITY", "NAME", "LAST", "CHG", "CHG %", "BID", "ASK", "VOLUME", "SOURCE", "DATA"))
        self.table.setRowCount(max(len(model.quotes), 1))
        if model.quotes:
            for table_row, quote in enumerate(model.quotes):
                values = (
                    str(table_row + 1), quote.symbol, quote.name, fmt_number(quote.price, 4),
                    _signed(quote.change, 4), _percent(quote.change_percent), fmt_number(quote.bid, 4),
                    fmt_number(quote.ask, 4), fmt_number(quote.volume, 0), quote.provider, str(quote.quality),
                )
                for column, value in enumerate(values):
                    color = _change_color(quote.change_percent) if column in {4, 5} else AJAX_AMBER if column == 3 else AJAX_TEXT
                    self.table.setItem(table_row, column, _item(value, color=color, right=column in {0, 3, 4, 5, 6, 7, 8}))
        else:
            self.table.setItem(0, 0, _item("WATCHLIST IS EMPTY", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_security)
        root.addWidget(self.table, 1)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

    def _selected_symbol(self) -> str:
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        return item.text() if item is not None else ""

    @Slot(str)
    def _switch(self, name: str) -> None:
        if name and name != self.model.name:
            self.command_requested.emit(f"WATC {name}")

    @Slot()
    def _create(self) -> None:
        if self.new_name.text().strip():
            name = self.store.create(self.new_name.text())
            self.command_requested.emit(f"WATC {name}")

    @Slot()
    def _delete_list(self) -> None:
        self.store.delete(self.model.name)
        self.command_requested.emit("WATC DEFAULT")

    @Slot()
    def _add(self) -> None:
        symbol = self.symbol.text().strip().upper()
        if symbol:
            self.store.add(symbol, self.model.name)
            self.command_requested.emit(f"WATC {self.model.name}")

    @Slot()
    def _remove(self) -> None:
        symbol = self._selected_symbol()
        if symbol:
            self.store.remove(symbol, self.model.name)
            self.command_requested.emit(f"WATC {self.model.name}")

    def _move(self, offset: int) -> None:
        symbol = self._selected_symbol()
        if symbol:
            self.store.move(symbol, offset, self.model.name)
            self.command_requested.emit(f"WATC {self.model.name}")

    @Slot()
    def _refresh(self) -> None:
        self.command_requested.emit(f"WATC {self.model.name}")

    @Slot(int, int)
    def _open_security(self, row: int, _column: int) -> None:
        item = self.table.item(row, 1)
        if item is not None:
            self.command_requested.emit(f"{item.text()} DES")


class PortfolioWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: PortfolioLoad, store: PortfolioStore | None = None) -> None:
        super().__init__()
        self.model = model
        self.store = store or PortfolioStore()
        self._import_preview: BrokerImportPreview | None = None
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("PORT  PORTFOLIO ACCOUNTING", AJAX_CYAN, bold=True))
        self.selector = QComboBox()
        self.selector.setObjectName("amberField")
        self.selector.addItems(model.names)
        self.selector.setCurrentText(model.name)
        self.selector.currentTextChanged.connect(self._switch)
        row.addWidget(self.selector)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("NEW PORTFOLIO")
        self.new_name.setMaximumWidth(170)
        row.addWidget(self.new_name)
        self.new_base = QComboBox()
        self.new_base.setObjectName("amberField")
        self.new_base.addItems(("USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD"))
        self.new_base.setCurrentText(model.base_currency)
        row.addWidget(self.new_base)
        row.addWidget(_button("NEW", self._create))
        row.addWidget(_button("IMPORT CSV", self._choose_import, amber=True))
        row.addWidget(_button("REMOVE", self._remove))
        row.addWidget(_button("REFRESH", self._refresh))
        row.addStretch(1)
        row.addWidget(_label(f"BASE {model.base_currency}", AJAX_AMBER, bold=True))
        root.addWidget(controls)
        pnl_color = _change_color(model.profit_loss)
        title = QLabel(
            f"PORT  {model.name}  |  NAV  {model.net_asset_value:,.2f} {model.base_currency}  |  "
            f"SECURITIES  {model.market_value:,.2f}  |  CASH  {model.cash_balance:+,.2f}  |  "
            f"<span style='color:{pnl_color}'>TOTAL P&L {model.profit_loss:+,.2f}  "
            f"({_percent(model.total_return_percent)})</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        root.addWidget(
            _subheading(
                f"REALIZED {_signed(model.realized_pnl, 2)}  |  "
                f"UNREALIZED {_signed(model.unrealized_pnl, 2)}  |  "
                f"INCOME {_signed(model.income, 2)}  |  FEES {model.fees:,.2f}  |  "
                f"CASH EXP. {_signed(model.cash_expenses, 2)}  |  "
                f"NET FLOWS {_signed(model.net_external_flow, 2)}  |  "
                f"INVESTED CAPITAL {model.invested_capital:,.2f} {model.base_currency}"
            )
        )
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.table = self._holdings_table()
        self.attribution_table = self._attribution_table()
        transaction_page, self.transaction_table = self._transaction_page()
        cash_page, self.cash_table = self._cash_page()
        import_page, self.import_table = self._import_page()
        self.tabs.addTab(self.table, "1) HOLDINGS")
        self.tabs.addTab(self.attribution_table, "2) ATTRIBUTION")
        self.tabs.addTab(transaction_page, "3) TRANSACTIONS")
        self.tabs.addTab(cash_page, "4) CASH LEDGER")
        self.tabs.addTab(import_page, "5) IMPORT PREVIEW")
        root.addWidget(self.tabs, 1)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

    def _holdings_table(self) -> QTableWidget:
        table = _table(
            (
                "SECURITY",
                "NAME",
                "QTY",
                "AVG COST",
                "LAST",
                "NATIVE VALUE",
                f"MARKET VALUE {self.model.base_currency}",
                f"BOOK {self.model.base_currency}",
                "P&L",
                "P&L %",
                "WEIGHT",
                "FX TO BASE",
                "CCY",
                "SOURCE",
                "DATA",
            )
        )
        table.setRowCount(max(len(self.model.lines), 1))
        if self.model.lines:
            for table_row, line in enumerate(self.model.lines):
                values = (
                    line.position.symbol,
                    line.quote.name,
                    fmt_number(line.position.quantity, 4),
                    fmt_number(line.position.cost_basis, 4),
                    fmt_number(line.quote.price, 4),
                    fmt_number(line.native_market_value, 2),
                    fmt_number(line.market_value, 2),
                    fmt_number(line.book_value, 2),
                    _signed(line.profit_loss, 2),
                    _percent(line.profit_loss_percent),
                    _percent(line.weight_percent),
                    fmt_number(line.fx_rate, 6),
                    line.position.currency or line.quote.currency or self.model.base_currency,
                    line.quote.provider,
                    str(line.quote.quality),
                )
                for column, value in enumerate(values):
                    color = (
                        _change_color(line.profit_loss)
                        if column in {8, 9}
                        else AJAX_AMBER
                        if column in {4, 5, 6}
                        else AJAX_TEXT
                    )
                    table.setItem(
                        table_row,
                        column,
                        _item(value, color=color, right=column in {2, 3, 4, 5, 6, 7, 8, 9, 10, 11}),
                    )
        else:
            table.setItem(0, 0, _item("PORTFOLIO IS EMPTY", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.cellDoubleClicked.connect(self._open_security)
        return table

    def _attribution_table(self) -> QTableWidget:
        table = _table(
            (
                "SECURITY",
                "MARKET VALUE",
                "WEIGHT",
                "UNREALIZED",
                "REALIZED",
                "INCOME",
                "CASH EXPENSES",
                "FEES PAID",
                "TOTAL P&L",
                "CONTRIBUTION BP",
            )
        )
        table.setRowCount(max(len(self.model.attribution), 1))
        if self.model.attribution:
            for row, item in enumerate(self.model.attribution):
                values = (
                    item.symbol,
                    fmt_number(item.market_value, 2),
                    _percent(item.weight_percent),
                    _signed(item.unrealized_pnl, 2),
                    _signed(item.realized_pnl, 2),
                    _signed(item.income, 2),
                    _signed(item.cash_expenses, 2),
                    fmt_number(item.fees, 2),
                    _signed(item.total_pnl, 2),
                    f"{item.contribution_bp:+,.1f}" if item.contribution_bp is not None else "--",
                )
                for column, value in enumerate(values):
                    color = _change_color(item.total_pnl) if column in {3, 4, 5, 6, 8, 9} else AJAX_TEXT
                    table.setItem(row, column, _item(value, color=color, right=column > 0))
        else:
            table.setItem(0, 0, _item("NO PERFORMANCE ATTRIBUTION YET", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _transaction_page(self) -> tuple[QWidget, QTableWidget]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        controls = _strip()
        row = controls.layout()
        self.trade_side = QComboBox()
        self.trade_side.addItems(("BUY", "SELL"))
        self.trade_date = _input("YYYY-MM-DD", 105)
        self.trade_date.setText(date.today().isoformat())
        self.symbol = _input("SYMBOL", 105)
        self.quantity = _input("QUANTITY", 95)
        self.cost = _input("PRICE", 95)
        self.trade_fees = _input("FEES", 75)
        self.trade_fees.setText("0")
        self.currency = _input(self.model.base_currency, 65)
        self.currency.setText(self.model.base_currency)
        self.trade_fx = _input("FX", 75)
        self.trade_fx.setText("1")
        for widget in (
            self.trade_side,
            self.trade_date,
            self.symbol,
            self.quantity,
            self.cost,
            self.trade_fees,
            self.currency,
            self.trade_fx,
        ):
            row.addWidget(widget)
        row.addWidget(_button("BOOK TRADE", self._book_trade, amber=True))
        row.addStretch(1)
        layout.addWidget(controls)
        table = _table(
            (
                "DATE",
                "SIDE",
                "SECURITY",
                "QTY",
                "PRICE",
                "FEES",
                "CCY",
                "FX",
                f"REALIZED {self.model.base_currency}",
                "SOURCE",
                "REFERENCE",
            )
        )
        table.setRowCount(max(len(self.model.transactions), 1))
        if self.model.transactions:
            for table_row, transaction in enumerate(self.model.transactions):
                values = (
                    transaction.trade_date,
                    transaction.side,
                    transaction.symbol,
                    fmt_number(transaction.quantity, 4),
                    fmt_number(transaction.price, 4),
                    fmt_number(transaction.fees, 2),
                    transaction.currency,
                    fmt_number(transaction.fx_rate, 6),
                    _signed(transaction.realized_pnl, 2),
                    transaction.source,
                    transaction.external_id,
                )
                for column, value in enumerate(values):
                    color = (
                        AJAX_GREEN
                        if column == 1 and transaction.side == "BUY"
                        else AJAX_RED
                        if column == 1
                        else _change_color(transaction.realized_pnl)
                        if column == 8
                        else AJAX_TEXT
                    )
                    table.setItem(table_row, column, _item(value, color=color, right=column in {3, 4, 5, 7, 8}))
        else:
            table.setItem(0, 0, _item("NO BOOKED TRANSACTIONS", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        return page, table

    def _cash_page(self) -> tuple[QWidget, QTableWidget]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        controls = _strip()
        row = controls.layout()
        self.cash_kind = QComboBox()
        self.cash_kind.addItems(("DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "TAX", "FEE"))
        self.cash_date = _input("YYYY-MM-DD", 105)
        self.cash_date.setText(date.today().isoformat())
        self.cash_amount = _input("AMOUNT", 110)
        self.cash_currency = _input(self.model.base_currency, 65)
        self.cash_currency.setText(self.model.base_currency)
        self.cash_fx = _input("FX", 75)
        self.cash_fx.setText("1")
        self.cash_symbol = _input("SYMBOL (OPTIONAL)", 145)
        for widget in (
            self.cash_kind,
            self.cash_date,
            self.cash_amount,
            self.cash_currency,
            self.cash_fx,
            self.cash_symbol,
        ):
            row.addWidget(widget)
        row.addWidget(_button("BOOK CASH FLOW", self._book_cash, amber=True))
        row.addStretch(1)
        layout.addWidget(controls)
        table = _table(("DATE", "TYPE", "AMOUNT", "CCY", "FX", "BASE AMOUNT", "SECURITY", "SOURCE", "REFERENCE"))
        table.setRowCount(max(len(self.model.cash_flows), 1))
        if self.model.cash_flows:
            for table_row, cash_flow in enumerate(self.model.cash_flows):
                values = (
                    cash_flow.flow_date,
                    cash_flow.kind,
                    _signed(cash_flow.amount, 2),
                    cash_flow.currency,
                    fmt_number(cash_flow.fx_rate, 6),
                    _signed(cash_flow.amount * cash_flow.fx_rate, 2),
                    cash_flow.symbol or "--",
                    cash_flow.source,
                    cash_flow.external_id,
                )
                for column, value in enumerate(values):
                    color = _change_color(cash_flow.amount) if column in {1, 2, 5} else AJAX_TEXT
                    table.setItem(table_row, column, _item(value, color=color, right=column in {2, 4, 5}))
        else:
            table.setItem(0, 0, _item("NO CASH FLOWS", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        return page, table

    def _import_page(self) -> tuple[QWidget, QTableWidget]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        controls = _strip()
        row = controls.layout()
        self.import_status = _label("SELECT IMPORT CSV TO PREVIEW", AJAX_MUTED)
        row.addWidget(self.import_status, 1)
        self.apply_import_button = _button("APPLY IMPORT", self._apply_import, amber=True)
        self.apply_import_button.setEnabled(False)
        row.addWidget(self.apply_import_button)
        layout.addWidget(controls)
        table = _table(("ROW", "STATUS", "DATE", "TYPE", "ACTION", "SECURITY", "QTY", "PRICE / AMOUNT", "FEES", "CCY", "FX", "MESSAGE"))
        table.setRowCount(1)
        table.setItem(0, 0, _item("NO FILE SELECTED", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        return page, table

    def _set_import_preview(self, preview: BrokerImportPreview) -> None:
        self._import_preview = preview
        self.import_status.setText(
            f"{preview.broker}  |  {preview.path.name}  |  "
            f"READY {preview.ready_count}  |  ERRORS {preview.error_count}"
        )
        self.import_status.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold;padding:0 5px")
        self.apply_import_button.setEnabled(preview.ready_count > 0)
        self.import_table.clearContents()
        self.import_table.setRowCount(max(len(preview.rows), 1))
        for table_row, item in enumerate(preview.rows):
            price_or_amount = item.price if item.entry_type == "TRADE" else item.amount
            values = (
                item.row_number,
                item.status,
                item.entry_date,
                item.entry_type,
                item.action,
                item.symbol or "--",
                fmt_number(item.quantity, 4),
                fmt_number(price_or_amount, 4),
                fmt_number(item.fees, 2),
                item.currency,
                fmt_number(item.fx_rate, 6),
                item.message or "--",
            )
            for column, value in enumerate(values):
                color = AJAX_GREEN if column == 1 and item.valid else AJAX_RED if column == 1 else AJAX_TEXT
                self.import_table.setItem(
                    table_row,
                    column,
                    _item(value, color=color, right=column in {0, 6, 7, 8, 10}),
                )
        self.tabs.setCurrentIndex(4)

    def _selected_symbol(self) -> str:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else ""

    @Slot(str)
    def _switch(self, name: str) -> None:
        if name and name != self.model.name:
            self.command_requested.emit(f"PORT {name}")

    @Slot()
    def _create(self) -> None:
        if self.new_name.text().strip():
            name = self.store.create(self.new_name.text(), self.new_base.currentText())
            self.command_requested.emit(f"PORT {name}")

    @Slot()
    def _book_trade(self) -> None:
        try:
            self.store.record_trade(
                self.symbol.text(),
                self.trade_side.currentText(),
                float(self.quantity.text()),
                float(self.cost.text()),
                fees=float(self.trade_fees.text() or 0),
                currency=self.currency.text(),
                fx_rate=float(self.trade_fx.text() or 1),
                trade_date=self.trade_date.text(),
                name=self.model.name,
            )
        except (TypeError, ValueError) as exc:
            self._show_action_error("TRADE REJECTED", exc)
            return
        self.command_requested.emit(f"PORT {self.model.name}")

    @Slot()
    def _book_cash(self) -> None:
        try:
            self.store.record_cash_flow(
                self.cash_kind.currentText(),
                float(self.cash_amount.text()),
                currency=self.cash_currency.text(),
                fx_rate=float(self.cash_fx.text() or 1),
                flow_date=self.cash_date.text(),
                symbol=self.cash_symbol.text(),
                name=self.model.name,
            )
        except (TypeError, ValueError) as exc:
            self._show_action_error("CASH FLOW REJECTED", exc)
            return
        self.command_requested.emit(f"PORT {self.model.name}")

    def _show_action_error(self, prefix: str, error: Exception) -> None:
        message = " ".join(str(error).split())[:180]
        self.action_status.setText(f"{prefix}  |  {message}")
        self.action_status.setStyleSheet(
            f"color:{AJAX_RED};font-weight:bold;padding:0 5px"
        )

    @Slot()
    def _choose_import(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Import broker activity",
            str(Path.home()),
            "Broker CSV (*.csv *.txt)",
        )
        if not filename:
            return
        try:
            preview = preview_broker_csv(filename, default_currency=self.model.base_currency)
        except (OSError, ValueError) as exc:
            self.import_status.setText(f"IMPORT ERROR  |  {' '.join(str(exc).split())[:180]}")
            self.import_status.setStyleSheet(f"color:{AJAX_RED};font-weight:bold;padding:0 5px")
            self.tabs.setCurrentIndex(4)
            return
        self._set_import_preview(preview)

    @Slot()
    def _apply_import(self) -> None:
        if self._import_preview is None:
            return
        result = apply_broker_import(self._import_preview, self.model.name, self.store)
        self.import_status.setText(
            f"IMPORT COMPLETE  |  ADDED {result.imported}  |  "
            f"DUPLICATES {result.duplicates}  |  FAILED {result.failed}"
        )
        self.import_status.setStyleSheet(
            f"color:{AJAX_GREEN if result.failed == 0 else AJAX_AMBER};font-weight:bold;padding:0 5px"
        )
        self.apply_import_button.setEnabled(False)
        if result.imported:
            self.command_requested.emit(f"PORT {self.model.name}")

    @Slot()
    def _remove(self) -> None:
        symbol = self._selected_symbol()
        if symbol:
            if self.store.has_transaction_history(symbol, self.model.name):
                self._show_action_error(
                    "REMOVE REJECTED",
                    ValueError("ledger-managed positions must be closed with a SELL trade"),
                )
                return
            self.store.remove(symbol, self.model.name)
            self.command_requested.emit(f"PORT {self.model.name}")

    @Slot()
    def _refresh(self) -> None:
        self.command_requested.emit(f"PORT {self.model.name}")

    @Slot(int, int)
    def _open_security(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.command_requested.emit(f"{item.text()} DES")


class AlertsWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: AlertsLoad, store: AlertStore | None = None) -> None:
        super().__init__()
        self.model = model
        self.store = store or AlertStore()
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("ALRT", AJAX_CYAN, bold=True))
        self.symbol = _input("SYMBOL", 110)
        self.field = QComboBox()
        self.field.addItems(("PRICE", "CHANGE_PCT", "VOLUME", "BID", "ASK"))
        self.operator = QComboBox()
        self.operator.addItems((">", ">=", "<", "<=", "="))
        self.threshold = _input("THRESHOLD", 115)
        for widget in (self.symbol, self.field, self.operator, self.threshold):
            row.addWidget(widget)
        row.addWidget(_button("ADD ALERT", self._add, amber=True))
        row.addWidget(_button("ENABLE / DISABLE", self._toggle))
        row.addWidget(_button("DELETE", self._delete))
        row.addWidget(_button("REFRESH", self._refresh))
        root.addWidget(controls)
        root.addWidget(_heading(f"ALRT  MARKET ALERTS  |  UPDATED {model.refreshed_at:%H:%M:%S %Z}  |  AUTO 30S"))
        self.table = _table(("ID", "STATUS", "SECURITY", "FIELD", "RULE", "CURRENT", "SOURCE", "DATA", "LAST TRIGGER"))
        self.table.setRowCount(max(len(model.evaluations), 1))
        if model.evaluations:
            for table_row, evaluation in enumerate(model.evaluations):
                rule = evaluation.rule
                status = "TRIGGERED" if evaluation.triggered else "ARMED" if rule.enabled else "DISABLED"
                values = (
                    str(rule.id or "--"), status, rule.symbol, rule.field,
                    f"{rule.operator} {rule.threshold:,.6g}", fmt_number(evaluation.value, 6),
                    evaluation.quote.provider, str(evaluation.quote.quality), rule.last_triggered_at or "--",
                )
                for column, value in enumerate(values):
                    color = AJAX_RED if evaluation.triggered and column == 1 else AJAX_GREEN if column == 1 and rule.enabled else AJAX_AMBER if column in {4, 5} else AJAX_TEXT
                    item = _item(value, color=color, right=column in {0, 4, 5})
                    item.setData(Qt.ItemDataRole.UserRole, rule.id)
                    self.table.setItem(table_row, column, item)
        else:
            self.table.setItem(0, 0, _item("NO ALERTS CONFIGURED", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_security)
        root.addWidget(self.table, 1)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

    def _selected(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        alert_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return next((entry for entry in self.model.evaluations if entry.rule.id == alert_id), None)

    @Slot()
    def _add(self) -> None:
        try:
            self.store.add(self.symbol.text(), self.field.currentText(), self.operator.currentText(), float(self.threshold.text()))
        except ValueError:
            return
        self.command_requested.emit("ALRT")

    @Slot()
    def _toggle(self) -> None:
        selected = self._selected()
        if selected is not None and selected.rule.id is not None:
            self.store.set_enabled(selected.rule.id, not selected.rule.enabled)
            self.command_requested.emit("ALRT")

    @Slot()
    def _delete(self) -> None:
        selected = self._selected()
        if selected is not None and selected.rule.id is not None:
            self.store.delete(selected.rule.id)
            self.command_requested.emit("ALRT")

    @Slot()
    def _refresh(self) -> None:
        self.command_requested.emit("ALRT")

    @Slot(int, int)
    def _open_security(self, row: int, _column: int) -> None:
        item = self.table.item(row, 2)
        if item is not None:
            self.command_requested.emit(f"{item.text()} DES")


class EventCalendarWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: EventCalendarLoad) -> None:
        super().__init__()
        self.model = model
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("EVT  CORPORATE CALENDAR", AJAX_CYAN, bold=True))
        self.universe = QComboBox()
        self.universe.setObjectName("eventUniverseSelector")
        self.universe.addItem("ALL EQUITIES", ("ALL", ""))
        for name in model.watchlists:
            self.universe.addItem(f"WATCHLIST  {name}", ("WATCHLIST", name))
        for name in model.portfolios:
            self.universe.addItem(f"PORTFOLIO  {name}", ("PORTFOLIO", name))
        for index in range(self.universe.count()):
            if self.universe.itemData(index) == (model.scope, model.selection):
                self.universe.setCurrentIndex(index)
                break
        self.universe.currentIndexChanged.connect(self._universe_changed)
        row.addWidget(self.universe)
        self.market_cap = QComboBox()
        self.market_cap.setObjectName("eventMarketCapFilter")
        for code, label, _minimum, _maximum in EVENT_MARKET_CAP_FILTERS:
            self.market_cap.addItem(f"MCAP  {label}", code)
        self._select_combo(self.market_cap, model.market_cap_filter)
        self.market_cap.setEnabled(model.scope == "ALL")
        row.addWidget(self.market_cap)
        self.industry = QComboBox()
        self.industry.setObjectName("eventIndustryFilter")
        for code, label, _query in EVENT_INDUSTRY_FILTERS:
            self.industry.addItem(f"IND  {label}", code)
        self._select_combo(self.industry, model.industry_filter)
        self.industry.setEnabled(model.scope == "ALL")
        row.addWidget(self.industry)
        self.geography = QComboBox()
        self.geography.setObjectName("eventGeographyFilter")
        for code, label, _regions in EVENT_GEOGRAPHY_FILTERS:
            self.geography.addItem(f"REGION  {label}", code)
        self._select_combo(self.geography, model.geography_filter)
        self.geography.setEnabled(model.scope == "ALL")
        row.addWidget(self.geography)
        self.market_cap.currentIndexChanged.connect(self._filter_changed)
        self.industry.currentIndexChanged.connect(self._filter_changed)
        self.geography.currentIndexChanged.connect(self._filter_changed)
        for days in (7, 30, 90):
            button = _button(
                f"{days}D",
                lambda _checked=False, value=days: self._request(days=value, page=1),
            )
            button.setCheckable(True)
            button.setChecked(days == model.days)
            row.addWidget(button)
        row.addStretch(1)
        previous = _button("<", lambda: self._request(page=max(1, model.page - 1)))
        previous.setEnabled(model.page > 1)
        row.addWidget(previous)
        total_pages = max(1, ceil(model.total_symbols / model.page_size))
        row.addWidget(_label(f"PAGE {model.page:,} / {total_pages:,}", AJAX_TEXT, bold=True))
        following = _button(">", lambda: self._request(page=model.page + 1))
        following.setEnabled(model.page < total_pages)
        row.addWidget(following)
        row.addWidget(_button("REFRESH", lambda: self._request(), amber=True))
        root.addWidget(controls)
        root.addWidget(
            _heading(
                f"EVT  {model.days}-DAY CORPORATE CALENDAR  |  "
                f"{model.total_symbols:,} SECURITIES  |  {model.universe}"
            )
        )
        root.addWidget(_subheading("SCANNED PAGE: " + "  |  ".join(model.symbols)))
        self.table = _table(("DATE / TIME", "SECURITY", "COMPANY", "EVENT", "DETAIL", "STATUS", "SOURCE", "DATA"))
        event_symbols = {event.symbol.upper() for event in model.events}
        without_events = [symbol for symbol in model.symbols if symbol.upper() not in event_symbols]
        self.table.setRowCount(max(len(model.events) + len(without_events), 1))
        if model.events:
            for table_row, event in enumerate(model.events):
                values = (
                    event.event_date.strftime("%d %b %Y %H:%M"), event.symbol, event.company,
                    event.event_type, event.detail or "--", "ESTIMATE" if event.estimated else "CONFIRMED",
                    event.provider, str(event.quality),
                )
                for column, value in enumerate(values):
                    color = AJAX_AMBER if column in {0, 3} else AJAX_TEXT
                    self.table.setItem(table_row, column, _item(value, color=color))
        for offset, symbol in enumerate(without_events, start=len(model.events)):
            values = (
                "--",
                symbol,
                "--",
                "NO EVENT IN WINDOW",
                f"No corporate event returned for the next {model.days} days",
                "--",
                "YAHOO FINANCE",
                "N/A",
            )
            for column, value in enumerate(values):
                color = AJAX_TEXT if column == 1 else AJAX_MUTED
                self.table.setItem(offset, column, _item(value, color=color))
        if not model.symbols:
            self.table.setItem(
                0,
                0,
                _item(
                    f"NO EQUITIES IN THE SELECTED UNIVERSE  |  {model.universe}",
                    color=AJAX_MUTED,
                ),
            )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_security)
        root.addWidget(self.table, 1)

    def _request(self, *, days: int | None = None, page: int | None = None) -> None:
        self.command_requested.emit(
            self._command(
                self.model.scope,
                self.model.selection,
                days or self.model.days,
                page or self.model.page,
                self.model.market_cap_filter,
                self.model.industry_filter,
                self.model.geography_filter,
            )
        )

    @Slot(int)
    def _universe_changed(self, index: int) -> None:
        data = self.universe.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        scope, selection = data
        self.command_requested.emit(
            self._command(
                str(scope),
                str(selection),
                self.model.days,
                1,
                self.model.market_cap_filter,
                self.model.industry_filter,
                self.model.geography_filter,
            )
        )

    @Slot(int)
    def _filter_changed(self, _index: int) -> None:
        if self.model.scope != "ALL":
            return
        self.command_requested.emit(
            self._command(
                "ALL",
                "",
                self.model.days,
                1,
                str(self.market_cap.currentData()),
                str(self.industry.currentData()),
                str(self.geography.currentData()),
            )
        )

    @staticmethod
    def _command(
        scope: str,
        selection: str,
        days: int,
        page: int,
        market_cap: str,
        industry: str,
        geography: str,
    ) -> str:
        if scope == "WATCHLIST":
            target = "WATC:" + urllib.parse.quote(selection, safe="")
        elif scope == "PORTFOLIO":
            target = "PORT:" + urllib.parse.quote(selection, safe="")
        else:
            target = "ALL"
        return (
            f"EVT {target} {days} {page} "
            f"MCAP:{market_cap} IND:{industry} GEO:{geography}"
        )

    @staticmethod
    def _select_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @Slot(int, int)
    def _open_security(self, row: int, _column: int) -> None:
        item = self.table.item(row, 1)
        if item is not None:
            self.command_requested.emit(f"{item.text()} DES")


class WorkspaceManagerWorkspace(QWidget):
    command_requested = Signal(str)
    workspace_selected = Signal(object)

    def __init__(
        self,
        store: WorkspaceStore,
        current_command: str,
        current_symbol: str,
        history: tuple[str, ...],
        geometry_b64: str,
    ) -> None:
        super().__init__()
        self.store = store
        self.current_command = current_command
        self.current_symbol = current_symbol
        self.history = history
        self.geometry_b64 = geometry_b64
        self.snapshots = store.list()
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("WSP  WORKSPACES", AJAX_CYAN, bold=True))
        self.name = _input("WORKSPACE NAME", 230)
        row.addWidget(self.name)
        row.addWidget(_button("SAVE CURRENT", self._save, amber=True))
        row.addWidget(_button("OPEN", self._open))
        row.addWidget(_button("DELETE", self._delete))
        row.addStretch(1)
        root.addWidget(controls)
        root.addWidget(_heading("WSP  PERSISTENT WORKSPACES  |  ROUTE HISTORY + ACTIVE SECURITY + WINDOW LAYOUT"))
        self.table = _table(("NAME", "ACTIVE COMMAND", "SECURITY", "ROUTES", "UPDATED"))
        self.table.setRowCount(max(len(self.snapshots), 1))
        if self.snapshots:
            for row_index, snapshot in enumerate(self.snapshots):
                values = (
                    snapshot.name, snapshot.active_command, snapshot.current_symbol or "--",
                    str(len(snapshot.history)), snapshot.updated_at.replace("T", " ")[:19],
                )
                for column, value in enumerate(values):
                    item = _item(value, color=AJAX_AMBER if column == 0 else AJAX_TEXT)
                    item.setData(Qt.ItemDataRole.UserRole, snapshot.name)
                    self.table.setItem(row_index, column, item)
        else:
            self.table.setItem(0, 0, _item("NO SAVED WORKSPACES", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._open())
        root.addWidget(self.table, 1)

    def _selected(self) -> WorkspaceSnapshot | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        return self.store.get(str(name)) if name else None

    @Slot()
    def _save(self) -> None:
        if not self.name.text().strip():
            return
        self.store.save(
            WorkspaceSnapshot(
                self.name.text(), self.current_command, self.current_symbol,
                self.history, self.geometry_b64,
            )
        )
        self.command_requested.emit("WSP")

    @Slot()
    def _open(self) -> None:
        snapshot = self._selected()
        if snapshot is not None:
            self.workspace_selected.emit(snapshot)

    @Slot()
    def _delete(self) -> None:
        snapshot = self._selected()
        if snapshot is not None:
            self.store.delete(snapshot.name)
            self.command_requested.emit("WSP")


class UpdateWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, releases: tuple[BetaRelease, ...]) -> None:
        super().__init__()
        self.releases = releases
        self.current_executable = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("UPD  BETA RELEASES", AJAX_CYAN, bold=True))
        row.addWidget(_button("RUN / ROLLBACK", self._launch, amber=True))
        row.addWidget(_button("OPEN RELEASES FOLDER", self._open_folder))
        row.addWidget(_button("RESCAN", lambda: self.command_requested.emit("UPD")))
        row.addStretch(1)
        root.addWidget(controls)
        current = self.current_executable.name if self.current_executable else "DEVELOPMENT BUILD"
        root.addWidget(_heading(f"UPD  LOCAL BETA MANAGER  |  RUNNING {current}"))
        root.addWidget(_subheading("A RELEASE IS LAUNCHED SIDE-BY-SIDE; THE CURRENT EXECUTABLE IS NEVER OVERWRITTEN WHILE RUNNING."))
        self.table = _table(("VERSION", "STATUS", "INTEGRITY", "SIZE", "BUILT", "FILE", "SHA-256"))
        self.table.setRowCount(max(len(releases), 1))
        if releases:
            latest = max(item.version for item in releases)
            for table_row, release in enumerate(releases):
                running = self.current_executable == release.path
                status = "RUNNING" if running else "LATEST" if release.version == latest else "ROLLBACK"
                integrity = "VERIFIED" if release.verified else "NO CHECKSUM" if not release.expected_sha256 else "FAILED"
                values = (
                    f"BETA {release.version:03d}", status, integrity, f"{release.size_bytes / 1024 / 1024:,.1f} MB",
                    release.modified_at.strftime("%d %b %Y %H:%M"), release.path.name, release.sha256,
                )
                for column, value in enumerate(values):
                    color = AJAX_GREEN if integrity == "VERIFIED" and column == 2 else AJAX_RED if integrity == "FAILED" and column == 2 else AJAX_AMBER if column in {0, 1} else AJAX_TEXT
                    item = _item(value, color=color)
                    item.setData(Qt.ItemDataRole.UserRole, str(release.path))
                    self.table.setItem(table_row, column, item)
        else:
            self.table.setItem(0, 0, _item("NO BETA RELEASES FOUND", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._launch())
        root.addWidget(self.table, 1)

    def _selected_path(self) -> Path | None:
        row = self.table.currentRow()
        if row < 0 and self.releases:
            row = 0
        item = self.table.item(row, 0) if row >= 0 else None
        raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        path = Path(str(raw)) if raw else None
        return path if path is not None and path.exists() else None

    @Slot()
    def _launch(self) -> None:
        path = self._selected_path()
        if path is not None and path != self.current_executable:
            QProcess.startDetached(str(path), [], str(Path.cwd()))

    @Slot()
    def _open_folder(self) -> None:
        path = self._selected_path()
        folder = path.parent if path is not None else Path.cwd() / "releases" / "BETA"
        if folder.exists():
            open_local_path(folder)


def restore_workspace_geometry(snapshot: WorkspaceSnapshot) -> QByteArray:
    return QByteArray.fromBase64(snapshot.geometry_b64.encode("ascii")) if snapshot.geometry_b64 else QByteArray()


def _root(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    return layout


def _strip() -> QFrame:
    frame = QFrame()
    frame.setObjectName("viewStrip")
    row = QHBoxLayout(frame)
    row.setContentsMargins(7, 2, 7, 2)
    row.setSpacing(2)
    return frame


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _subheading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{AJAX_MUTED};padding:2px 7px")
    return label


def _label(text: str, color: str, *, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{color};font-weight:{'bold' if bold else 'normal'};padding:0 5px")
    return label


def _button(text: str, callback, *, amber: bool = False) -> QPushButton:
    button = QPushButton(text)
    if amber:
        button.setObjectName("amberButton")
    button.clicked.connect(callback)
    return button


def _input(placeholder: str, width: int) -> QLineEdit:
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    widget.setMaximumWidth(width)
    return widget


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(28)
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)
    table.setWordWrap(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setMinimumSectionSize(58)
    return table


def _item(value: object, *, color: str = AJAX_TEXT, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value))
    item.setForeground(QColor(color))
    alignment = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    return item


def _change_color(value: float | None) -> str:
    if value is None:
        return AJAX_MUTED
    if value > 0:
        return AJAX_GREEN
    if value < 0:
        return AJAX_RED
    return AJAX_TEXT


def _signed(value: float | None, decimals: int) -> str:
    return "--" if value is None else f"{value:+,.{decimals}f}"


def _percent(value: float | None) -> str:
    return "--" if value is None else fmt_percent(value, signed=True)
