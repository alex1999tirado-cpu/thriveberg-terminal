from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from ajax_terminal.services.data_quality_service import DataQualityDashboard
from ajax_terminal.utils.formatting import fmt_timestamp


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.=_^-]{0,24}$")


class DataQualityWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, model: DataQualityDashboard) -> None:
        super().__init__()
        self.model = model
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("DQM  DATA QUALITY MONITOR", AJAX_CYAN, bold=True))
        self.provider_filter = QLineEdit()
        self.provider_filter.setPlaceholderText("FILTER PROVIDER / DOMAIN / STATUS")
        self.provider_filter.setMaximumWidth(310)
        self.provider_filter.textChanged.connect(self._filter_health)
        row.addWidget(self.provider_filter)
        row.addStretch(1)
        row.addWidget(_button("PROBE ALL", self._probe, amber=True))
        root.addWidget(controls)

        root.addWidget(
            _heading(
                f"AVAILABLE {model.available_count}   |   DEGRADED {model.degraded_count}   |   "
                f"FAILED {model.failed_count}   |   FRESH CACHE {model.fresh_cache_count}   |   "
                f"STALE CACHE {model.stale_cache_count}"
            )
        )
        root.addWidget(
            _subheading(
                "PROBE RUNS NON-DESTRUCTIVE LIVE CHECKS  |  NO CREDENTIALS OR PROVIDER PAYLOADS ARE STORED"
            )
        )

        self.tabs = QTabWidget()
        self.tabs.setObjectName("dataQualityTabs")
        self.health_table = self._health_table()
        self.cache_table = self._cache_table()
        self.coverage_table = self._coverage_table()
        compare_page, self.comparison_table = self._comparison_page()
        self.tabs.addTab(self.health_table, "1) PROVIDER HEALTH")
        self.tabs.addTab(self.cache_table, "2) CACHE INVENTORY")
        self.tabs.addTab(self.coverage_table, "3) COVERAGE MATRIX")
        self.tabs.addTab(compare_page, "4) SOURCE COMPARISON")
        if model.symbol:
            self.tabs.setCurrentIndex(3)
        root.addWidget(self.tabs, 1)
        QTimer.singleShot(0, self._clear_initial_selection)

    def _health_table(self) -> QTableWidget:
        table = _table(
            (
                "PROVIDER",
                "GROUP",
                "TEST",
                "CONFIG",
                "STATUS",
                "QUALITY",
                "LATENCY",
                "OK / FAIL",
                "LAST CHECK",
                "MESSAGE",
            )
        )
        table.setRowCount(len(self.model.providers))
        for row, provider in enumerate(self.model.providers):
            values = (
                provider.provider,
                provider.group,
                provider.domain,
                provider.configuration,
                provider.status,
                str(provider.quality) if provider.status not in {"DISABLED", "UNTESTED"} else "--",
                f"{provider.latency_ms:,.0f} ms" if provider.latency_ms is not None else "--",
                f"{provider.success_count} / {provider.failure_count}",
                fmt_timestamp(provider.last_checked_at) if provider.last_checked_at else "--",
                provider.message or "--",
            )
            for column, value in enumerate(values):
                color = _status_color(provider.status) if column == 4 else AJAX_TEXT
                if column in {3, 5, 6, 8, 9} and value == "--":
                    color = AJAX_MUTED
                table.setItem(row, column, _item(value, color=color, right=column in {6, 7}))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)
        table.clearSelection()
        table.setCurrentItem(None)
        return table

    def _cache_table(self) -> QTableWidget:
        table = _table(
            (
                "DOMAIN",
                "TOTAL",
                "FRESH",
                "STALE",
                "MOCK",
                "UNAVAILABLE",
                "OLDEST WRITE",
                "LATEST WRITE",
                "PROVIDERS",
            )
        )
        table.setRowCount(max(1, len(self.model.cache)))
        if not self.model.cache:
            table.setItem(0, 0, _item("CACHE IS EMPTY", color=AJAX_MUTED))
        for row, domain in enumerate(self.model.cache):
            values = (
                domain.domain,
                domain.total,
                domain.fresh,
                domain.stale,
                domain.mock,
                domain.unavailable,
                fmt_timestamp(domain.oldest_at) if domain.oldest_at else "--",
                fmt_timestamp(domain.newest_at) if domain.newest_at else "--",
                ", ".join(domain.providers) or "--",
            )
            for column, value in enumerate(values):
                color = AJAX_TEXT
                if column == 2 and domain.fresh:
                    color = AJAX_GREEN
                elif column in {3, 4, 5} and int(value):
                    color = AJAX_RED if column in {4, 5} else AJAX_AMBER
                table.setItem(row, column, _item(value, color=color, right=column in {1, 2, 3, 4, 5}))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        table.clearSelection()
        table.setCurrentItem(None)
        return table

    def _coverage_table(self) -> QTableWidget:
        domains = tuple(
            domain
            for domain in (
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
        )
        table = _table(("PROVIDER", "CONFIG", *domains))
        table.setRowCount(len(self.model.capabilities))
        for row, provider in enumerate(self.model.capabilities):
            table.setItem(row, 0, _item(provider.provider))
            config_color = AJAX_GREEN if provider.configured else AJAX_MUTED
            table.setItem(row, 1, _item("READY" if provider.configured else "DISABLED", color=config_color))
            for index, domain in enumerate(domains, start=2):
                supported = domain in provider.domains
                value = "YES" if supported else "--"
                color = AJAX_CYAN if supported and provider.configured else AJAX_MUTED
                table.setItem(row, index, _item(value, color=color))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.clearSelection()
        table.setCurrentItem(None)
        return table

    def _comparison_page(self) -> tuple[QWidget, QTableWidget]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        controls = _strip()
        row = controls.layout()
        row.addWidget(_label("SECURITY", AJAX_CYAN, bold=True))
        self.symbol = QLineEdit(self.model.symbol)
        self.symbol.setPlaceholderText("TICKER, E.G. AAPL OR ES10Y")
        self.symbol.setMaximumWidth(220)
        self.symbol.returnPressed.connect(self._compare)
        row.addWidget(self.symbol)
        row.addWidget(_button("COMPARE", self._compare, amber=True))
        row.addStretch(1)
        row.addWidget(_label("DOUBLE-CLICK A ROW FOR FLDS PRICE", AJAX_MUTED))
        layout.addWidget(controls)
        table = _table(
            (
                "SOURCE",
                "STATUS",
                "PRICE",
                "CCY / UNIT",
                "QUALITY",
                "DIFF BP",
                "CHECK",
                "LATENCY",
                "AS OF",
                "MESSAGE",
            )
        )
        table.setRowCount(max(1, len(self.model.comparisons)))
        if not self.model.comparisons:
            table.setItem(
                0,
                0,
                _item("ENTER A SECURITY TO COMPARE ALL APPLICABLE SOURCES", color=AJAX_MUTED),
            )
        for table_row, comparison in enumerate(self.model.comparisons):
            values = (
                comparison.provider,
                comparison.status,
                f"{comparison.price:,.6f}" if comparison.price is not None else "--",
                comparison.currency or "--",
                str(comparison.quality) if comparison.price is not None else "--",
                f"{comparison.difference_bp:+,.1f}" if comparison.difference_bp is not None else "--",
                comparison.alignment or "--",
                f"{comparison.latency_ms:,.0f} ms" if comparison.latency_ms is not None else "--",
                fmt_timestamp(comparison.timestamp) if comparison.timestamp else "--",
                comparison.message or "--",
            )
            for column, value in enumerate(values):
                color = _status_color(comparison.status) if column == 1 else AJAX_TEXT
                if column in {2, 5} and value != "--":
                    color = AJAX_AMBER
                if column == 6:
                    color = {
                        "ALIGNED": AJAX_GREEN,
                        "DIVERGENT": AJAX_RED,
                        "SINGLE SOURCE": AJAX_AMBER,
                    }.get(str(value), AJAX_MUTED)
                table.setItem(table_row, column, _item(value, color=color, right=column in {2, 5, 7}))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)
        table.cellDoubleClicked.connect(self._open_fields)
        table.clearSelection()
        table.setCurrentItem(None)
        layout.addWidget(table, 1)
        return page, table

    @Slot(str)
    def _filter_health(self, value: str) -> None:
        needle = " ".join(value.upper().split())
        for row in range(self.health_table.rowCount()):
            haystack = " ".join(
                self.health_table.item(row, column).text().upper()
                for column in range(self.health_table.columnCount())
                if self.health_table.item(row, column) is not None
            )
            self.health_table.setRowHidden(row, bool(needle and needle not in haystack))

    @Slot()
    def _clear_initial_selection(self) -> None:
        for table in (
            self.health_table,
            self.cache_table,
            self.coverage_table,
            self.comparison_table,
        ):
            table.clearSelection()
            table.selectionModel().clearCurrentIndex()
        self.provider_filter.setFocus()

    @Slot()
    def _probe(self) -> None:
        suffix = f" {self.model.symbol}" if self.model.symbol else ""
        self.command_requested.emit(f"DQM{suffix} PROBE")

    @Slot()
    def _compare(self) -> None:
        symbol = self.symbol.text().strip().upper()
        if not _SYMBOL_RE.fullmatch(symbol):
            self.symbol.setFocus()
            self.symbol.selectAll()
            return
        self.command_requested.emit(f"DQM {symbol}")

    @Slot(int, int)
    def _open_fields(self, _row: int, _column: int) -> None:
        if self.model.symbol:
            self.command_requested.emit(f"{self.model.symbol} FLDS PRICE")


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


def _status_color(status: str) -> str:
    return {
        "AVAILABLE": AJAX_GREEN,
        "DEGRADED": AJAX_AMBER,
        "FAILED": AJAX_RED,
        "DISABLED": AJAX_MUTED,
        "UNTESTED": AJAX_CYAN,
    }.get(status, AJAX_TEXT)
