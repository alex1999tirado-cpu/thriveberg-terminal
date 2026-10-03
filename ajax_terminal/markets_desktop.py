from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
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
from ajax_terminal.charts.widgets.web_chart import EChartsWidget
from ajax_terminal.desktop_security import open_external_url
from ajax_terminal.models.macro import EconomicEvent
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.news_service import NewsService


GROUP_COMMANDS = {
    "GLOBAL EQUITIES": "WEI",
    "FX": "FXC",
    "RATES": "GOVT",
    "CREDIT": "CORP",
    "COMMODITIES": "INSTRUMENTS CMDTY",
}
PRICE_MOVER_GROUPS = {"GLOBAL EQUITIES", "FX", "COMMODITIES"}


@dataclass(frozen=True, slots=True)
class MarketGroup:
    name: str
    quotes: tuple[Quote, ...]


@dataclass(frozen=True, slots=True)
class MarketMonitorLoad:
    groups: tuple[MarketGroup, ...]
    events: tuple[EconomicEvent, ...]
    news: tuple[NewsItem, ...]
    loaded_at: datetime

    @property
    def quotes(self) -> tuple[Quote, ...]:
        return tuple(quote for group in self.groups for quote in group.quotes)

    @property
    def available(self) -> tuple[Quote, ...]:
        return tuple(
            quote
            for quote in self.quotes
            if quote.price is not None
            and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        )

    def quote(self, symbol: str) -> Quote | None:
        target = symbol.upper()
        return next((quote for quote in self.quotes if quote.symbol.upper() == target), None)


def load_market_monitor() -> MarketMonitorLoad:
    return asyncio.run(_load_market_monitor())


async def _load_market_monitor() -> MarketMonitorLoad:
    market = MarketService()
    definitions = market.registry.home_groups()
    tasks = {
        name: asyncio.create_task(
            market.government_quotes([instrument.symbol for instrument in instruments])
            if name == "RATES"
            else market.bulk_quotes(
                [instrument.symbol for instrument in instruments],
                allow_mock=False,
            )
        )
        for name, instruments in definitions.items()
    }
    news_task = asyncio.create_task(NewsService(market.cache).headlines(limit=12))
    groups: list[MarketGroup] = []
    for name, task in tasks.items():
        groups.append(MarketGroup(name, tuple(await task)))
    news = await news_task
    return MarketMonitorLoad(
        groups=tuple(groups),
        events=(),
        news=tuple(news),
        loaded_at=datetime.now(timezone.utc),
    )


def build_market_movers_option(model: MarketMonitorLoad, limit: int = 14) -> dict[str, object]:
    comparable = [
        quote
        for group in model.groups
        if group.name in PRICE_MOVER_GROUPS
        for quote in group.quotes
        if quote.change_percent is not None
        and quote.price is not None
        and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
    ]
    selected = sorted(comparable, key=lambda quote: abs(quote.change_percent or 0.0), reverse=True)[:limit]
    selected.sort(key=lambda quote: quote.change_percent or 0.0)
    values = [quote.change_percent or 0.0 for quote in selected]
    bound = max((abs(value) for value in values), default=1.0)
    bound = max(0.5, round(bound * 1.15, 2))
    return {
        "animation": False,
        "backgroundColor": "#030404",
        "tooltip": {
            "trigger": "item",
            "backgroundColor": "#111315",
            "borderColor": "#5b6065",
            "textStyle": {"color": AJAX_TEXT},
        },
        "grid": {"left": 72, "right": 58, "top": 12, "bottom": 25},
        "xAxis": {
            "type": "value",
            "min": -bound,
            "max": bound,
            "name": "1D %",
            "nameTextStyle": {"color": AJAX_AMBER},
            "axisLabel": {"color": AJAX_MUTED, "formatter": "{value}%"},
            "axisLine": {"lineStyle": {"color": "#5b6065"}},
            "splitLine": {"lineStyle": {"color": "#252a2e", "type": "dashed"}},
        },
        "yAxis": {
            "type": "category",
            "data": [quote.symbol for quote in selected],
            "axisLabel": {"color": AJAX_TEXT},
            "axisLine": {"lineStyle": {"color": "#5b6065"}},
            "axisTick": {"show": False},
        },
        "series": [
            {
                "name": "1D MOVE",
                "type": "bar",
                "barMaxWidth": 15,
                "data": [
                    {
                        "name": quote.symbol,
                        "value": round(quote.change_percent or 0.0, 3),
                        "itemStyle": {"color": _movement_color(quote.change_percent)},
                    }
                    for quote in selected
                ],
                "label": {
                    "show": True,
                    "position": "right",
                    "color": AJAX_AMBER,
                    "formatter": "{c}%",
                },
            }
        ],
    }


