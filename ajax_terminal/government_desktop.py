from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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
    AJAX_BACKGROUND,
    AJAX_BORDER,
    AJAX_CYAN,
    AJAX_GREEN,
    AJAX_GRID,
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
)
from ajax_terminal.charts.widgets.web_chart import EChartsWidget
from ajax_terminal.country_registry import COUNTRY_REGISTRY
from ajax_terminal.instruments import INSTRUMENT_REGISTRY, InstrumentRegistry
from ajax_terminal.models.instrument import Instrument
from ajax_terminal.models.quote import DataQuality, PriceHistory, Quote
from ajax_terminal.services.market_service import MarketService


REGION_ORDER = ("AMERICAS", "EMEA", "ASIA-PACIFIC")
COUNTRY_ORDER = (
    "US", "CA", "MX",
    "DE", "GB", "FR", "IT", "ES", "CH", "NO", "SE", "PL", "ZA",
    "JP", "AU", "NZ", "KR",
)
REGION_ALIASES = {
    "AMERICAS": "AMERICAS",
    "AMER": "AMERICAS",
    "EMEA": "EMEA",
    "EUROPE": "EMEA",
    "EU": "EMEA",
    "ASIA": "ASIA-PACIFIC",
    "APAC": "ASIA-PACIFIC",
    "ASIA-PACIFIC": "ASIA-PACIFIC",
}
GLOBAL_ALIASES = {"", "ALL", "GLOBAL", "WORLD"}


@dataclass(frozen=True, slots=True)
class GovernmentBondObservation:
    symbol: str
    country_code: str
    country_name: str
    region: str
    tenor: str
    name: str
    yield_pct: float | None
    change_bp: float | None
    previous_yield: float | None
    spread_to_ust_bp: float | None
    range_low: float | None
    range_high: float | None
    range_position: float | None
    provider: str
    quality: DataQuality
    frequency: str
    timestamp: datetime
    estimated: bool = False
    methodology: str = ""


@dataclass(frozen=True, slots=True)
class GovernmentBondsLoad:
    scope: str
    title: str
    mode: str
    observations: tuple[GovernmentBondObservation, ...]
    reference_yield: float | None
    loaded_at: datetime

    @property
    def available(self) -> tuple[GovernmentBondObservation, ...]:
        return tuple(item for item in self.observations if item.yield_pct is not None)


def load_government_bonds(
    tokens: tuple[str, ...] = (),
    *,
    market: MarketService | None = None,
    registry: InstrumentRegistry = INSTRUMENT_REGISTRY,
) -> GovernmentBondsLoad:
    return asyncio.run(_load_government_bonds(tokens, market or MarketService(), registry))


async def _load_government_bonds(
    tokens: tuple[str, ...],
    market: MarketService,
    registry: InstrumentRegistry,
) -> GovernmentBondsLoad:
    scope, title, mode, instruments = _resolve_universe(tokens, registry)
    if not instruments:
        raise ValueError(f"No registered sovereign benchmarks are available for {scope}")

    symbols = [instrument.symbol for instrument in instruments]
    quote_symbols = list(symbols)
    if mode == "world" and "US10Y" not in quote_symbols and registry.get("US10Y") is not None:
        quote_symbols.append("US10Y")

    quotes_task = asyncio.create_task(market.government_quotes(quote_symbols))
    histories_task = asyncio.gather(
        *(_safe_history(market, symbol) for symbol in symbols)
    )
    quotes, histories = await asyncio.gather(quotes_task, histories_task)
    return build_government_load(
        scope,
        title,
        mode,
        instruments,
        quotes,
        histories,
    )


async def _safe_history(market: MarketService, symbol: str) -> PriceHistory:
    try:
        return await market.history(symbol, "1Y", "1d", allow_mock=False)
    except Exception:
        return PriceHistory(
            symbol=symbol,
            period="1Y",
            interval="1d",
            bars=[],
            provider="UNAVAILABLE",
            quality=DataQuality.UNAVAILABLE,
        )


