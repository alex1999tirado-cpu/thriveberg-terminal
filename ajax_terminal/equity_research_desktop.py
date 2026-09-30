from __future__ import annotations

import asyncio
from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Callable, Iterable

from PySide6.QtCore import Qt, Signal, Slot
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
    AJAX_YELLOW,
)
from ajax_terminal.desktop_security import open_external_url
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CorporateEvent,
    DividendAnalysis,
    EstimateSet,
    RelativeValuation,
    ScreenerPage,
)
from ajax_terminal.models.filing import FilingCollection
from ajax_terminal.models.quote import Quote
from ajax_terminal.services.equity_research_service import EquityResearchService, parse_screener_filters
from ajax_terminal.services.filings_service import FilingsService
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.workstation import SavedScreenStore
from ajax_terminal.utils.formatting import fmt_money, fmt_number, fmt_percent, fmt_timestamp


@dataclass(slots=True)
class ResearchLoad:
    model: Any
    quote: Quote | None = None
    active_function: str = ""


def _run_security_load(
    symbol: str,
    loader: Callable[[EquityResearchService], Any],
    *,
    active_function: str,
) -> ResearchLoad:
    async def load() -> ResearchLoad:
        market = MarketService()
        research = EquityResearchService(market)
        model, quote = await asyncio.gather(loader(research), market.quote(symbol))
        return ResearchLoad(model, quote, active_function)

    return asyncio.run(load())


def load_relative_valuation(symbol: str, peers: list[str] | None = None) -> ResearchLoad:
    return _run_security_load(
        symbol,
        lambda service: service.relative_valuation(symbol, peers),
        active_function="RV",
    )


def load_estimates(symbol: str) -> ResearchLoad:
    return _run_security_load(symbol, lambda service: service.estimates(symbol), active_function="EE")


def load_analyst_consensus(symbol: str) -> ResearchLoad:
    return _run_security_load(
        symbol,
        lambda service: service.analyst_consensus(symbol),
        active_function="ANR",
    )


def load_dividends(symbol: str) -> ResearchLoad:
    return _run_security_load(symbol, lambda service: service.dividends(symbol), active_function="DVD")


def load_events(symbol: str) -> ResearchLoad:
    return _run_security_load(symbol, lambda service: service.events(symbol), active_function="EVT")


def load_filings(symbol: str, forms: tuple[str, ...], active_function: str) -> ResearchLoad:
    async def load() -> ResearchLoad:
        market = MarketService()
        filings = FilingsService(market.cache)
        model, quote = await asyncio.gather(
            filings.filings(symbol, forms=forms),
            market.quote(symbol),
        )
        return ResearchLoad(model, quote, active_function)

    return asyncio.run(load())


def load_screener(tokens: tuple[str, ...]) -> ResearchLoad:
    async def load() -> ResearchLoad:
        market = MarketService()
        filters = parse_screener_filters(tokens)
        page = await EquityResearchService(market).screener(filters)
        return ResearchLoad(page, active_function="EQS")

    return asyncio.run(load())