class MarketMonitorWorkspace(QWidget):
    command_requested = Signal(str)
    ready = Signal()

    def __init__(self, model: MarketMonitorLoad) -> None:
        super().__init__()
        self.model = model
        self._by_symbol = {quote.symbol: quote for quote in model.quotes}
        self._row_by_symbol: dict[str, int] = {}
        self._selected_row: int | None = None
        self._selected_symbol = model.available[0].symbol if model.available else ""
        self._selected_story = 0
        self._last_open_url = ""
        self._last_opened_at = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)
        root.addWidget(self._function_strip())
        root.addWidget(self._market_strip())

        self.body = QSplitter(Qt.Orientation.Vertical)
        self.body.setChildrenCollapsible(False)
        self.upper = QSplitter(Qt.Orientation.Horizontal)
        self.upper.setChildrenCollapsible(False)
        self.matrix_panel = self._matrix_panel()
        self.visual_column = self._visual_column()
        self.upper.addWidget(self.matrix_panel)
        self.upper.addWidget(self.visual_column)
        self.upper.setStretchFactor(0, 7)
        self.upper.setStretchFactor(1, 4)
        self.upper.setSizes([1180, 690])
        self.lower = self._information_tape()
        self.body.addWidget(self.upper)
        self.body.addWidget(self.lower)
        self.body.setStretchFactor(0, 4)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([650, 205])
        root.addWidget(self.body, 1)

        if self._selected_symbol:
            self._select_symbol(self._selected_symbol)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(lambda: self.command_requested.emit("MARKETS"))
        self.refresh_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        super().resizeEvent(event)
        if not hasattr(self, "table"):
            return
        compact = self.width() < 1_050 or self.height() < 570
        narrow = self.width() < 1_360
        self.visual_column.setVisible(not compact)
        self.lower.setVisible(not compact)
        self.function_title.setText("MM" if compact else "MM  CROSS-ASSET MARKET MONITOR")
        for label in ("6) ECO", "7) NEWS"):
            self.function_buttons[label].setVisible(not compact)
        for column in (5, 6, 7):
            self.table.setColumnHidden(column, narrow)
        self.table.setColumnHidden(1, compact)
        self.table.setColumnHidden(3, compact)
        header = self.table.horizontalHeader()
        if compact:
            available_width = max(self.width() - 18, 520)
            widths = (0.24, 0.25, 0.25, 0.26)
            for column in (0, 2, 4, 8):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            for column, share in zip((0, 2, 4, 8), widths, strict=True):
                self.table.setColumnWidth(column, int(available_width * share))
        else:
            for column in range(self.table.columnCount()):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _function_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(1)
        self.function_title = QLabel("MM  CROSS-ASSET MARKET MONITOR")
        self.function_title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold;padding-right:10px")
        row.addWidget(self.function_title)
        commands = (
            ("1) MARKETS", "MARKETS", True),
            ("2) WEI", "WEI", False),
            ("3) FXC", "FXC", False),
            ("4) GOVT", "GOVT", False),
            ("5) CORP", "CORP", False),
            ("6) ECO", "ECO", False),
            ("7) NEWS", "NEWS", False),
        )
        self.function_buttons: dict[str, QPushButton] = {}
        for label, command, active in commands:
            button = _button(
                label,
                lambda _checked=False, value=command: self.command_requested.emit(value),
                active=active,
            )
            self.function_buttons[label] = button
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(_button("REFRESH", lambda: self.command_requested.emit("MARKETS"), amber=True))
        return frame

    def _market_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("metricsStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(18)
        changes = [quote.change_percent for quote in self.model.available if quote.change_percent is not None]
        row.addWidget(_metric("COVERAGE", f"{len(self.model.available)}/{len(self.model.quotes)}"))
        row.addWidget(_metric("ADV", str(sum(value > 0 for value in changes)), AJAX_GREEN))
        row.addWidget(_metric("DEC", str(sum(value < 0 for value in changes)), AJAX_RED))
        for label, symbol in (("UST 10Y", "US10Y"), ("EUR/USD", "EURUSD"), ("BRENT", "BRENT")):
            quote = self.model.quote(symbol)
            row.addWidget(_metric(label, _price(quote) if quote else "--", AJAX_TEXT))
        row.addStretch(1)
        observed = max((quote.timestamp for quote in self.model.available), default=self.model.loaded_at)
        row.addWidget(_metric("AS OF", observed.astimezone().strftime("%d %b %H:%M"), AJAX_TEXT))
        row.addWidget(_metric("AUTO", "30S", AJAX_CYAN))
        return frame

    def _matrix_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        heading = QLabel("MULTI-ASSET MATRIX")
        heading.setObjectName("panelHeader")
        layout.addWidget(heading)
        headers = ("SECURITY", "DESCRIPTION", "LAST", "NET CHG", "CHG%", "BID", "ASK", "CCY", "DATA")
        self.table = QTableWidget(0, len(headers))
        self.table.setObjectName("marketMatrix")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(23)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self._matrix_clicked)
        self.table.cellDoubleClicked.connect(self._open_matrix_row)
        self._populate_matrix()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 105)
        self.table.setColumnWidth(8, 100)
        layout.addWidget(self.table, 1)
        note = QLabel("CLICK SELECTS  |  DOUBLE-CLICK OPENS GP  |  VALUES SHOW PROVIDER QUALITY; UNAVAILABLE DATA IS NEVER SYNTHESIZED")
        note.setStyleSheet(f"color:{AJAX_MUTED};padding:3px 7px")
        layout.addWidget(note)
        panel.setMinimumWidth(560)
        return panel

    def _populate_matrix(self) -> None:
        rows = sum(len(group.quotes) + 1 for group in self.model.groups)
        self.table.setRowCount(rows)
        row = 0
        for group in self.model.groups:
            self.table.setSpan(row, 0, 1, self.table.columnCount())
            group_item = _item(group.name, AJAX_CYAN, bold=True)
            group_item.setBackground(QColor("#111417"))
            group_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(row, 0, group_item)
            self.table.setRowHeight(row, 23)
            row += 1
            for quote in group.quotes:
                self._row_by_symbol[quote.symbol] = row
                values = (
                    quote.symbol,
                    quote.name,
                    _price(quote),
                    _net_change(quote),
                    _percent(quote.change_percent),
                    _plain_price(quote.bid, quote),
                    _plain_price(quote.ask, quote),
                    quote.currency or "--",
                    str(quote.quality),
                )
                movement = _movement_color(quote.change_percent if quote.change_percent is not None else quote.change)
                for column, value in enumerate(values):
                    color = AJAX_TEXT
                    if column == 2:
                        color = AJAX_AMBER
                    elif column in {3, 4}:
                        color = movement
                    elif column == 8:
                        color = AJAX_MUTED if quote.quality == DataQuality.UNAVAILABLE else AJAX_CYAN
                    cell = _item(value, color, right=column in {2, 3, 4, 5, 6})
                    cell.setData(Qt.ItemDataRole.UserRole, quote.symbol)
                    cell.setToolTip(_quote_tooltip(quote))
                    self.table.setItem(row, column, cell)
                row += 1
        self.table.clearSelection()

    def _visual_column(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._chart_panel())
        splitter.addWidget(self._detail_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([390, 245])
        splitter.setMinimumWidth(330)
        return splitter

    def _chart_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        header = QFrame()
        header.setObjectName("viewStrip")
        row = QHBoxLayout(header)
        row.setContentsMargins(7, 2, 7, 2)
        row.addWidget(_label("PRICE MOVERS / 1D", AJAX_TEXT, bold=True))
        row.addStretch(1)
        row.addWidget(_label("EQUITY + FX + COMMODITY", AJAX_AMBER, bold=True))
        layout.addWidget(header)
        self.chart = EChartsWidget()
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart.country_clicked.connect(self._select_symbol)
        self.chart.loadFinished.connect(lambda _ok: self.ready.emit())
        self.chart.set_option(build_market_movers_option(self.model), events=True)
        layout.addWidget(self.chart, 1)
        return panel

    def _detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("terminalPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 5, 8, 6)
        layout.setSpacing(3)
        top = QHBoxLayout()
        self.detail_title = _label("NO SECURITY SELECTED", AJAX_CYAN, bold=True)
        top.addWidget(self.detail_title)
        top.addStretch(1)
        for label, command in (("GP", "GP"), ("DES", "DES"), ("NEWS", "NEWS")):
            button = _button(label, lambda _checked=False, value=command: self._run_selected(value))
            top.addWidget(button)
        layout.addLayout(top)
        self.detail_grid = QGridLayout()
        self.detail_grid.setContentsMargins(0, 0, 0, 0)
        self.detail_grid.setHorizontalSpacing(15)
        self.detail_grid.setVerticalSpacing(2)
        self.detail_values: dict[str, QLabel] = {}
        fields = ("LAST", "NET CHANGE", "BID / ASK", "DAY RANGE", "52W RANGE", "VOLUME", "PROVIDER", "OBSERVED")
        for index, field in enumerate(fields):
            grid_row, column = divmod(index, 2)
            label_column = column * 2
            self.detail_grid.addWidget(_label(field, AJAX_MUTED), grid_row, label_column)
            value = _label("--", AJAX_AMBER)
            self.detail_values[field] = value
            self.detail_grid.addWidget(value, grid_row, label_column + 1)
        self.detail_grid.setColumnStretch(1, 1)
        self.detail_grid.setColumnStretch(3, 1)
        layout.addLayout(self.detail_grid)
        layout.addStretch(1)
        return panel

    def _information_tape(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._news_panel())
        splitter.addWidget(self._breadth_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([1130, 730])
        splitter.setMinimumHeight(150)
        return splitter

    def _news_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        heading = QLabel("TOP MARKET STORIES  /  CLICK PREVIEW  /  DOUBLE-CLICK SOURCE")
        heading.setObjectName("panelHeader")
        layout.addWidget(heading)
        self.news_table = QTableWidget(0, 4)
        self.news_table.setHorizontalHeaderLabels(("TIME", "SOURCE", "HEADLINE", "DATA"))
        self.news_table.verticalHeader().hide()
        self.news_table.verticalHeader().setDefaultSectionSize(24)
        self.news_table.setAlternatingRowColors(True)
        self.news_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.news_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.news_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.news_table.cellClicked.connect(self._story_clicked)
        self.news_table.cellDoubleClicked.connect(self._open_story)
        self._populate_news()
        news_header = self.news_table.horizontalHeader()
        news_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        news_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.news_table, 1)
        self.news_preview = QLabel("NO VERIFIED HEADLINES AVAILABLE")
        self.news_preview.setStyleSheet(f"color:{AJAX_MUTED};padding:2px 7px")
        self.news_preview.setWordWrap(False)
        layout.addWidget(self.news_preview)
        if self.model.news:
            self.news_table.setCurrentCell(0, 0)
            self._show_story(0)
        return panel

    def _populate_news(self) -> None:
        items = self.model.news[:8]
        self.news_table.setRowCount(len(items))
        for row, story in enumerate(items):
            values = (
                story.timestamp.astimezone().strftime("%H:%M"),
                story.source,
                story.headline,
                str(story.quality),
            )
            for column, value in enumerate(values):
                color = AJAX_AMBER if column == 2 else AJAX_MUTED if column == 3 else AJAX_TEXT
                cell = _item(value, color)
                if column == 2 and story.link:
                    font = QFont(cell.font())
                    font.setUnderline(True)
                    cell.setFont(font)
                    cell.setToolTip("Select for preview; double-click to open the verified source")
                self.news_table.setItem(row, column, cell)

    def _breadth_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        heading = QLabel("CROSS-ASSET BREADTH / DOUBLE-CLICK GROUP")
        heading.setObjectName("panelHeader")
        layout.addWidget(heading)
        self.breadth_table = QTableWidget(len(self.model.groups), 6)
        self.breadth_table.setHorizontalHeaderLabels(("ASSET", "ADV", "DEC", "FLAT", "LEADER", "MOVE"))
        self.breadth_table.verticalHeader().hide()
        self.breadth_table.verticalHeader().setDefaultSectionSize(24)
        self.breadth_table.setAlternatingRowColors(True)
        self.breadth_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.breadth_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.breadth_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.breadth_table.cellDoubleClicked.connect(self._open_breadth)
        for row, group in enumerate(self.model.groups):
            available = [
                quote
                for quote in group.quotes
                if quote.price is not None
                and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
            ]
            changes = [quote for quote in available if quote.change_percent is not None]
            leader = max(changes, key=lambda quote: quote.change_percent or 0.0) if changes else None
            values = (
                group.name,
                str(sum((quote.change_percent or 0.0) > 0 for quote in changes)),
                str(sum((quote.change_percent or 0.0) < 0 for quote in changes)),
                str(sum((quote.change_percent or 0.0) == 0 for quote in changes)),
                leader.symbol if leader else "--",
                _percent(leader.change_percent) if leader else "--",
            )
            for column, value in enumerate(values):
                color = AJAX_TEXT
                if column == 1:
                    color = AJAX_GREEN
                elif column == 2:
                    color = AJAX_RED
                elif column in {4, 5}:
                    color = AJAX_AMBER
                cell = _item(value, color, right=column in {1, 2, 3, 5})
                cell.setData(Qt.ItemDataRole.UserRole, GROUP_COMMANDS.get(group.name, "MARKETS"))
                self.breadth_table.setItem(row, column, cell)
        breadth_header = self.breadth_table.horizontalHeader()
        breadth_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        breadth_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.breadth_table, 1)
        return panel

    @Slot(int, int)
    def _matrix_clicked(self, row: int, column: int) -> None:
        cell = self.table.item(row, column) or self.table.item(row, 0)
        symbol = cell.data(Qt.ItemDataRole.UserRole) if cell is not None else ""
        if isinstance(symbol, str):
            self._select_symbol(symbol)

    @Slot(int, int)
    def _open_matrix_row(self, row: int, column: int) -> None:
        self._matrix_clicked(row, column)
        if self._selected_symbol:
            self.command_requested.emit(f"GP {self._selected_symbol} 1Y 1D")

    @Slot(str)
    def _select_symbol(self, symbol: str) -> None:
        quote = self._by_symbol.get(symbol)
        if quote is None:
            return
        self._selected_symbol = symbol
        row = self._row_by_symbol.get(symbol)
        if row is not None:
            self._set_selected_row_colors(row)
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0), QAbstractItemView.ScrollHint.EnsureVisible)
        self.detail_title.setText(f"{quote.symbol}  {quote.name.upper()}")
        observed = quote.timestamp.astimezone().strftime("%d %b %H:%M")
        details = {
            "LAST": f"{_price(quote)}  {_percent(quote.change_percent)}",
            "NET CHANGE": _net_change(quote),
            "BID / ASK": f"{_plain_price(quote.bid, quote)} / {_plain_price(quote.ask, quote)}",
            "DAY RANGE": f"{_plain_price(quote.day_low, quote)} / {_plain_price(quote.day_high, quote)}",
            "52W RANGE": f"{_plain_price(quote.week_52_low, quote)} / {_plain_price(quote.week_52_high, quote)}",
            "VOLUME": _compact_number(quote.volume),
            "PROVIDER": f"{quote.provider} / {quote.quality}",
            "OBSERVED": observed,
        }
        for field, value in details.items():
            self.detail_values[field].setText(value)

    def _run_selected(self, function: str) -> None:
        if not self._selected_symbol:
            return
        command = f"{function} {self._selected_symbol}"
        if function == "GP":
            command += " 1Y 1D"
        self.command_requested.emit(command)

    @Slot(int, int)
    def _story_clicked(self, row: int, _column: int) -> None:
        self._show_story(row)

    def _show_story(self, row: int) -> None:
        if not 0 <= row < len(self.model.news[:8]):
            return
        self._selected_story = row
        story = self.model.news[row]
        preview = story.summary.strip() or story.headline
        self.news_preview.setText(f"{story.category}  |  {preview}")
        self.news_preview.setToolTip(preview)

    @Slot(int, int)
    def _open_story(self, row: int, _column: int) -> None:
        self._show_story(row)
        if not 0 <= row < len(self.model.news[:8]):
            return
        link = self.model.news[row].link.strip()
        if not link:
            self.news_preview.setText("SOURCE LINK UNAVAILABLE FOR THIS STORY")
            return
        now = monotonic()
        if link == self._last_open_url and now - self._last_opened_at < 0.75:
            return
        self._last_open_url = link
        self._last_opened_at = now
        try:
            opened = open_external_url(link)
        except (TypeError, ValueError) as exc:
            self.news_preview.setText(f"SOURCE LINK REJECTED  |  {exc}")
            return
        self.news_preview.setText("SOURCE OPENED" if opened else "WINDOWS COULD NOT OPEN THE SOURCE")

    @Slot(int, int)
    def _open_breadth(self, row: int, column: int) -> None:
        cell = self.breadth_table.item(row, column) or self.breadth_table.item(row, 0)
        command = cell.data(Qt.ItemDataRole.UserRole) if cell is not None else ""
        if isinstance(command, str) and command:
            self.command_requested.emit(command)

    def _set_selected_row_colors(self, row: int) -> None:
        if self._selected_row is not None:
            previous = self.table.item(self._selected_row, 0)
            symbol = previous.data(Qt.ItemDataRole.UserRole) if previous is not None else ""
            quote = self._by_symbol.get(symbol)
            if quote is not None:
                movement = _movement_color(
                    quote.change_percent if quote.change_percent is not None else quote.change
                )
                for column in range(self.table.columnCount()):
                    cell = self.table.item(self._selected_row, column)
                    if cell is None:
                        continue
                    color = AJAX_TEXT
                    if column == 2:
                        color = AJAX_AMBER
                    elif column in {3, 4}:
                        color = movement
                    elif column == 8:
                        color = AJAX_MUTED if quote.quality == DataQuality.UNAVAILABLE else AJAX_CYAN
                    cell.setForeground(QColor(color))
        for column in range(self.table.columnCount()):
            cell = self.table.item(row, column)
            if cell is not None:
                cell.setForeground(QColor("#050505"))
        self._selected_row = row