def _resolve_universe(
    tokens: tuple[str, ...],
    registry: InstrumentRegistry,
) -> tuple[str, str, str, list[Instrument]]:
    target = tokens[0].strip().upper() if tokens else ""
    registered = registry.get(target) if target else None
    if registered is not None and registered.instrument_type == "GOVT_BENCHMARK":
        return registered.symbol, registered.name.upper(), "benchmark", [registered]

    if target in GLOBAL_ALIASES:
        instruments = [
            item for item in registry.government_benchmarks() if item.symbol.endswith("10Y")
        ]
        return "WORLD", "WORLD BOND MARKETS / GLOBAL 10Y", "world", _sort_world(instruments)

    region = REGION_ALIASES.get(target)
    if region is not None:
        instruments = [
            item
            for item in registry.government_benchmarks()
            if item.symbol.endswith("10Y") and _region_for_country(item.country) == region
        ]
        return region, f"WORLD BOND MARKETS / {region}", "world", _sort_world(instruments)

    profile = COUNTRY_REGISTRY.resolve(target)
    country = profile.iso2 if profile is not None else target
    instruments = registry.government_benchmarks(country)
    if instruments:
        country_name = profile.name if profile is not None else country
        return country, f"{country_name.upper()} GOVERNMENT CURVE", "curve", _sort_curve(instruments)
    raise ValueError(f"Unknown sovereign market: {target or '--'}")


def build_government_load(
    scope: str,
    title: str,
    mode: str,
    instruments: list[Instrument],
    quotes: list[Quote],
    histories: list[PriceHistory],
) -> GovernmentBondsLoad:
    quote_by_symbol = {quote.symbol: quote for quote in quotes}
    history_by_symbol = {history.symbol: history for history in histories}
    reference = quote_by_symbol.get("US10Y")
    reference_yield = reference.price if reference is not None else None
    observations = tuple(
        _observation(
            instrument,
            quote_by_symbol.get(instrument.symbol),
            history_by_symbol.get(instrument.symbol),
            reference_yield,
        )
        for instrument in instruments
    )
    return GovernmentBondsLoad(
        scope=scope,
        title=title,
        mode=mode,
        observations=observations,
        reference_yield=reference_yield,
        loaded_at=datetime.now(timezone.utc),
    )


def _observation(
    instrument: Instrument,
    quote: Quote | None,
    history: PriceHistory | None,
    reference_yield: float | None,
) -> GovernmentBondObservation:
    bars = history.bars if history is not None else []
    closes = [bar.close for bar in bars]
    yield_pct = quote.price if quote is not None and quote.price is not None else (closes[-1] if closes else None)
    previous = quote.previous_close if quote is not None else None
    change = quote.change if quote is not None else None
    if change is None and len(closes) > 1:
        change = closes[-1] - closes[-2]
    if previous is None and yield_pct is not None and change is not None:
        previous = yield_pct - change
    change_bp = change * 100.0 if change is not None else None
    range_values = [*closes]
    if yield_pct is not None:
        range_values.append(yield_pct)
    low = min(range_values) if range_values else None
    high = max(range_values) if range_values else None
    position = None
    if yield_pct is not None and low is not None and high is not None:
        position = 0.5 if high == low else max(0.0, min(1.0, (yield_pct - low) / (high - low)))
    profile = COUNTRY_REGISTRY.resolve(instrument.country)
    provider = quote.provider if quote is not None and quote.price is not None else (history.provider if history is not None else "UNAVAILABLE")
    quality = quote.quality if quote is not None and quote.price is not None else (history.quality if history is not None else DataQuality.UNAVAILABLE)
    timestamp = quote.timestamp if quote is not None and quote.price is not None else (history.timestamp if history is not None else datetime.now(timezone.utc))
    spread = None
    if yield_pct is not None and reference_yield is not None:
        spread = (yield_pct - reference_yield) * 100.0
    return GovernmentBondObservation(
        symbol=instrument.symbol,
        country_code=instrument.country,
        country_name=profile.name if profile is not None else instrument.country,
        region=_region_for_country(instrument.country),
        tenor=_tenor(instrument.symbol, instrument.country),
        name=instrument.name,
        yield_pct=yield_pct,
        change_bp=change_bp,
        previous_yield=previous,
        spread_to_ust_bp=spread,
        range_low=low,
        range_high=high,
        range_position=position,
        provider=provider,
        quality=quality,
        frequency="MTH" if "FRED / OECD" in provider.upper() else "DLY",
        timestamp=timestamp,
        estimated=bool(quote.estimated) if quote is not None else False,
        methodology=quote.methodology if quote is not None else "",
    )