class ResearchWorkspace(QWidget):
    command_requested = Signal(str)

    FUNCTIONS = (
        ("1) DES", "DES"),
        ("2) GP", "GP"),
        ("3) FA", "FA"),
        ("4) EE", "EE"),
        ("5) ANR", "ANR"),
        ("6) RV", "RV"),
        ("7) DVD", "DVD"),
        ("8) EVT", "EVT"),
        ("9) FILINGS", "FILINGS"),
        ("FLDS", "FLDS"),
    )

    def __init__(self, symbol: str, active_function: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.active_function = active_function
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(2)
        self.root.addWidget(self._function_strip())

    def _function_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        for label, command in self.FUNCTIONS:
            button = QPushButton(label)
            button.setObjectName("functionTab")
            button.setCheckable(True)
            button.setChecked(command == self.active_function or (command == "FILINGS" and self.active_function in {"10K", "10Q"}))
            button.clicked.connect(
                lambda _checked=False, value=command: self.command_requested.emit(f"{self.symbol} {value}")
            )
            row.addWidget(button)
        row.addStretch(1)
        return frame

    def add_heading(self, title: str, detail: str = "") -> None:
        heading = QLabel(title)
        heading.setObjectName("researchHeading")
        heading.setStyleSheet(f"color:{AJAX_YELLOW};font-size:15px;font-weight:bold;padding:8px 12px 2px")
        self.root.addWidget(heading)
        if detail:
            subheading = QLabel(detail)
            subheading.setStyleSheet(f"color:{AJAX_TEXT};padding:0 12px 5px")
            self.root.addWidget(subheading)

    def add_source(self, provider: str, quality: object, timestamp: object, message: str = "") -> None:
        if message:
            note = QLabel(message)
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{AJAX_AMBER};padding:5px 12px")
            self.root.addWidget(note)
        source = QLabel(f"{provider}  |  {quality}  |  {fmt_timestamp(timestamp)}")
        source.setStyleSheet(f"color:{AJAX_MUTED};padding:3px 12px 7px")
        self.root.addWidget(source)


class RelativeValuationWorkspace(ResearchWorkspace):
    HEADERS = (
        "SYMBOL",
        "COMPANY",
        "PRICE",
        "MKT CAP",
        "P/E",
        "FWD P/E",
        "EV/EBITDA",
        "P/B",
        "REV GROWTH",
        "OP MARGIN",
        "ROE",
        "DIV YIELD",
    )

    def __init__(self, valuation: RelativeValuation) -> None:
        super().__init__(valuation.symbol, "RV")
        self.valuation = valuation
        mode = "AUTOMATIC INDUSTRY PEERS" if valuation.automatic else "MANUAL PEER SET"
        basis = " / ".join(value for value in (valuation.peer_sector, valuation.peer_industry) if value)
        self.add_heading(f"RV  {valuation.symbol}  RELATIVE VALUATION", f"{mode}  |  PEER BASIS  {basis or 'USER SELECTED'}")
        self.root.addWidget(self._peer_editor())
        self.table = _data_table(self.HEADERS)
        self._populate()
        self.table.cellDoubleClicked.connect(self._open_peer)
        self.root.addWidget(self.table, 1)
        self.add_source(valuation.provider, valuation.quality, valuation.timestamp, valuation.message)

    def _peer_editor(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("researchControlStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 3, 12, 3)
        label = QLabel("PEER SET")
        label.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
        row.addWidget(label)
        self.peer_input = QLineEdit()
        self.peer_input.setPlaceholderText("TICKERS SEPARATED BY SPACES; BLANK = AUTOMATIC INDUSTRY PEERS")
        if not self.valuation.automatic:
            self.peer_input.setText(" ".join(item.symbol for item in self.valuation.peers if item.symbol != self.symbol))
        row.addWidget(self.peer_input, 1)
        apply_button = QPushButton("APPLY")
        apply_button.setObjectName("amberButton")
        apply_button.clicked.connect(self._apply_peers)
        row.addWidget(apply_button)
        automatic = QPushButton("AUTO")
        automatic.clicked.connect(lambda: self.command_requested.emit(f"{self.symbol} RV"))
        row.addWidget(automatic)
        return frame

    def _populate(self) -> None:
        rows = self.valuation.peers
        self.table.setRowCount(len(rows) + (2 if rows else 0))
        for row, peer in enumerate(rows):
            values = (
                (peer.symbol, None),
                (peer.name or "--", None),
                (fmt_number(peer.price), peer.price),
                (fmt_money(peer.market_cap), peer.market_cap),
                (fmt_number(peer.pe), peer.pe),
                (fmt_number(peer.forward_pe), peer.forward_pe),
                (fmt_number(peer.ev_ebitda), peer.ev_ebitda),
                (fmt_number(peer.price_book), peer.price_book),
                (fmt_percent(peer.revenue_growth, signed=True), peer.revenue_growth),
                (fmt_percent(peer.operating_margin), peer.operating_margin),
                (fmt_percent(peer.roe), peer.roe),
                (fmt_percent(peer.dividend_yield), peer.dividend_yield),
            )
            for column, (text, numeric) in enumerate(values):
                item = _item(text, numeric=numeric, right=column >= 2)
                if peer.symbol == self.symbol:
                    item.setForeground(QColor(AJAX_YELLOW if column < 2 else AJAX_TEXT))
                    item.setBackground(QColor("#302506"))
                self.table.setItem(row, column, item)
        accessors: tuple[tuple[str, Callable[[Iterable[float]], float]], ...] = (("MEAN", mean), ("MEDIAN", median))
        fields = (
            None,
            None,
            "price",
            "market_cap",
            "pe",
            "forward_pe",
            "ev_ebitda",
            "price_book",
            "revenue_growth",
            "operating_margin",
            "roe",
            "dividend_yield",
        )
        for offset, (label, aggregate) in enumerate(accessors):
            row = len(rows) + offset
            self.table.setItem(row, 0, _item(label, color=AJAX_TEXT))
            self.table.setItem(row, 1, _item("PEER GROUP", color=AJAX_MUTED))
            for column, field in enumerate(fields[2:], start=2):
                numbers = [getattr(peer, field) for peer in rows if getattr(peer, field) is not None]
                value = aggregate(numbers) if numbers else None
                text = (
                    fmt_money(value)
                    if field == "market_cap"
                    else fmt_percent(value, signed=field == "revenue_growth")
                    if field in {"revenue_growth", "operating_margin", "roe", "dividend_yield"}
                    else fmt_number(value)
                )
                self.table.setItem(row, column, _item(text, numeric=value, right=True, color=AJAX_MUTED))
        widths = (92, 220, 92, 104, 74, 88, 98, 72, 108, 104, 82, 96)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    @Slot()
    def _apply_peers(self) -> None:
        peers = " ".join(self.peer_input.text().upper().replace(",", " ").split())
        command = f"{self.symbol} RV {peers}".strip()
        self.command_requested.emit(command)

    @Slot(int, int)
    def _open_peer(self, row: int, _column: int) -> None:
        if row < len(self.valuation.peers):
            self.command_requested.emit(f"{self.valuation.peers[row].symbol} DES")


class EstimatesWorkspace(ResearchWorkspace):
    HEADERS = ("METRIC", "PERIOD", "END DATE", "CONSENSUS", "LOW", "HIGH", "YEAR AGO", "GROWTH", "ANALYSTS", "REV 7D", "REV 30D")

    def __init__(self, estimates: EstimateSet) -> None:
        super().__init__(estimates.symbol, "EE")
        earnings = estimates.earnings_date.strftime("%d %b %Y %H:%M UTC") if estimates.earnings_date else "--"
        self.add_heading(f"EE  {estimates.name.upper()}  {estimates.symbol}", f"NEXT EARNINGS  {earnings}  |  CURRENCY  {estimates.currency or '--'}")
        table = _data_table(self.HEADERS)
        table.setRowCount(max(len(estimates.estimates), 1))
        if estimates.estimates:
            for row, estimate in enumerate(estimates.estimates):
                money = estimate.metric.upper() == "REVENUE"
                values = (
                    estimate.metric.upper(),
                    estimate.period,
                    estimate.end_date.isoformat() if estimate.end_date else "--",
                    fmt_money(estimate.average) if money else fmt_number(estimate.average),
                    fmt_money(estimate.low) if money else fmt_number(estimate.low),
                    fmt_money(estimate.high) if money else fmt_number(estimate.high),
                    fmt_money(estimate.year_ago) if money else fmt_number(estimate.year_ago),
                    fmt_percent(estimate.growth_percent, signed=True),
                    str(estimate.analyst_count) if estimate.analyst_count is not None else "--",
                    fmt_percent(estimate.revision_7d, signed=True),
                    fmt_percent(estimate.revision_30d, signed=True),
                )
                numeric = (None, None, None, estimate.average, estimate.low, estimate.high, estimate.year_ago, estimate.growth_percent, estimate.analyst_count, estimate.revision_7d, estimate.revision_30d)
                for column, text in enumerate(values):
                    color = _change_color(numeric[column]) if column in {7, 9, 10} else AJAX_TEXT
                    table.setItem(row, column, _item(text, numeric=numeric[column], right=column >= 3, color=color))
        else:
            table.setItem(0, 0, _item("NO CONSENSUS ESTIMATES AVAILABLE", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(table, 1)
        self.add_source(estimates.provider, estimates.quality, estimates.timestamp)


class AnalystWorkspace(ResearchWorkspace):
    def __init__(self, consensus: AnalystConsensus) -> None:
        super().__init__(consensus.symbol, "ANR")
        self.add_heading(f"ANR  {consensus.name.upper()}  {consensus.symbol}", "ANALYST RECOMMENDATIONS AND PRICE TARGETS")
        snapshot = _data_table(("MEASURE", "VALUE", "MEASURE", "VALUE"))
        metrics = (
            ("RECOMMENDATION", consensus.recommendation or "--", None),
            ("SCORE", fmt_number(consensus.recommendation_score), consensus.recommendation_score),
            ("ANALYSTS", str(consensus.analyst_count or "--"), consensus.analyst_count),
            ("CURRENT PRICE", fmt_number(consensus.current_price), consensus.current_price),
            ("TARGET LOW", fmt_number(consensus.target_low), consensus.target_low),
            ("TARGET MEAN", fmt_number(consensus.target_mean), consensus.target_mean),
            ("TARGET MEDIAN", fmt_number(consensus.target_median), consensus.target_median),
            ("TARGET HIGH", fmt_number(consensus.target_high), consensus.target_high),
            ("MEAN UPSIDE", fmt_percent(consensus.upside_percent, signed=True), consensus.upside_percent),
            ("CURRENCY", consensus.currency or "--", None),
        )
        snapshot.setRowCount((len(metrics) + 1) // 2)
        for index, (label, value, numeric) in enumerate(metrics):
            row, pair = divmod(index, 2)
            column = pair * 2
            snapshot.setItem(row, column, _item(label, color=AJAX_TEXT))
            value_color = _change_color(numeric) if label == "MEAN UPSIDE" else AJAX_YELLOW
            snapshot.setItem(row, column + 1, _item(value, numeric=numeric, right=True, color=value_color))
        snapshot.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        snapshot.setFixedHeight(snapshot.rowCount() * 28 + 31)
        self.root.addWidget(snapshot)
        distribution = _data_table(("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL", "TOTAL"))
        distribution.setRowCount(1)
        values = (consensus.strong_buy, consensus.buy, consensus.hold, consensus.sell, consensus.strong_sell)
        for column, value in enumerate((*values, consensus.analyst_count)):
            distribution.setItem(0, column, _item(str(value) if value is not None else "--", numeric=value, right=True))
        distribution.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        distribution.setFixedHeight(52)
        self.root.addWidget(_section("RECOMMENDATION DISTRIBUTION"))
        self.root.addWidget(distribution)
        self.root.addStretch(1)
        self.add_source(consensus.provider, consensus.quality, consensus.timestamp)


class DividendsWorkspace(ResearchWorkspace):
    def __init__(self, dividends: DividendAnalysis) -> None:
        super().__init__(dividends.symbol, "DVD")
        self.add_heading(f"DVD  {dividends.name.upper()}  {dividends.symbol}", "DIVIDEND SNAPSHOT AND PAYMENT HISTORY")
        summary = _data_table(("INDICATED RATE", "YIELD", "PAYOUT RATIO", "5Y AVG YIELD", "EX-DIV DATE", "PAYMENT DATE"))
        summary.setRowCount(1)
        summary_values = (
            (fmt_number(dividends.indicated_rate, 4), dividends.indicated_rate),
            (fmt_percent(dividends.yield_percent), dividends.yield_percent),
            (fmt_percent(dividends.payout_ratio_percent), dividends.payout_ratio_percent),
            (fmt_percent(dividends.five_year_average_yield), dividends.five_year_average_yield),
            (dividends.ex_dividend_date.isoformat() if dividends.ex_dividend_date else "--", None),
            (dividends.payment_date.isoformat() if dividends.payment_date else "--", None),
        )
        for column, (text, numeric) in enumerate(summary_values):
            summary.setItem(0, column, _item(text, numeric=numeric, right=True, color=AJAX_YELLOW))
        summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        summary.setFixedHeight(52)
        self.root.addWidget(summary)
        history = _data_table(("EX-DIV DATE", "AMOUNT", "CURRENCY", "YEAR TOTAL", "YOY GROWTH"))
        records = sorted(dividends.records, key=lambda item: item.ex_date, reverse=True)
        yearly: dict[int, float] = {}
        for record in records:
            yearly[record.ex_date.year] = yearly.get(record.ex_date.year, 0.0) + record.amount
        history.setRowCount(max(len(records), 1))
        if records:
            for row, record in enumerate(records):
                year_total = yearly[record.ex_date.year]
                previous = yearly.get(record.ex_date.year - 1)
                growth = (year_total / previous - 1.0) * 100.0 if previous else None
                values = (
                    (record.ex_date.isoformat(), None),
                    (fmt_number(record.amount, 4), record.amount),
                    (record.currency or dividends.currency or "--", None),
                    (fmt_number(year_total, 4), year_total),
                    (fmt_percent(growth, signed=True), growth),
                )
                for column, (text, numeric) in enumerate(values):
                    color = _change_color(growth) if column == 4 else AJAX_TEXT
                    history.setItem(row, column, _item(text, numeric=numeric, right=column in {1, 3, 4}, color=color))
        else:
            history.setItem(0, 0, _item("NO DIVIDEND RECORDS AVAILABLE", color=AJAX_MUTED))
        history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(_section("PAYMENT HISTORY"))
        self.root.addWidget(history, 1)
        self.add_source(dividends.provider, dividends.quality, dividends.timestamp)


class EventsWorkspace(ResearchWorkspace):
    def __init__(self, symbol: str, events: list[CorporateEvent]) -> None:
        super().__init__(symbol, "EVT")
        self.events = events
        self.add_heading(f"EVT  {symbol}  CORPORATE EVENTS", "CONFIRMED AND ESTIMATED COMPANY DATES")
        table = _data_table(("DATE / TIME", "SYMBOL", "COMPANY", "EVENT", "DETAIL", "STATUS", "DATA"))
        table.setRowCount(max(len(events), 1))
        if events:
            for row, event in enumerate(events):
                values = (
                    event.event_date.strftime("%d %b %Y %H:%M"),
                    event.symbol,
                    event.company,
                    event.event_type,
                    event.detail or "--",
                    "ESTIMATE" if event.estimated else "CONFIRMED",
                    str(event.quality),
                )
                for column, text in enumerate(values):
                    color = AJAX_YELLOW if column == 3 else AJAX_TEXT
                    table.setItem(row, column, _item(text, color=color))
        else:
            table.setItem(0, 0, _item("NO EVENTS SUPPLIED FOR THIS SECURITY", color=AJAX_MUTED))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(table, 1)


class FilingsWorkspace(ResearchWorkspace):
    def __init__(self, collection: FilingCollection, active_function: str) -> None:
        super().__init__(collection.symbol, active_function)
        self.collection = collection
        self.add_heading(
            f"{active_function}  {collection.company_name.upper()}  {collection.symbol}",
            f"{collection.jurisdiction} REGULATORY FILINGS  |  {collection.provider}",
        )
        controls = QFrame()
        controls.setObjectName("researchControlStrip")
        row = QHBoxLayout(controls)
        row.setContentsMargins(12, 3, 12, 3)
        for label, command in (("ALL FILINGS", "FILINGS"), ("ANNUAL", "10K"), ("QUARTERLY", "10Q")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(command == active_function)
            button.clicked.connect(lambda _checked=False, value=command: self.command_requested.emit(f"{self.symbol} {value}"))
            row.addWidget(button)
        row.addStretch(1)
        if collection.portal_url:
            portal = QPushButton("REGULATOR PORTAL")
            portal.clicked.connect(lambda: open_external_url(collection.portal_url))
            row.addWidget(portal)
        self.root.addWidget(controls)
        self.table = _data_table(("FILED", "REPORT PERIOD", "FORM", "DESCRIPTION", "ACCESSION / ID", "JURISDICTION", "DOCUMENT"))
        self.table.setRowCount(max(len(collection.filings), 1))
        if collection.filings:
            for table_row, filing in enumerate(collection.filings):
                values = (
                    filing.filing_date.isoformat(),
                    filing.report_date.isoformat() if filing.report_date else "--",
                    filing.form,
                    filing.description or filing.primary_document or "--",
                    filing.accession_number or "--",
                    filing.jurisdiction,
                    "OPEN",
                )
                for column, text in enumerate(values):
                    color = AJAX_AMBER if column == 6 else AJAX_YELLOW if column == 2 else AJAX_TEXT
                    self.table.setItem(table_row, column, _item(text, color=color))
        else:
            self.table.setItem(0, 0, _item("NO FILINGS RETURNED BY THE REGULATORY SOURCE", color=AJAX_MUTED))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_document)
        self.root.addWidget(self.table, 1)
        self.add_source(collection.provider, collection.quality, collection.timestamp, collection.message)

    @Slot(int, int)
    def _open_document(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.collection.filings):
            open_external_url(self.collection.filings[row].document_url)


class ScreenerWorkspace(QWidget):
    command_requested = Signal(str)

    HEADERS = ("SYMBOL", "NAME", "COUNTRY", "SECTOR", "LAST", "CHG %", "MKT CAP", "P/E", "FWD P/E", "DIV YIELD", "ROE", "ROIC", "REV GROWTH", "OP MARGIN", "VOLUME")
    SORT_FIELDS = (
        "symbol",
        "name",
        "country",
        "sector",
        "price",
        "change_percent",
        "market_cap",
        "pe",
        "forward_pe",
        "dividend_yield",
        "roe",
        "roic",
        "revenue_growth",
        "operating_margin",
        "volume",
    )

    def __init__(self, page: ScreenerPage, store: SavedScreenStore | None = None) -> None:
        super().__init__()
        self.page = page
        self.store = store or SavedScreenStore()
        self._results = list(page.results)
        self._sort_column: int | None = None
        self._sort_ascending = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        controls = QFrame()
        controls.setObjectName("viewStrip")
        row = QHBoxLayout(controls)
        row.setContentsMargins(8, 2, 8, 2)
        row.addWidget(QLabel("EQS  FILTERS"))
        self.filters = QLineEdit(" ".join(f"{item.field}{item.operator}{item.value:g}" if isinstance(item.value, float) else f"{item.field}{item.operator}{item.value}" for item in page.filters))
        self.filters.setPlaceholderText("EXAMPLE: MARKETCAP>10B PE<20 COUNTRY=US")
        self.filters.returnPressed.connect(self._apply)
        row.addWidget(self.filters, 1)
        apply_button = QPushButton("RUN SCREEN")
        apply_button.setObjectName("amberButton")
        apply_button.clicked.connect(self._apply)
        row.addWidget(apply_button)
        root.addWidget(controls)
        saved = QFrame()
        saved.setObjectName("researchControlStrip")
        saved_row = QHBoxLayout(saved)
        saved_row.setContentsMargins(8, 2, 8, 2)
        saved_row.setSpacing(2)
        saved_row.addWidget(QLabel("PRESETS"))
        for label, query in (
            ("LARGE CAP", "MARKETCAP>10B"),
            ("VALUE", "MARKETCAP>2B PE<15"),
            ("QUALITY", "MARKETCAP>2B ROE>15 MARGIN>12"),
            ("INCOME", "MARKETCAP>2B DIVYIELD>3"),
            ("GROWTH", "MARKETCAP>2B REVENUEGROWTH>15"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=query: self.command_requested.emit(f"EQS {value}")
            )
            saved_row.addWidget(button)
        saved_row.addSpacing(12)
        self.saved_selector = QComboBox()
        self.saved_selector.setMinimumWidth(160)
        self.saved_selector.addItem("SAVED SCREENS")
        for name, query in self.store.list():
            self.saved_selector.addItem(name, query)
        saved_row.addWidget(self.saved_selector)
        open_saved = QPushButton("OPEN")
        open_saved.clicked.connect(self._open_saved)
        saved_row.addWidget(open_saved)
        self.screen_name = QLineEdit()
        self.screen_name.setPlaceholderText("SCREEN NAME")
        self.screen_name.setMaximumWidth(150)
        saved_row.addWidget(self.screen_name)
        save_screen = QPushButton("SAVE")
        save_screen.clicked.connect(self._save_screen)
        saved_row.addWidget(save_screen)
        delete_screen = QPushButton("DELETE")
        delete_screen.clicked.connect(self._delete_screen)
        saved_row.addWidget(delete_screen)
        saved_row.addStretch(1)
        root.addWidget(saved)
        title = QLabel(f"EQS  EQUITY SCREENING  |  UNIVERSE  {page.universe}  |  {len(page.results)} RESULTS")
        title.setStyleSheet(f"color:{AJAX_YELLOW};font-weight:bold;padding:7px 12px")
        root.addWidget(title)
        self.table = _data_table(self.HEADERS)
        self._populate_results()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by_column)
        self.table.cellDoubleClicked.connect(self._open_result)
        root.addWidget(self.table, 1)
        source = QLabel(f"{page.provider}  |  {page.quality}  |  {fmt_timestamp(page.timestamp)}  |  {page.message}")
        source.setStyleSheet(f"color:{AJAX_MUTED};padding:4px 12px")
        root.addWidget(source)

    @Slot()
    def _apply(self) -> None:
        self.command_requested.emit(f"EQS {self.filters.text().strip()}".strip())

    @Slot()
    def _open_saved(self) -> None:
        query = self.saved_selector.currentData()
        if query:
            self.command_requested.emit(f"EQS {query}")

    @Slot()
    def _save_screen(self) -> None:
        name = self.screen_name.text().strip()
        if name:
            self.store.save(name, self.filters.text())
            self.command_requested.emit(f"EQS {self.filters.text().strip()}".strip())

    @Slot()
    def _delete_screen(self) -> None:
        if self.saved_selector.currentIndex() > 0:
            self.store.delete(self.saved_selector.currentText())
            self.command_requested.emit(f"EQS {self.filters.text().strip()}".strip())

    def _populate_results(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(max(len(self._results), 1))
        if not self._results:
            self.table.setItem(0, 0, _item("NO SECURITIES MATCHED OR DATA IS UNAVAILABLE", color=AJAX_MUTED))
            return
        for table_row, result in enumerate(self._results):
            fields = (
                (result.symbol, None),
                (result.name, None),
                (result.country, None),
                (result.sector, None),
                (fmt_number(result.price), result.price),
                (fmt_percent(result.change_percent, signed=True), result.change_percent),
                (fmt_money(result.market_cap), result.market_cap),
                (fmt_number(result.pe), result.pe),
                (fmt_number(result.forward_pe), result.forward_pe),
                (fmt_percent(result.dividend_yield), result.dividend_yield),
                (fmt_percent(result.roe), result.roe),
                (fmt_percent(result.roic), result.roic),
                (fmt_percent(result.revenue_growth, signed=True), result.revenue_growth),
                (fmt_percent(result.operating_margin), result.operating_margin),
                (fmt_money(result.volume), result.volume),
            )
            for column, (text, numeric) in enumerate(fields):
                color = _change_color(numeric) if column in {5, 12} else AJAX_TEXT
                self.table.setItem(table_row, column, _item(text, numeric=numeric, right=column >= 4, color=color))

    @Slot(int)
    def _sort_by_column(self, column: int) -> None:
        if not 0 <= column < len(self.SORT_FIELDS):
            return
        if self._sort_column == column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = column
            self._sort_ascending = True
        field = self.SORT_FIELDS[column]
        populated = [result for result in self._results if getattr(result, field) not in {None, ""}]
        missing = [result for result in self._results if getattr(result, field) in {None, ""}]

        def key(result: object) -> object:
            value = getattr(result, field)
            return value.casefold() if isinstance(value, str) else value

        populated.sort(key=key, reverse=not self._sort_ascending)
        self._results = populated + missing
        order = Qt.SortOrder.AscendingOrder if self._sort_ascending else Qt.SortOrder.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(column, order)
        self._populate_results()

    @Slot(int, int)
    def _open_result(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._results):
            self.command_requested.emit(f"{self._results[row].symbol} DES")


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _data_table(headers: tuple[str, ...]) -> QTableWidget:
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
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.horizontalHeader().setSectionsClickable(True)
    table.setSortingEnabled(False)
    return table


def _item(
    text: object,
    *,
    numeric: float | int | None = None,
    right: bool = False,
    color: str = AJAX_TEXT,
) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    if numeric is not None:
        item.setData(Qt.ItemDataRole.UserRole, float(numeric))
    item.setForeground(QColor(color))
    alignment = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    return item


def _change_color(value: float | int | None) -> str:
    if value is None:
        return AJAX_MUTED
    if value > 0:
        return AJAX_GREEN
    if value < 0:
        return AJAX_RED
    return AJAX_TEXT
