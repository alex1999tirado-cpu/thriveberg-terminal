from __future__ import annotations

import sys
import urllib.parse
from math import ceil
from pathlib import Path

from PySide6.QtCore import QByteArray, QProcess, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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
        root = _root(self)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("PORT", AJAX_CYAN, bold=True))
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
        row.addWidget(_button("NEW", self._create))
        row.addSpacing(10)
        self.symbol = _input("SYMBOL", 110)
        self.quantity = _input("QUANTITY", 105)
        self.cost = _input("AVG COST", 105)
        self.currency = _input(model.base_currency, 70)
        for widget in (self.symbol, self.quantity, self.cost, self.currency):
            row.addWidget(widget)
        row.addWidget(_button("ADD / UPDATE", self._upsert, amber=True))
        row.addWidget(_button("REMOVE", self._remove))
        row.addWidget(_button("REFRESH", self._refresh))
        root.addWidget(controls)
        pnl_color = _change_color(model.profit_loss)
        title = QLabel(
            f"PORT  {model.name}  |  MARKET VALUE  {model.market_value:,.2f} {model.base_currency}  |  "
            f"BOOK  {model.book_value:,.2f}  |  <span style='color:{pnl_color}'>P&L {model.profit_loss:+,.2f}</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.table = _table(("SECURITY", "NAME", "QTY", "AVG COST", "LAST", "MARKET VALUE", "BOOK VALUE", "P&L", "P&L %", "WEIGHT", "CCY", "SOURCE", "DATA"))
        self.table.setRowCount(max(len(model.lines), 1))
        if model.lines:
            for table_row, line in enumerate(model.lines):
                values = (
                    line.position.symbol,
                    line.quote.name,
                    fmt_number(line.position.quantity, 4),
                    fmt_number(line.position.cost_basis, 4),
                    fmt_number(line.quote.price, 4),
                    fmt_number(line.market_value, 2),
                    fmt_number(line.book_value, 2),
                    _signed(line.profit_loss, 2),
                    _percent(line.profit_loss_percent),
                    _percent(line.weight_percent),
                    line.position.currency or line.quote.currency or model.base_currency,
                    line.quote.provider,
                    str(line.quote.quality),
                )
                for column, value in enumerate(values):
                    color = _change_color(line.profit_loss) if column in {7, 8} else AJAX_AMBER if column in {4, 5} else AJAX_TEXT
                    self.table.setItem(table_row, column, _item(value, color=color, right=column in {2, 3, 4, 5, 6, 7, 8, 9}))
        else:
            self.table.setItem(0, 0, _item("PORTFOLIO IS EMPTY", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_security)
        root.addWidget(self.table, 1)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

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
            name = self.store.create(self.new_name.text(), self.currency.text())
            self.command_requested.emit(f"PORT {name}")

    @Slot()
    def _upsert(self) -> None:
        try:
            self.store.upsert(
                self.symbol.text(), float(self.quantity.text()), float(self.cost.text()),
                self.currency.text(), self.model.name,
            )
        except ValueError:
            return
        self.command_requested.emit(f"PORT {self.model.name}")

    @Slot()
    def _remove(self) -> None:
        symbol = self._selected_symbol()
        if symbol:
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