def build_government_chart_option(model: GovernmentBondsLoad) -> dict[str, object]:
    if model.mode == "curve":
        available = [item for item in model.observations if item.yield_pct is not None]
        return {
            "backgroundColor": AJAX_BACKGROUND,
            "animation": False,
            "textStyle": {"fontFamily": "Consolas, monospace", "fontSize": 13, "color": AJAX_TEXT},
            "tooltip": {"trigger": "axis", "backgroundColor": "#111417", "borderColor": AJAX_BORDER, "textStyle": {"color": AJAX_TEXT}},
            "grid": {"left": 54, "right": 24, "top": 22, "bottom": 42},
            "xAxis": {
                "type": "category",
                "name": "TENOR",
                "nameTextStyle": {"color": AJAX_AMBER},
                "data": [item.tenor for item in available],
                "axisLine": {"lineStyle": {"color": AJAX_BORDER}},
                "axisLabel": {"color": AJAX_TEXT},
            },
            "yAxis": {
                "type": "value",
                "scale": True,
                "name": "YIELD %",
                "nameTextStyle": {"color": AJAX_AMBER},
                "axisLine": {"show": True, "lineStyle": {"color": AJAX_BORDER}},
                "axisLabel": {"color": AJAX_TEXT, "formatter": "{value}%"},
                "splitLine": {"show": True, "lineStyle": {"color": AJAX_GRID, "type": "dashed"}},
            },
            "series": [{
                "name": "YIELD",
                "type": "line",
                "data": [
                    {"name": item.symbol, "value": round(item.yield_pct, 3)}
                    for item in available
                ],
                "symbol": "diamond",
                "symbolSize": 8,
                "lineStyle": {"color": AJAX_AMBER, "width": 2},
                "itemStyle": {"color": AJAX_AMBER},
            }],
        }

    available = sorted(model.available, key=lambda item: item.yield_pct or 0.0)
    return {
        "backgroundColor": AJAX_BACKGROUND,
        "animation": False,
        "textStyle": {"fontFamily": "Consolas, monospace", "fontSize": 12, "color": AJAX_TEXT},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "backgroundColor": "#111417", "borderColor": AJAX_BORDER, "textStyle": {"color": AJAX_TEXT}},
        "grid": {"left": 62, "right": 52, "top": 12, "bottom": 32},
        "xAxis": {
            "type": "value",
            "name": "YIELD %",
            "nameTextStyle": {"color": AJAX_AMBER},
            "axisLine": {"show": True, "lineStyle": {"color": AJAX_BORDER}},
            "axisLabel": {"color": AJAX_TEXT, "formatter": "{value}%"},
            "splitLine": {"show": True, "lineStyle": {"color": AJAX_GRID, "type": "dashed"}},
        },
        "yAxis": {
            "type": "category",
            "data": [item.symbol for item in available],
            "axisLine": {"lineStyle": {"color": AJAX_BORDER}},
            "axisLabel": {"color": AJAX_TEXT},
        },
        "series": [{
            "name": "YIELD",
            "type": "bar",
            "barMaxWidth": 16,
            "data": [
                {
                    "name": item.symbol,
                    "value": round(item.yield_pct, 3),
                    "itemStyle": {"color": _movement_color(item.change_bp)},
                }
                for item in available
            ],
            "label": {"show": True, "position": "right", "color": AJAX_AMBER, "formatter": "{c}%"},
        }],
    }