def _price(quote: Quote | None) -> str:
    if quote is None or quote.price is None:
        return "--"
    return _plain_price(quote.price, quote)


def _plain_price(value: float | None, quote: Quote) -> str:
    if value is None:
        return "--"
    is_yield = quote.currency == "%" or quote.asset_class.upper() in {"RATE", "BOND"}
    if is_yield:
        return f"{value:.3f}%"
    if quote.asset_class.upper() == "FX":
        return f"{value:.5f}"
    return f"{value:,.2f}"


def _net_change(quote: Quote) -> str:
    if quote.change is None:
        return "--"
    if quote.currency == "%" or quote.asset_class.upper() in {"RATE", "BOND"}:
        return f"{quote.change * 100:+.1f}bp"
    decimals = 5 if quote.asset_class.upper() == "FX" else 2
    return f"{quote.change:+,.{decimals}f}"


def _percent(value: float | None) -> str:
    return "--" if value is None else f"{value:+.2f}%"


def _compact_number(value: float | None) -> str:
    if value is None:
        return "--"
    for scale, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(value) >= scale:
            return f"{value / scale:.2f}{suffix}"
    return f"{value:,.0f}"


def _movement_color(value: float | None) -> str:
    if value is None or value == 0:
        return AJAX_TEXT
    return AJAX_GREEN if value > 0 else AJAX_RED


def _quote_tooltip(quote: Quote) -> str:
    observed = quote.timestamp.astimezone().strftime("%d %b %Y %H:%M %Z")
    details = [
        quote.name,
        f"SOURCE: {quote.provider}",
        f"DATA: {quote.quality}",
        f"AS OF: {observed}",
    ]
    if quote.estimated:
        details.append(f"ESTIMATED: {quote.methodology or 'DERIVED VALUE'}")
    return "\n".join(details)


def _button(text: str, callback, *, active: bool = False, amber: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("amberButton" if amber or active else "functionTab")
    button.clicked.connect(callback)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _metric(label: str, value: str, color: str = AJAX_AMBER) -> QLabel:
    widget = QLabel(f"{label}  {value}")
    widget.setStyleSheet(f"color:{color};font-weight:bold")
    return widget


def _label(text: str, color: str, *, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{color};font-weight:{'bold' if bold else 'normal'}")
    return label


def _item(value: object, color: str = AJAX_TEXT, *, right: bool = False, bold: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value))
    item.setForeground(QColor(color))
    if bold:
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
    alignment = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item
