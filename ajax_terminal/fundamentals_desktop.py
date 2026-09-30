from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.charts.theme import (
    AJAX_AMBER,
    AJAX_BORDER,
    AJAX_CYAN,
    AJAX_GREEN,
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
    AJAX_YELLOW,
)
from ajax_terminal.desktop_security import open_external_url, open_local_path
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    EstimateSet,
    FinancialAnalysis,
    FinancialMetric,
)
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import (
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    PriceHistory,
    Quote,
    StatementType,
)
from ajax_terminal.services.equity_research_service import EquityResearchService
from ajax_terminal.services.excel_export_service import ExcelExportService, FinancialExportResult
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.utils.financials import (
    grouped_statement_metrics,
    is_expense_or_outflow_metric,
    ordered_statement_metrics,
)
from ajax_terminal.utils.formatting import fmt_bp, fmt_money, fmt_number, fmt_percent


@dataclass(slots=True)
class SecurityDescriptionData:
    quote: Quote
    history: PriceHistory
    fundamentals: EquityFundamentals
    profile: CompanyProfile
    analyst: AnalystConsensus
    estimates: EstimateSet
    news: list[NewsItem]


def load_security_description(symbol: str) -> SecurityDescriptionData:
    async def load() -> SecurityDescriptionData:
        market = MarketService()
        research = EquityResearchService(market)
        news_service = NewsService(market.cache)
        instrument = market.registry.resolve(symbol)
        if instrument.instrument_type == "GOVT_BENCHMARK":
            quotes, history, news = await asyncio.gather(
                market.government_quotes([instrument.symbol]),
                market.history(instrument.symbol, "1Y", allow_mock=False),
                news_service.headlines(f"{instrument.country} government bonds", limit=8),
            )
            quote = quotes[0]
            return SecurityDescriptionData(
                quote=quote,
                history=history,
                fundamentals=EquityFundamentals(
                    instrument.symbol,
                    instrument.name,
                    provider="NOT APPLICABLE",
                    quality=DataQuality.UNAVAILABLE,
                ),
                profile=CompanyProfile(
                    instrument.symbol,
                    instrument.name,
                    sector="Sovereign Rates",
                    industry="Government Bond Benchmark",
                    country=instrument.country,
                    currency="%",
                    provider=quote.provider,
                    quality=quote.quality,
                ),
                analyst=AnalystConsensus(instrument.symbol, instrument.name),
                estimates=EstimateSet(instrument.symbol, instrument.name, "%", []),
                news=news,
            )
        quote, history, fundamentals, profile, analyst, estimates, news = await asyncio.gather(
            market.quote(symbol, allow_mock=False),
            market.history(symbol, "1Y", allow_mock=False),
            market.equity_fundamentals(symbol),
            research.company_profile(symbol),
            research.analyst_consensus(symbol),
            research.estimates(symbol),
            news_service.headlines(symbol, limit=8),
        )
        return SecurityDescriptionData(
            quote,
            history,
            fundamentals,
            profile,
            analyst,
            estimates,
            news,
        )

    return asyncio.run(load())


def load_financial_statement(
    symbol: str,
    statement_type: StatementType,
    *,
    refresh: bool = False,
) -> FinancialStatements:
    return asyncio.run(
        MarketService().financial_statements(symbol, statement_type, refresh=refresh)
    )


def load_financial_analysis(symbol: str) -> FinancialAnalysis:
    market = MarketService()
    return asyncio.run(EquityResearchService(market).financial_analysis(symbol))


def export_financial_statements(symbol: str) -> FinancialExportResult:
    export_dir = Path.home() / "Downloads" / "THRIVEBERG Exports"
    return asyncio.run(ExcelExportService(MarketService(), export_dir).export_financials(symbol))


class SecurityDescriptionWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, data: SecurityDescriptionData) -> None:
        super().__init__()
        self.data = data
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(self._function_strip())

        if self.data.quote.asset_class == "RATE":
            root.addWidget(self._rate_tabs(), 1)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(8)
        layout.addWidget(self._identity())
        layout.addWidget(_section("MARKET SNAPSHOT"))
        layout.addWidget(self._market_snapshot())
        layout.addWidget(_section("FUNDAMENTALS / VALUATION"))
        layout.addLayout(self._fundamental_grid())
        layout.addWidget(_section("ANALYST / EARNINGS"))
        layout.addWidget(self._analyst_table())
        layout.addWidget(_section("RELATED HEADLINES"))
        layout.addWidget(self._news_table())
        layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _function_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        if self.data.quote.asset_class == "RATE":
            commands = (("1) DES", "DES"), ("2) GP", "GP"), ("3) GOVT", "GOVT"))
        else:
            commands = (
                ("1) DES", "DES"),
                ("2) GP", "GP"),
                ("3) FA", "FA"),
                ("4) EE", "EE"),
                ("5) ANR", "ANR"),
                ("6) RV", "RV"),
                ("7) FILINGS", "FILINGS"),
                ("8) NEWS", "NEWS"),
                ("IS", "IS"),
                ("BS", "BS"),
                ("CF", "CF"),
                ("FLDS", "FLDS"),
                ("XLS", "XLS"),
            )
        for label, command in commands:
            button = QPushButton(label)
            button.setObjectName("functionTab")
            button.setCheckable(command == "DES")
            button.setChecked(command == "DES")
            button.clicked.connect(
                lambda _checked=False, value=command: self.command_requested.emit(
                    f"{self.data.quote.symbol} {value}"
                )
            )
            row.addWidget(button)
        row.addStretch(1)
        return frame

    def _rate_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("workspaceTabs")

        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overview = QWidget()
        layout = QVBoxLayout(overview)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(8)
        layout.addWidget(self._rate_identity())
        layout.addWidget(_section("YIELD SNAPSHOT"))
        snapshot = self._rate_snapshot()
        layout.addWidget(snapshot)
        layout.addWidget(_section("RECENT OBSERVATIONS"))
        layout.addWidget(self._rate_history())
        layout.addWidget(_section("RELATED HEADLINES"))
        layout.addWidget(self._news_table())
        layout.addStretch(1)
        overview_scroll.setWidget(overview)
        tabs.addTab(overview_scroll, "DES")

        methodology = QWidget()
        methodology_layout = QVBoxLayout(methodology)
        methodology_layout.setContentsMargins(20, 14, 20, 14)
        methodology_layout.setSpacing(8)
        methodology_layout.addWidget(_section("DATA PROVENANCE / METHODOLOGY"))
        text = QLabel(self._methodology_text())
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setStyleSheet(f"color:{AJAX_TEXT};padding:8px;border:1px solid {AJAX_BORDER}")
        methodology_layout.addWidget(text)
        methodology_layout.addStretch(1)
        tabs.addTab(methodology, "METHODOLOGY")

        snapshot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        snapshot.customContextMenuRequested.connect(
            lambda position: self._open_rate_context_menu(tabs, snapshot, position)
        )
        self.rate_tabs = tabs
        return tabs

    def _rate_identity(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title = QLabel(f"{self.data.quote.name.upper()}   {self.data.quote.symbol}")
        title.setStyleSheet(f"color:{AJAX_YELLOW};font-size:15px;font-weight:bold")
        layout.addWidget(title)
        marker = "   |   ESTIMATED *" if self.data.quote.estimated else ""
        detail = QLabel(
            f"SOVEREIGN BENCHMARK   |   YIELD UNIT %   |   {self.data.quote.provider}   |   "
            f"{self.data.quote.quality}{marker}"
        )
        detail.setStyleSheet(f"color:{AJAX_TEXT}")
        layout.addWidget(detail)
        return panel

    def _rate_snapshot(self) -> QTableWidget:
        quote = self.data.quote
        change_bp = quote.change * 100.0 if quote.change is not None else None
        marker = "*" if quote.estimated and quote.price is not None else ""
        rows = (
            ("YIELD", f"{fmt_percent(quote.price, 3)}{marker}", "D1", fmt_bp(change_bp)),
            ("PREVIOUS", fmt_percent(quote.previous_close, 3), "UNIT", "PERCENT"),
            ("OBSERVED", quote.timestamp.strftime("%d %b %Y %H:%M UTC"), "QUALITY", str(quote.quality)),
            ("SOURCE", quote.provider, "STATUS", "ESTIMATED *" if quote.estimated else "OBSERVED"),
        )
        table = _table(len(rows), 4, headers=())
        table.setObjectName("rateSnapshot")
        table.horizontalHeader().hide()
        for row, values in enumerate(rows):
            _set_item(table, row, 0, values[0], AJAX_TEXT)
            _set_item(table, row, 1, values[1], AJAX_AMBER, right=True)
            _set_item(table, row, 2, values[2], AJAX_TEXT)
            _set_item(table, row, 3, values[3], AJAX_AMBER, right=True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setFixedHeight(len(rows) * 27 + 4)
        return table

    def _rate_history(self) -> QTableWidget:
        bars = self.data.history.bars[-12:][::-1]
        table = _table(max(len(bars), 1), 2, ("DATE", "YIELD %"))
        if bars:
            for row, bar in enumerate(bars):
                _set_item(table, row, 0, bar.timestamp.strftime("%d %b %Y"), AJAX_TEXT)
                _set_item(table, row, 1, fmt_percent(bar.close, 3), AJAX_AMBER, right=True)
        else:
            _set_item(table, 0, 0, "NO REAL HISTORY AVAILABLE", AJAX_MUTED)
            table.setSpan(0, 0, 1, 2)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.setFixedHeight(min(max(len(bars), 1), 12) * 27 + 31)
        return table

    def _methodology_text(self) -> str:
        quote = self.data.quote
        if quote.estimated:
            return (
                f"{quote.symbol} carries an asterisk because it is derived, not directly observed.\n\n"
                f"{quote.methodology}\n\n"
                f"SOURCES: {quote.provider}\n"
                f"REFERENCE TIMESTAMP: {quote.timestamp.strftime('%d %b %Y %H:%M UTC')}\n\n"
                "The estimate is shown only when a direct public observation is unavailable. "
                "It must not be treated as an executable market quote."
            )
        return (
            f"{quote.symbol} is a directly observed public series.\n\n"
            f"SOURCE: {quote.provider}\n"
            f"UNIT: PERCENT\n"
            f"OBSERVATION TIMESTAMP: {quote.timestamp.strftime('%d %b %Y %H:%M UTC')}\n\n"
            "No synthetic or mock value is used."
        )

    def _open_rate_context_menu(self, tabs: QTabWidget, table: QTableWidget, position) -> None:
        menu = QMenu(table)
        action = menu.addAction("OPEN METHODOLOGY")
        selected = menu.exec(table.viewport().mapToGlobal(position))
        if selected == action:
            tabs.setCurrentIndex(1)

    def _identity(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        name = self.data.profile.name or self.data.fundamentals.name or self.data.quote.name
        title = QLabel(f"{name.upper()}   {self.data.quote.symbol}")
        title.setStyleSheet(f"color:{AJAX_YELLOW};font-size:15px;font-weight:bold")
        layout.addWidget(title)
        profile = self.data.profile
        identity = "   |   ".join(
            value for value in (profile.exchange, profile.sector, profile.industry, profile.country) if value
        )
        line = QLabel(identity or "COMPANY PROFILE UNAVAILABLE")
        line.setStyleSheet(f"color:{AJAX_TEXT}")
        layout.addWidget(line)
        description_title = QLabel("BUSINESS DESCRIPTION")
        description_title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold;padding-top:5px")
        layout.addWidget(description_title)
        description = QPlainTextEdit()
        description.setObjectName("businessDescription")
        description.setPlainText(profile.description or "COMPANY DESCRIPTION UNAVAILABLE")
        description.setReadOnly(True)
        description.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        description.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        description.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        description.setFixedHeight(112)
        description.setStyleSheet(
            f"QPlainTextEdit#businessDescription {{"
            f"background:#080a0b;color:{AJAX_TEXT};border:1px solid {AJAX_BORDER};padding:7px;"
            "}"
        )
        layout.addWidget(description)
        return panel

    def _market_snapshot(self) -> QTableWidget:
        quote = self.data.quote
        change_color = AJAX_GREEN if (quote.change or 0) >= 0 else AJAX_RED
        rows = (
            ("LAST", _price(quote.price, quote.currency), "CHANGE", _signed(quote.change), change_color),
            ("OPEN", _price(quote.open_price, quote.currency), "PREV CLOSE", _price(quote.previous_close, quote.currency), AJAX_TEXT),
            ("DAY HIGH", _price(quote.day_high, quote.currency), "DAY LOW", _price(quote.day_low, quote.currency), AJAX_TEXT),
            ("52W HIGH", _price(quote.week_52_high, quote.currency), "52W LOW", _price(quote.week_52_low, quote.currency), AJAX_TEXT),
            ("BID", _price(quote.bid, quote.currency), "ASK", _price(quote.ask, quote.currency), AJAX_TEXT),
            ("VOLUME", fmt_number(quote.volume, 0), "CHANGE %", fmt_percent(quote.change_percent, signed=True), change_color),
        )
        table = _table(len(rows), 4, headers=())
        table.horizontalHeader().hide()
        for row, (left, left_value, right, right_value, color) in enumerate(rows):
            _set_item(table, row, 0, left, AJAX_TEXT)
            _set_item(table, row, 1, left_value, AJAX_AMBER, right=True)
            _set_item(table, row, 2, right, AJAX_TEXT)
            _set_item(table, row, 3, right_value, color, right=True)
        table.setFixedHeight(6 * 27 + 4)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _fundamental_grid(self) -> QGridLayout:
        f = self.data.fundamentals
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.addWidget(
            _metric_panel(
                "VALUATION",
                (
                    ("MARKET CAP", fmt_money(f.market_cap)),
                    ("ENTERPRISE VALUE", fmt_money(f.enterprise_value)),
                    ("P/E", fmt_number(f.pe)),
                    ("FORWARD P/E", fmt_number(f.forward_pe)),
                    ("EV / EBITDA", fmt_number(f.ev_ebitda)),
                    ("PRICE / BOOK", fmt_number(f.price_book)),
                    ("DIVIDEND YIELD", fmt_percent(f.dividend_yield)),
                    ("BETA", fmt_number(f.beta)),
                ),
            ),
            0,
            0,
        )
        grid.addWidget(
            _metric_panel(
                "FINANCIALS",
                (
                    ("REVENUE", fmt_money(f.revenue)),
                    ("REVENUE GROWTH", fmt_percent(f.revenue_growth, signed=True)),
                    ("EBITDA", fmt_money(f.ebitda)),
                    ("EBIT", fmt_money(f.ebit)),
                    ("NET INCOME", fmt_money(f.net_income)),
                    ("EPS", fmt_number(f.eps)),
                    ("FREE CASH FLOW", fmt_money(f.free_cash_flow)),
                    ("OPERATING CF", fmt_money(f.operating_cash_flow)),
                ),
            ),
            0,
            1,
        )
        grid.addWidget(
            _metric_panel(
                "PROFITABILITY / BALANCE SHEET",
                (
                    ("GROSS MARGIN", fmt_percent(f.gross_margin)),
                    ("OPERATING MARGIN", fmt_percent(f.operating_margin)),
                    ("NET MARGIN", fmt_percent(f.profit_margin)),
                    ("ROE", fmt_percent(f.roe)),
                    ("ROA", fmt_percent(f.roa)),
                    ("ROIC", fmt_percent(f.roic)),
                    ("TOTAL CASH", fmt_money(f.total_cash)),
                    ("NET DEBT", fmt_money(f.net_debt)),
                ),
            ),
            0,
            2,
        )
        return grid

    def _analyst_table(self) -> QTableWidget:
        analyst = self.data.analyst
        next_earnings = self.data.estimates.earnings_date
        rows = (
            ("RECOMMENDATION", analyst.recommendation or "--", "TARGET MEAN", _price(analyst.target_mean, analyst.currency)),
            ("ANALYSTS", str(analyst.analyst_count or "--"), "UPSIDE", fmt_percent(analyst.upside_percent, signed=True)),
            ("BUY / HOLD / SELL", f"{analyst.buy or 0} / {analyst.hold or 0} / {analyst.sell or 0}", "NEXT EARNINGS", next_earnings.strftime("%d %b %Y %H:%M UTC") if next_earnings else "--"),
        )
        table = _table(len(rows), 4, headers=())
        table.horizontalHeader().hide()
        for row, values in enumerate(rows):
            _set_item(table, row, 0, values[0], AJAX_TEXT)
            _set_item(table, row, 1, values[1], AJAX_YELLOW, right=True)
            _set_item(table, row, 2, values[2], AJAX_TEXT)
            _set_item(table, row, 3, values[3], AJAX_AMBER, right=True)
        table.setFixedHeight(len(rows) * 27 + 4)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _news_table(self) -> QTableWidget:
        table = _table(len(self.data.news) or 1, 3, ("TIME", "SOURCE", "HEADLINE"))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setProperty("newsItems", self.data.news)
        if self.data.news:
            for row, item in enumerate(self.data.news):
                _set_item(table, row, 0, item.timestamp.strftime("%H:%M"), AJAX_MUTED)
                _set_item(table, row, 1, item.source, AJAX_YELLOW)
                _set_item(table, row, 2, item.headline, AJAX_TEXT)
        else:
            _set_item(table, 0, 0, "--", AJAX_MUTED)
            _set_item(table, 0, 2, "NO RELATED HEADLINES AVAILABLE", AJAX_MUTED)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setFixedHeight(min(max(len(self.data.news), 1), 8) * 27 + 31)
        table.cellDoubleClicked.connect(self._open_news)
        return table

    @Slot(int, int)
    def _open_news(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.data.news):
            link = self.data.news[row].link.strip()
            if link.startswith(("https://", "http://")):
                open_external_url(link)


class FinancialStatementsWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, statements: FinancialStatements) -> None:
        super().__init__()
        self.statements = statements
        self.frequency = "ANNUAL" if statements.annual else "QUARTERLY"
        self.unit_mode = _preferred_statement_unit()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(self._controls())
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        root.addWidget(self.title)
        self.source = QLabel()
        self.source.setStyleSheet(f"color:{AJAX_MUTED};padding:2px 7px")
        root.addWidget(self.source)
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.verticalHeader().setMinimumSectionSize(27)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._field_context_menu)
        root.addWidget(self.table, 1)
        self._render()

    def _controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        statement_commands = (
            ("1) INCOME", "IS", StatementType.INCOME),
            ("2) BALANCE SHEET", "BS", StatementType.BALANCE_SHEET),
            ("3) CASH FLOW", "CF", StatementType.CASH_FLOW),
        )
        for label, command, statement_type in statement_commands:
            button = QPushButton(label)
            button.setObjectName("functionTab")
            button.setCheckable(True)
            button.setChecked(statement_type == self.statements.statement_type)
            button.clicked.connect(
                lambda _checked=False, value=command: self.command_requested.emit(
                    f"{self.statements.symbol} {value}"
                )
            )
            row.addWidget(button)
        row.addSpacing(12)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for frequency in ("ANNUAL", "QUARTERLY"):
            button = QPushButton(frequency)
            button.setCheckable(True)
            button.setChecked(frequency == self.frequency)
            button.clicked.connect(lambda _checked=False, value=frequency: self._set_frequency(value))
            group.addButton(button)
            row.addWidget(button)
        row.addSpacing(12)
        units_label = QLabel("UNITS")
        units_label.setStyleSheet(f"color:{AJAX_TEXT};padding:0 3px")
        row.addWidget(units_label)
        self.unit_selector = QComboBox()
        self.unit_selector.setObjectName("amberField")
        self.unit_selector.setMinimumWidth(120)
        self.unit_selector.blockSignals(True)
        for label, value in _STATEMENT_UNIT_OPTIONS:
            self.unit_selector.addItem(label, value)
        selected = self.unit_selector.findData(self.unit_mode)
        self.unit_selector.setCurrentIndex(max(selected, 0))
        self.unit_selector.blockSignals(False)
        self.unit_selector.currentIndexChanged.connect(self._set_unit_mode)
        row.addWidget(self.unit_selector)
        row.addStretch(1)
        current_command = {
            StatementType.INCOME: "IS",
            StatementType.BALANCE_SHEET: "BS",
            StatementType.CASH_FLOW: "CF",
        }[self.statements.statement_type]
        refresh = QPushButton("REFRESH DATA")
        refresh.clicked.connect(
            lambda: self.command_requested.emit(
                f"{self.statements.symbol} {current_command} REFRESH"
            )
        )
        row.addWidget(refresh)
        export = QPushButton("EXPORT XLSX")
        export.setObjectName("amberField")
        export.clicked.connect(
            lambda: self.command_requested.emit(f"{self.statements.symbol} XLS")
        )
        row.addWidget(export)
        audit = QPushButton("FLDS  AUDIT DATA")
        audit.clicked.connect(
            lambda: self.command_requested.emit(f"{self.statements.symbol} FLDS")
        )
        row.addWidget(audit)
        if self.statements.source_url.startswith(("https://", "http://")):
            source = QPushButton("OPEN FILING")
            source.clicked.connect(
                lambda: open_external_url(self.statements.source_url)
            )
            row.addWidget(source)
        return frame

    def _set_frequency(self, frequency: str) -> None:
        self.frequency = frequency
        self._render()

    def _set_unit_mode(self, index: int) -> None:
        value = self.unit_selector.itemData(index)
        self.unit_mode = str(value) if value in _STATEMENT_UNIT_DIVISORS or value == "AUTO" else "AUTO"
        app = QApplication.instance()
        if app is not None:
            app.setProperty("financialStatementUnit", self.unit_mode)
        self._render()

    def _render(self) -> None:
        names = {
            StatementType.INCOME: "INCOME STATEMENT",
            StatementType.BALANCE_SHEET: "BALANCE SHEET",
            StatementType.CASH_FLOW: "CASH FLOW STATEMENT",
        }
        periods = self.statements.annual if self.frequency == "ANNUAL" else self.statements.quarterly
        visible = periods[:8]
        self.title.setText(
            f"{self.statements.name.upper()}   {self.statements.symbol}   "
            f"{names[self.statements.statement_type]} / {self.frequency}"
        )
        metrics = ordered_statement_metrics(
            visible,
            self.statements.statement_type,
            self.statements.metric_order,
        )
        metric_groups = grouped_statement_metrics(
            metrics,
            self.statements.statement_type,
            self.statements.metric_sections,
        )
        display_unit, divisor = _statement_display_unit(visible, metrics, self.unit_mode)
        derived_note = "  |  * DERIVED FROM FILED CUMULATIVE VALUES" if any(
            period.derived for period in visible
        ) else ""
        auto_note = " (AUTO)" if self.unit_mode == "AUTO" else ""
        self.source.setText(
            f"CURRENCY {self.statements.currency or '--'}  |  "
            f"UNITS: {self.statements.currency or ''} {display_unit}{auto_note}  |  "
            "EPS / RATIOS: AS REPORTED  |  "
            f"{len(metrics)} LINE ITEMS  |  {self.statements.provider}  |  "
            f"{self.statements.quality}{derived_note}"
        )
        meta_rows = 3 if visible else 0
        grouped_rows = sum(len(group_metrics) + 1 for _title, group_metrics in metric_groups)
        grouped_rows += max(0, len(metric_groups) - 1)
        content_rows = grouped_rows
        self.table.clear()
        self.table.clearSpans()
        self.table.setRowCount(meta_rows + content_rows if visible else 1)
        self.table.setColumnCount(1 + len(visible))
        self.table.setHorizontalHeaderLabels(["LINE ITEM", *[period.period for period in visible]])
        if not visible:
            _set_item(self.table, 0, 0, "NO DATA OFFERED BY PROVIDER", AJAX_MUTED)
            return
        for column, period in enumerate(visible, start=1):
            _set_item(self.table, 0, column, period.end_date.isoformat() if period.end_date else "--", AJAX_MUTED, right=True)
            _set_item(self.table, 1, column, f"{period.source_form}{' / DERIVED' if period.derived else ''}" or "--", AJAX_MUTED, right=True)
            _set_item(self.table, 2, column, period.filed_date.isoformat() if period.filed_date else "--", AJAX_MUTED, right=True)
        _set_item(self.table, 0, 0, "PERIOD END", AJAX_MUTED)
        _set_item(self.table, 1, 0, "SOURCE FORM", AJAX_MUTED)
        _set_item(self.table, 2, 0, "FILED", AJAX_MUTED)
        row = meta_rows
        for group_index, (group_title, group_metrics) in enumerate(metric_groups):
            if group_index:
                self.table.setSpan(row, 0, 1, self.table.columnCount())
                self.table.setRowHeight(row, 9)
                row += 1
            _set_section_item(self.table, row, group_title)
            self.table.setSpan(row, 0, 1, self.table.columnCount())
            self.table.setRowHeight(row, 28)
            row += 1
            for metric in group_metrics:
                red = is_expense_or_outflow_metric(metric, self.statements.statement_type)
                label = self.statements.metric_labels.get(metric) or _humanize(metric)
                _set_item(self.table, row, 0, label.upper(), AJAX_TEXT)
                self.table.item(row, 0).setToolTip(label)
                self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, metric)
                for column, period in enumerate(visible, start=1):
                    value = period.values.get(metric)
                    value_color = AJAX_RED if red else AJAX_AMBER
                    _set_item(
                        self.table,
                        row,
                        column,
                        _statement_value(value, metric, divisor),
                        value_color,
                        right=True,
                    )
                    self.table.item(row, column).setData(Qt.ItemDataRole.UserRole, metric)
                row += 1
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    @Slot(object)
    def _field_context_menu(self, position: object) -> None:
        item = self.table.itemAt(position)
        metric = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not metric:
            return
        menu = QMenu(self.table)
        audit = menu.addAction("FLDS  OPEN FIELD SOURCE & METHODOLOGY")
        if menu.exec(self.table.viewport().mapToGlobal(position)) == audit:
            self.command_requested.emit(f"{self.statements.symbol} FLDS {metric}")


class FinancialAnalysisWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, analysis: FinancialAnalysis) -> None:
        super().__init__()
        self.analysis = analysis
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(self._controls())

        title = QLabel(f"{analysis.name.upper()}   {analysis.symbol}   FINANCIAL ANALYSIS")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        source = QLabel(
            f"CURRENCY {analysis.currency or '--'}  |  ACTUALS AND AVAILABLE CONSENSUS ONLY  |  "
            f"{analysis.provider}  |  {analysis.quality}"
        )
        source.setStyleSheet(f"color:{AJAX_MUTED};padding:2px 7px")
        root.addWidget(source)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(8, 5, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        actual_income = self._panel("INCOME STATEMENT / ACTUAL", "INCOME STATEMENT", "ACTUAL")
        if actual_income is not None:
            grid.addWidget(actual_income, 0, 0, 1, 2)
        for row, (title_text, category) in enumerate(
            (
                ("CASH FLOW / ACTUAL", "CASH FLOW"),
                ("BALANCE SHEET / ACTUAL", "BALANCE SHEET"),
                ("RETURNS / MARGINS", "RETURNS / MARGINS"),
                ("VALUATION", "VALUATION"),
            ),
            start=1,
        ):
            panel = self._panel(title_text, category, "ACTUAL")
            if panel is not None:
                grid.addWidget(panel, (row + 1) // 2, (row - 1) % 2)

        estimates = self._panel("CONSENSUS ESTIMATES", "INCOME STATEMENT", "ESTIMATE")
        if estimates is not None:
            grid.addWidget(estimates, 3, 0, 1, 2)
        grid.setRowStretch(4, 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        for label, command in (
            ("1) DES", "DES"),
            ("2) GP", "GP"),
            ("3) FA", "FA"),
            ("4) EE", "EE"),
            ("5) ANR", "ANR"),
            ("6) RV", "RV"),
            ("7) FILINGS", "FILINGS"),
            ("8) NEWS", "NEWS"),
            ("IS", "IS"),
            ("BS", "BS"),
            ("CF", "CF"),
            ("FLDS", "FLDS"),
            ("XLS", "XLS"),
        ):
            button = QPushButton(label)
            button.setObjectName("functionTab")
            button.setCheckable(command == "FA")
            button.setChecked(command == "FA")
            button.clicked.connect(
                lambda _checked=False, value=command: self.command_requested.emit(
                    f"{self.analysis.symbol} {value}"
                )
            )
            row.addWidget(button)
        row.addStretch(1)
        return frame

    def _panel(self, title: str, category: str, status: str) -> QWidget | None:
        offered = [
            metric
            for metric in self.analysis.metrics.get(category, [])
            if metric.status == status and metric.value is not None
        ]
        if not offered:
            return None
        period_order = [
            period
            for period in self.analysis.periods
            if any(metric.period == period for metric in offered)
        ]
        names = list(dict.fromkeys(metric.name for metric in offered))
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        table = _table(len(names), 1 + len(period_order), ("METRIC", *period_order))
        table.setObjectName(f"analysis-{category.lower().replace(' ', '-')}")
        for row, name in enumerate(names):
            _set_item(table, row, 0, name.upper(), AJAX_TEXT)
            for column, period in enumerate(period_order, start=1):
                metric = next(
                    (
                        item
                        for item in offered
                        if item.name == name and item.period == period
                    ),
                    None,
                )
                value = _analysis_value(metric)
                color = _analysis_metric_color(metric, category)
                _set_item(table, row, column, value, color, right=True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table.setFixedHeight(len(names) * 27 + 32)
        layout.addWidget(table)
        return panel


class FinancialExportWorkspace(QWidget):
    def __init__(self, result: FinancialExportResult) -> None:
        super().__init__()
        self.result = result
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(10)
        title = QLabel(f"XLS   {result.symbol}   FINANCIAL STATEMENT EXPORT")
        title.setStyleSheet(f"color:{AJAX_YELLOW};font-size:16px;font-weight:bold")
        root.addWidget(title)
        status = QLabel("EXPORT COMPLETE")
        status.setStyleSheet(f"color:{AJAX_GREEN};font-weight:bold")
        root.addWidget(status)
        path = QLabel(str(result.path))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setStyleSheet(f"color:{AJAX_TEXT};padding:8px 0")
        root.addWidget(path)
        table = _table(len(result.sheet_names) + len(result.skipped), 2, ("WORKSHEET", "STATUS"))
        row = 0
        for name in result.sheet_names:
            _set_item(table, row, 0, name, AJAX_TEXT)
            _set_item(table, row, 1, "EXPORTED", AJAX_GREEN)
            row += 1
        for name in result.skipped:
            _set_item(table, row, 0, name, AJAX_TEXT)
            _set_item(table, row, 1, "NO PROVIDER DATA", AJAX_AMBER)
            row += 1
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(260)
        root.addWidget(table)
        actions = QHBoxLayout()
        open_file = QPushButton("OPEN WORKBOOK")
        open_file.setObjectName("amberField")
        open_file.clicked.connect(lambda: open_local_path(result.path))
        actions.addWidget(open_file)
        open_folder = QPushButton("OPEN FOLDER")
        open_folder.clicked.connect(lambda: open_local_path(result.path.parent))
        actions.addWidget(open_folder)
        save_copy = QPushButton("SAVE COPY AS...")
        save_copy.clicked.connect(self._save_copy)
        actions.addWidget(save_copy)
        actions.addStretch(1)
        root.addLayout(actions)
        note = QLabel("Only real or cached provider statements are exported; generated mock data is excluded.")
        note.setStyleSheet(f"color:{AJAX_MUTED}")
        root.addWidget(note)
        root.addStretch(1)

    def _save_copy(self) -> None:
        destination, _selected = QFileDialog.getSaveFileName(
            self,
            "Save financial workbook",
            str(Path.home() / "Downloads" / self.result.path.name),
            "Excel Workbook (*.xlsx)",
        )
        if destination:
            target = Path(destination)
            if target.suffix.lower() != ".xlsx":
                target = target.with_suffix(".xlsx")
            shutil.copy2(self.result.path, target)
            open_local_path(target.parent)


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _metric_panel(title: str, rows: tuple[tuple[str, str], ...]) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
    layout.addWidget(heading)
    table = _table(len(rows), 2, headers=())
    table.horizontalHeader().hide()
    for row, (name, value) in enumerate(rows):
        _set_item(table, row, 0, name, AJAX_TEXT)
        _set_item(table, row, 1, value, AJAX_AMBER, right=True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setFixedHeight(len(rows) * 27 + 4)
    layout.addWidget(table)
    return panel


def _table(rows: int, columns: int, headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(rows, columns)
    if headers:
        table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setShowGrid(True)
    table.setAlternatingRowColors(True)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setDefaultSectionSize(27)
    return table


def _set_item(
    table: QTableWidget,
    row: int,
    column: int,
    value: object,
    color: str,
    *,
    right: bool = False,
) -> None:
    item = QTableWidgetItem(str(value))
    item.setForeground(QColor(color))
    if right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    table.setItem(row, column, item)


def _set_section_item(table: QTableWidget, row: int, value: str) -> None:
    item = QTableWidgetItem(value)
    item.setForeground(QColor(AJAX_CYAN))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.setItem(row, 0, item)


def _humanize(value: str) -> str:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ")
    return " ".join(separated.upper().split())


_STATEMENT_UNIT_OPTIONS = (
    ("AUTO", "AUTO"),
    ("UNITS", "UNITS"),
    ("THOUSANDS", "THOUSANDS"),
    ("MILLIONS", "MILLIONS"),
    ("BILLIONS", "BILLIONS"),
    ("TRILLIONS", "TRILLIONS"),
)

_STATEMENT_UNIT_DIVISORS = {
    "UNITS": 1.0,
    "THOUSANDS": 1_000.0,
    "MILLIONS": 1_000_000.0,
    "BILLIONS": 1_000_000_000.0,
    "TRILLIONS": 1_000_000_000_000.0,
}


def _preferred_statement_unit() -> str:
    app = QApplication.instance()
    value = app.property("financialStatementUnit") if app is not None else None
    return str(value) if value in _STATEMENT_UNIT_DIVISORS or value == "AUTO" else "AUTO"


def _statement_display_unit(
    periods: list[FinancialPeriod],
    metrics: list[str],
    mode: str,
) -> tuple[str, float]:
    if mode in _STATEMENT_UNIT_DIVISORS:
        return mode, _STATEMENT_UNIT_DIVISORS[mode]
    values = [
        abs(value)
        for period in periods
        for metric in metrics
        if not _statement_metric_is_unscaled(metric)
        if isinstance((value := period.values.get(metric)), (int, float))
    ]
    maximum = max(values, default=0.0)
    # Financial statements conventionally use one table-wide scale. Millions
    # retain useful detail for large issuers without mixing M/B/T suffixes.
    effective = "MILLIONS" if maximum >= 1_000_000 else "THOUSANDS" if maximum >= 1_000 else "UNITS"
    return effective, _STATEMENT_UNIT_DIVISORS[effective]


def _statement_metric_is_unscaled(metric: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", metric.lower())
    return normalized.endswith(("eps", "ratio", "ratios", "margin", "margins", "percentage", "percent", "yield")) or any(
        token in normalized
        for token in (
            "pershare",
            "taxrate",
            "returnon",
        )
    )


def _statement_value(value: float | None, metric: str, divisor: float) -> str:
    if value is None:
        return "--"
    if _statement_metric_is_unscaled(metric):
        return fmt_number(value, 2)
    return fmt_number(value / divisor, 2)


def _analysis_value(metric: FinancialMetric | None) -> str:
    if metric is None or metric.value is None:
        return "--"
    if metric.unit == "percent":
        return fmt_percent(metric.value)
    if metric.unit == "multiple" or metric.name == "EPS":
        return fmt_number(metric.value)
    return fmt_money(metric.value)


def _analysis_metric_color(metric: FinancialMetric | None, category: str) -> str:
    if metric is None:
        return AJAX_MUTED
    statement_type = {
        "INCOME STATEMENT": StatementType.INCOME,
        "CASH FLOW": StatementType.CASH_FLOW,
    }.get(category)
    if statement_type and is_expense_or_outflow_metric(metric.name, statement_type):
        return AJAX_RED
    return AJAX_AMBER


def _price(value: float | None, currency: str) -> str:
    return f"{fmt_number(value, 2)} {currency}" if value is not None else "--"


def _signed(value: float | None) -> str:
    return f"{value:+,.2f}" if value is not None else "--"