class GovernmentBondsWorkspace(QWidget):
    command_requested = Signal(str)
    ready = Signal()

    def __init__(self, model: GovernmentBondsLoad) -> None:
        super().__init__()
        self.model = model
        self._by_symbol = {item.symbol: item for item in model.observations}
        self._by_tenor = {item.tenor: item for item in model.observations}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)
        root.addWidget(self._function_strip())
        root.addWidget(self._market_strip())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._matrix_panel())
        splitter.addWidget(self._visual_panel())
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([1120, 650])
        root.addWidget(splitter, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        super().resizeEvent(event)
        if not hasattr(self, "table"):
            return
        compact = self.width() < 1_300
        for column in (5, 6, 7):
            self.table.setColumnHidden(column, compact)

    def _function_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(1)
        title = QLabel("WB  WORLD BOND MARKETS")
        title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold;padding-right:10px")
        row.addWidget(title)
        buttons = (
            ("1) WORLD", "GOVT", self.model.scope == "WORLD"),
            ("2) AMER", "GOVT AMERICAS", self.model.scope == "AMERICAS"),
            ("3) EMEA", "GOVT EMEA", self.model.scope == "EMEA"),
            ("4) APAC", "GOVT APAC", self.model.scope == "ASIA-PACIFIC"),
        )
        for label, command, active in buttons:
            row.addWidget(
                _button(
                    label,
                    lambda _checked=False, value=command: self.command_requested.emit(value),
                    active=active,
                )
            )
        row.addStretch(1)
        row.addWidget(_button("USD CURVE", lambda: self.command_requested.emit("CURVE USD")))
        row.addWidget(_button("MAP 10Y", lambda: self.command_requested.emit("MAP 10Y")))
        refresh = "GOVT" if self.model.scope == "WORLD" else f"GOVT {self.model.scope}"
        row.addWidget(_button("REFRESH", lambda: self.command_requested.emit(refresh), amber=True))
        return frame

    def _market_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("metricsStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(18)
        available = self.model.available
        moves = [item.change_bp for item in available if item.change_bp is not None]
        row.addWidget(_metric("SCOPE", self.model.scope))
        row.addWidget(_metric("MARKETS", f"{len(available)}/{len(self.model.observations)}"))
        row.addWidget(_metric("UST 10Y", _yield(self.model.reference_yield)))
        row.addWidget(_metric("YIELDS UP", str(sum(value > 0 for value in moves)), AJAX_GREEN))
        row.addWidget(_metric("YIELDS DOWN", str(sum(value < 0 for value in moves)), AJAX_RED))
        row.addStretch(1)
        observed = max((item.timestamp for item in available), default=self.model.loaded_at)
        row.addWidget(_metric("AS OF", observed.astimezone().strftime("%d %b %Y %H:%M"), AJAX_TEXT))
        return frame

    def _matrix_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        heading = QLabel("SOVEREIGN BENCHMARK MATRIX")
        heading.setObjectName("panelHeader")
        layout.addWidget(heading)
        self.table = QTableWidget()
        self.table.setObjectName("governmentMatrix")
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.cellDoubleClicked.connect(self._open_row)
        if self.model.mode == "world":
            self._populate_world_table()
        else:
            self._populate_curve_table()
        layout.addWidget(self.table, 1)
        note = QLabel(
            "DOUBLE-CLICK A BENCHMARK FOR GP  |  CHG = LATEST OBSERVED MOVE; FREQ IDENTIFIES DAILY OR MONTHLY DATA  |  SPREADS USE LATEST AVAILABLE UST"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{AJAX_MUTED};padding:3px 7px")
        layout.addWidget(note)
        panel.setMinimumWidth(570)
        return panel

    def _populate_world_table(self) -> None:
        headers = ("COUNTRY", "GOVIE", "YIELD", "CHG BP", "SPRD/UST", "1Y LOW", "1Y HIGH", "RANGE", "DATA")
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        rows: list[GovernmentBondObservation | str] = []
        for region in REGION_ORDER:
            selected = [item for item in self.model.observations if item.region == region]
            if selected:
                rows.append(region)
                rows.extend(selected)
        self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            if isinstance(entry, str):
                self.table.setSpan(row, 0, 1, len(headers))
                item = _item(entry, AJAX_CYAN)
                item.setBackground(QColor("#111417"))
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.table.setItem(row, 0, item)
                self.table.setRowHeight(row, 24)
                continue
            self._set_world_row(row, entry)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 82)
        self.table.clearSelection()

    def _set_world_row(self, row: int, item: GovernmentBondObservation) -> None:
        values = (
            item.country_name.upper(),
            item.symbol,
            _yield(item.yield_pct, item.estimated),
            _signed(item.change_bp, 1),
            _signed(item.spread_to_ust_bp, 0),
            _yield(item.range_low),
            _yield(item.range_high),
            _range_bar(item.range_position),
            f"{item.frequency} {item.quality}",
        )
        for column, value in enumerate(values):
            color = AJAX_TEXT
            if column in {2, 4, 5, 6}:
                color = AJAX_AMBER
            elif column == 3:
                color = _movement_color(item.change_bp)
            elif column == 7:
                color = AJAX_CYAN
            elif column == 8 and item.quality == DataQuality.UNAVAILABLE:
                color = AJAX_MUTED
            cell = _item(value, color, right=column in {2, 3, 4, 5, 6})
            cell.setData(Qt.ItemDataRole.UserRole, item.symbol)
            cell.setToolTip(_tooltip(item))
            self.table.setItem(row, column, cell)

    def _populate_curve_table(self) -> None:
        headers = ("TENOR", "BENCHMARK", "YIELD", "CHG BP", "PREVIOUS", "1Y LOW", "1Y HIGH", "RANGE", "SOURCE / DATA")
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self.model.observations))
        for row, item in enumerate(self.model.observations):
            values = (
                item.tenor,
                item.name.upper(),
                _yield(item.yield_pct, item.estimated),
                _signed(item.change_bp, 1),
                _yield(item.previous_yield),
                _yield(item.range_low),
                _yield(item.range_high),
                _range_bar(item.range_position),
                f"{item.provider} / {item.frequency} {item.quality}",
            )
            for column, value in enumerate(values):
                color = AJAX_TEXT
                if column in {0, 2, 4, 5, 6}:
                    color = AJAX_AMBER
                elif column == 3:
                    color = _movement_color(item.change_bp)
                elif column == 7:
                    color = AJAX_CYAN
                cell = _item(value, color, right=column in {2, 3, 4, 5, 6})
                cell.setData(Qt.ItemDataRole.UserRole, item.symbol)
                cell.setToolTip(_tooltip(item))
                self.table.setItem(row, column, cell)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.clearSelection()

    def _visual_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("chartPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        header = QFrame()
        header.setObjectName("viewStrip")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(7, 2, 7, 2)
        heading = "YIELD CURVE" if self.model.mode == "curve" else "GLOBAL 10Y YIELD COMPARISON"
        header_row.addWidget(_plain_label(heading, AJAX_TEXT, bold=True))
        header_row.addStretch(1)
        header_row.addWidget(_plain_label("YIELD %", AJAX_AMBER, bold=True))
        layout.addWidget(header)
        self.chart = EChartsWidget()
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart.country_clicked.connect(self._chart_clicked)
        self.chart.loadFinished.connect(lambda _ok: self.ready.emit())
        self.chart.set_option(build_government_chart_option(self.model), events=True)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self._pulse_panel())
        panel.setMinimumWidth(320)
        return panel

    def _pulse_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("terminalPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 4, 7, 5)
        layout.setSpacing(2)
        layout.addWidget(_plain_label("MARKET PULSE", AJAX_CYAN, bold=True))
        available = list(self.model.available)
        if not available:
            layout.addWidget(_plain_label("NO VERIFIED YIELD OBSERVATIONS", AJAX_MUTED))
            return panel
        yields = [item.yield_pct for item in available if item.yield_pct is not None]
        ranked = sorted(available, key=lambda item: item.yield_pct or 0.0)
        moves = [item for item in available if item.change_bp is not None]
        median = sorted(yields)[len(yields) // 2]
        pulse = (
            ("LOWEST", f"{ranked[0].symbol}  {_yield(ranked[0].yield_pct)}"),
            ("HIGHEST", f"{ranked[-1].symbol}  {_yield(ranked[-1].yield_pct)}"),
            ("MEDIAN", _yield(median)),
            ("LARGEST MOVE", _largest_move(moves)),
            ("COVERAGE", f"{len(available)} VERIFIED / {len(self.model.observations)} TOTAL"),
        )
        for label, value in pulse:
            line = QFrame()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(_plain_label(label, AJAX_MUTED))
            row.addStretch(1)
            row.addWidget(_plain_label(value, AJAX_AMBER))
            layout.addWidget(line)
        return panel

    @Slot(int, int)
    def _open_row(self, row: int, column: int) -> None:
        cell = self.table.item(row, column) or self.table.item(row, 0)
        symbol = cell.data(Qt.ItemDataRole.UserRole) if cell is not None else ""
        if isinstance(symbol, str) and symbol in self._by_symbol:
            self.command_requested.emit(f"GP {symbol} 1Y 1D")

    @Slot(str)
    def _chart_clicked(self, name: str) -> None:
        item = self._by_symbol.get(name) or self._by_tenor.get(name)
        if item is not None:
            self.command_requested.emit(f"GP {item.symbol} 1Y 1D")


def _sort_world(instruments: list[Instrument]) -> list[Instrument]:
    order = {region: index for index, region in enumerate(REGION_ORDER)}
    country_order = {country: index for index, country in enumerate(COUNTRY_ORDER)}
    return sorted(
        instruments,
        key=lambda item: (
            order.get(_region_for_country(item.country), 99),
            country_order.get(item.country, 999),
            item.country,
        ),
    )


def _sort_curve(instruments: list[Instrument]) -> list[Instrument]:
    return sorted(instruments, key=lambda item: _tenor_years(_tenor(item.symbol, item.country)))


def _region_for_country(country: str) -> str:
    profile = COUNTRY_REGISTRY.resolve(country)
    if profile is None:
        return "EMEA"
    if profile.region == "AMERICAS":
        return "AMERICAS"
    if profile.region == "ASIA":
        return "ASIA-PACIFIC"
    return "EMEA"


def _tenor(symbol: str, country: str) -> str:
    return symbol.removeprefix(country) or symbol


def _tenor_years(tenor: str) -> float:
    match = re.fullmatch(r"(\d+)([MY])", tenor.upper())
    if match is None:
        return 10_000.0
    value = float(match.group(1))
    return value / 12.0 if match.group(2) == "M" else value


def _yield(value: float | None, estimated: bool = False) -> str:
    if value is None:
        return "--"
    return f"{value:.3f}%{'*' if estimated else ''}"


def _signed(value: float | None, decimals: int) -> str:
    return "--" if value is None else f"{value:+.{decimals}f}"


def _range_bar(position: float | None, width: int = 10) -> str:
    if position is None:
        return "--"
    marker = min(width - 1, max(0, round(position * (width - 1))))
    return "[" + "-" * marker + "|" + "-" * (width - marker - 1) + "]"


def _movement_color(value: float | None) -> str:
    if value is None:
        return AJAX_AMBER
    if value > 0:
        return AJAX_GREEN
    if value < 0:
        return AJAX_RED
    return AJAX_TEXT


def _largest_move(items: list[GovernmentBondObservation]) -> str:
    if not items:
        return "--"
    item = max(items, key=lambda value: abs(value.change_bp or 0.0))
    return f"{item.symbol}  {_signed(item.change_bp, 1)} BP"


def _tooltip(item: GovernmentBondObservation) -> str:
    observed = item.timestamp.astimezone().strftime("%d %b %Y %H:%M %Z")
    details = [item.name, f"SOURCE: {item.provider}", f"DATA: {item.quality} / {item.frequency}", f"AS OF: {observed}"]
    if item.estimated:
        details.append(f"ESTIMATED: {item.methodology or 'DERIVED VALUE'}")
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


def _plain_label(text: str, color: str, *, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{color};font-weight:{'bold' if bold else 'normal'}")
    return label


def _item(value: object, color: str = AJAX_TEXT, *, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value))
    item.setForeground(QColor(color))
    alignment = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    return item
