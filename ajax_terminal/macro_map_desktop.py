from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
)
from ajax_terminal.charts.widgets.web_chart import ThreeGlobeWidget
from ajax_terminal.country_registry import COUNTRY_REGISTRY, CountryRegistry
from ajax_terminal.models.macro import (
    CountryMacroSnapshot,
    CountryProfile,
    MacroMapDataset,
    MacroMapMetric,
    MacroObservation,
)
from ajax_terminal.services.macro_country_service import MacroCountryService, normalize_map_metric


METRIC_LABELS = {
    MacroMapMetric.GDP: "GDP GROWTH %",
    MacroMapMetric.CPI: "CPI %",
    MacroMapMetric.UNEMPLOYMENT: "UNEMPLOYMENT %",
    MacroMapMetric.POLICY_RATE: "POLICY RATE %",
    MacroMapMetric.SOVEREIGN_10Y: "10Y SOVEREIGN YIELD %",
    MacroMapMetric.EQUITY_YTD: "EQUITY YTD RETURN %",
}
METRIC_KEYS = {
    MacroMapMetric.GDP: "G",
    MacroMapMetric.CPI: "C",
    MacroMapMetric.UNEMPLOYMENT: "U",
    MacroMapMetric.POLICY_RATE: "R",
    MacroMapMetric.SOVEREIGN_10Y: "Y",
    MacroMapMetric.EQUITY_YTD: "E",
}
REGIONS = ("WORLD", "AMERICAS", "EUROPE", "ASIA", "EM", "DM")
MACRO_ROWS = (
    ("GDP", "GDP GROWTH"),
    ("CPI", "CPI"),
    ("CORE_CPI", "CORE CPI"),
    ("UNEMP", "UNEMPLOYMENT"),
    ("RATE", "POLICY RATE"),
    ("PMI_MFG", "PMI MANUFACTURING"),
    ("PMI_SVC", "PMI SERVICES"),
    ("RETAIL", "RETAIL SALES"),
    ("INDUSTRIAL", "INDUSTRIAL PROD."),
    ("DEBT_GDP", "DEBT / GDP"),
    ("CURRENT_ACCOUNT", "CURRENT ACCOUNT"),
)


@dataclass(slots=True)
class MacroMapLoad:
    dataset: MacroMapDataset
    region: str = "WORLD"
    selected_country: str = ""


def load_macro_map(tokens: tuple[str, ...]) -> MacroMapLoad:
    metric, region, profile = parse_macro_map_args(tokens)
    service = MacroCountryService()
    dataset = asyncio.run(service.world_dataset(metric, region))
    return MacroMapLoad(dataset, region, profile.iso3 if profile else "")


def parse_macro_map_args(tokens: tuple[str, ...]) -> tuple[MacroMapMetric, str, CountryProfile | None]:
    metric = MacroMapMetric.GDP
    region = "WORLD"
    country_tokens: list[str] = []
    for token in tokens:
        upper = token.upper()
        normalized = normalize_map_metric(upper)
        if upper in {"GDP", "GROWTH", "CPI", "INFLATION", "UNEMP", "UNEMPLOYMENT", "RATE", "RATES", "POLICY", "10Y", "YIELD", "EQUITY", "INDEX"}:
            metric = normalized
        elif upper in REGIONS:
            region = upper
        else:
            country_tokens.append(token)
    selected = " ".join(country_tokens)
    profile = COUNTRY_REGISTRY.resolve(selected) if selected else None
    if selected and profile is None:
        matches = COUNTRY_REGISTRY.search(selected, 1)
        profile = matches[0] if matches else None
    return metric, region, profile


class _TaskSignals(QObject):
    loaded = Signal(int, object)
    failed = Signal(int, str)


class _SnapshotTask(QRunnable):
    def __init__(self, serial: int, iso3: str, factory: Callable[[], MacroCountryService]) -> None:
        super().__init__()
        self.serial = serial
        self.iso3 = iso3
        self.factory = factory
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = asyncio.run(self.factory().get_snapshot(self.iso3))
            self.signals.loaded.emit(self.serial, snapshot)
        except Exception as exc:
            self.signals.failed.emit(self.serial, str(exc))


class MacroMapWorkspace(QWidget):
    command_requested = Signal(str)
    ready = Signal()

    def __init__(
        self,
        loaded: MacroMapLoad,
        *,
        registry: CountryRegistry = COUNTRY_REGISTRY,
        service_factory: Callable[[], MacroCountryService] = MacroCountryService,
    ) -> None:
        super().__init__()
        self.dataset = loaded.dataset
        self.region = loaded.region
        self.registry = registry
        self.service_factory = service_factory
        self.selected: CountryProfile | None = None
        self._snapshot_serial = 0
        self._tasks: set[_SnapshotTask] = set()
        initial_profile = self.registry.resolve(loaded.selected_country) if loaded.selected_country else None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)
        root.addWidget(self._metric_strip())
        root.addWidget(self._search_strip())

        body = QFrame()
        body.setObjectName("terminalPanel")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(1)
        self.chart = ThreeGlobeWidget()
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart.country_clicked.connect(self._map_clicked)
        self.chart.loadFinished.connect(self._chart_loaded)
        self.chart.set_globe(
            build_globe_payload(
                self.dataset,
                self.region,
                selected_name=initial_profile.map_name if initial_profile is not None else "",
            ),
            _world_geojson(),
        )
        body_layout.addWidget(self.chart, 1)
        self.panel = self._country_panel()
        body_layout.addWidget(self.panel)
        root.addWidget(body, 1)
        self._install_shortcuts()

        if initial_profile is not None:
            self._select_profile(initial_profile)

    def _metric_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(1)
        title = QLabel("GLOBAL ECONOMIC MAP")
        title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold;padding-right:12px")
        row.addWidget(title)
        for metric in MacroMapMetric:
            button = QPushButton(metric.value)
            button.setObjectName("amberButton" if metric == self.dataset.metric else "functionTab")
            button.setToolTip(f"{METRIC_LABELS[metric]} [{METRIC_KEYS[metric]}]")
            button.clicked.connect(lambda _checked=False, value=metric.value: self._change_metric(value))
            row.addWidget(button)
        row.addStretch(1)
        metric_label = QLabel(METRIC_LABELS[self.dataset.metric])
        metric_label.setStyleSheet(f"color:{AJAX_AMBER};font-weight:bold")
        row.addWidget(metric_label)
        return frame

    def _search_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("researchControlStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(2)
        region_label = QLabel("REGION")
        region_label.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
        row.addWidget(region_label)
        for region in REGIONS:
            button = QPushButton(region)
            button.setObjectName("amberButton" if region == self.region else "functionTab")
            button.clicked.connect(lambda _checked=False, value=region: self._change_region(value))
            row.addWidget(button)
        row.addStretch(1)
        search_label = QLabel("COUNTRY")
        search_label.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
        row.addWidget(search_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("NAME / ISO2 / ISO3")
        self.search.setFixedWidth(235)
        entries = sorted({value for country in self.registry.all() for value in (country.name, country.iso2, country.iso3)})
        completer = QCompleter(entries, self.search)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.search.setCompleter(completer)
        self.search.returnPressed.connect(self._search_country)
        row.addWidget(self.search)
        go = QPushButton("GO")
        go.setObjectName("amberButton")
        go.clicked.connect(self._search_country)
        row.addWidget(go)
        return frame

    def _country_panel(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("macroCountryPanel")
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        scroll.setMaximumWidth(450)
        scroll.setStyleSheet(f"QScrollArea#macroCountryPanel{{border:1px solid {AJAX_BORDER};border-right:0px;background:{AJAX_BACKGROUND}}}")
        content = QWidget()
        self.panel_layout = QVBoxLayout(content)
        self.panel_layout.setContentsMargins(10, 8, 10, 8)
        self.panel_layout.setSpacing(5)
        self.country_title = QLabel("SELECT A COUNTRY")
        self.country_title.setStyleSheet(f"color:{AJAX_AMBER};font-size:16px;font-weight:bold")
        self.panel_layout.addWidget(self.country_title)
        self.country_meta = QLabel("CLICK THE MAP OR SEARCH BY NAME / ISO")
        self.country_meta.setWordWrap(True)
        self.country_meta.setStyleSheet(f"color:{AJAX_MUTED}")
        self.panel_layout.addWidget(self.country_meta)
        self.panel_layout.addWidget(_section("MACRO"))
        self.macro_table = _panel_table(("INDICATOR", "VALUE", "PERIOD"), len(MACRO_ROWS))
        self.macro_table.setMinimumHeight(335)
        self.panel_layout.addWidget(self.macro_table)
        self.panel_layout.addWidget(_section("MARKETS"))
        self.market_table = _panel_table(("MARKET", "VALUE", "PERIOD"), 5)
        self.market_table.setMinimumHeight(170)
        self.panel_layout.addWidget(self.market_table)
        self.panel_layout.addWidget(_section("NEXT EVENTS"))
        self.events_table = _panel_table(("DATE", "EVENT", "CONS", "PREV"), 1)
        self.events_table.setMinimumHeight(95)
        self.panel_layout.addWidget(self.events_table)
        self.panel_layout.addWidget(_section("FUNCTIONS"))
        shortcuts = QFrame()
        shortcut_row = QGridLayout(shortcuts)
        shortcut_row.setContentsMargins(0, 0, 0, 0)
        shortcut_row.setSpacing(2)
        self.shortcut_buttons: dict[str, QPushButton] = {}
        for index, label in enumerate(("ECO", "RATES", "INDEX", "FX", "NEWS", "CAL")):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, value=label: self._run_shortcut(value))
            shortcut_row.addWidget(button, index // 3, index % 3)
            self.shortcut_buttons[label] = button
        self.panel_layout.addWidget(shortcuts)
        self.source_label = QLabel("NO COUNTRY SELECTED")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet(f"color:{AJAX_MUTED};padding-top:4px")
        self.panel_layout.addWidget(self.source_label)
        self.panel_layout.addStretch(1)
        scroll.setWidget(content)
        self._clear_tables()
        return scroll

    def _install_shortcuts(self) -> None:
        for metric, key in METRIC_KEYS.items():
            shortcut = QShortcut(QKeySequence(key), self.chart)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda value=metric.value: self._change_metric(value))
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(lambda: self.command_requested.emit("HOME"))

    @Slot(bool)
    def _chart_loaded(self, _ok: bool) -> None:
        if self.selected is not None:
            self.chart.select_country(self.selected.map_name)
        self.ready.emit()

    def _change_metric(self, metric: str) -> None:
        parts = ["MAP", metric]
        if self.region != "WORLD":
            parts.append(self.region)
        if self.selected is not None:
            parts.append(self.selected.iso3)
        self.command_requested.emit(" ".join(parts))

    def _change_region(self, region: str) -> None:
        self.command_requested.emit(f"MAP {self.dataset.metric.value} {region}")

    @Slot()
    def _search_country(self) -> None:
        query = self.search.text().strip()
        profile = self.registry.resolve(query)
        if profile is None:
            matches = self.registry.search(query, 1)
            profile = matches[0] if matches else None
        if profile is None:
            self.country_title.setText(query.upper() or "COUNTRY NOT FOUND")
            self.country_meta.setText("DATA UNAVAILABLE / COUNTRY NOT IN REGISTRY")
            return
        self._select_profile(profile)

    @Slot(str)
    def _map_clicked(self, map_name: str) -> None:
        profile = self.registry.resolve(map_name)
        if profile is None:
            self.selected = None
            self.chart.select_country(map_name)
            self.country_title.setText(map_name.upper())
            self.country_meta.setText("DATA UNAVAILABLE / COUNTRY NOT IN CURRENT REGISTRY")
            self.source_label.setText("NO VERIFIED DATA AVAILABLE")
            self._clear_tables()
            return
        self._select_profile(profile)

    def _select_profile(self, profile: CountryProfile) -> None:
        self.selected = profile
        self.search.setText(profile.name)
        self.chart.select_country(profile.map_name)
        self.country_title.setText(f"{profile.name.upper()}  |  {profile.iso3}")
        self.country_meta.setText(
            f"{profile.region}  |  {profile.currency}  |  {profile.central_bank}\nLOADING COUNTRY SNAPSHOT..."
        )
        self.source_label.setText("LOADING OFFICIAL MACRO AND MARKET DATA...")
        self._clear_tables(loading=True)
        self._update_shortcuts()
        self._snapshot_serial += 1
        task = _SnapshotTask(self._snapshot_serial, profile.iso3, self.service_factory)
        self._tasks.add(task)
        task.signals.loaded.connect(self._snapshot_loaded)
        task.signals.failed.connect(self._snapshot_failed)
        task.signals.loaded.connect(lambda _serial, _value, worker=task: self._tasks.discard(worker))
        task.signals.failed.connect(lambda _serial, _message, worker=task: self._tasks.discard(worker))
        QThreadPool.globalInstance().start(task)

    @Slot(int, object)
    def _snapshot_loaded(self, serial: int, model: object) -> None:
        if serial != self._snapshot_serial or not isinstance(model, CountryMacroSnapshot):
            return
        self._render_snapshot(model)

    @Slot(int, str)
    def _snapshot_failed(self, serial: int, message: str) -> None:
        if serial != self._snapshot_serial:
            return
        self.country_meta.setText(f"COUNTRY DATA ERROR\n{message}")
        self.source_label.setText("NO SUBSTITUTE OR MOCK DATA WAS SHOWN")
        self._clear_tables()

    def _render_snapshot(self, snapshot: CountryMacroSnapshot) -> None:
        profile = snapshot.profile
        self.country_title.setText(f"{profile.name.upper()}  |  {profile.iso3}")
        self.country_meta.setText(
            f"{profile.region}  |  {profile.currency}  |  {profile.central_bank}\n"
            f"MARKET {snapshot.market_status}"
        )
        for row, (code, label) in enumerate(MACRO_ROWS):
            self._set_observation_row(self.macro_table, row, label, snapshot.indicator(code))
        market_rows = (
            ("MAIN EQUITY INDEX", profile.main_equity_index or "N/A", None),
            ("EQUITY YTD", None, snapshot.indicator("EQUITY")),
            ("10Y YIELD", None, snapshot.indicator("10Y")),
            ("FX REFERENCE", profile.fx_reference or "N/A", None),
            ("FX YTD", None, snapshot.indicator("FX_YTD")),
        )
        for row, (label, plain, observation) in enumerate(market_rows):
            if plain is not None:
                self._set_plain_row(self.market_table, row, label, plain)
            else:
                self._set_observation_row(self.market_table, row, label, observation, signed=True)
        self.events_table.clearSpans()
        self.events_table.setRowCount(max(len(snapshot.events), 1))
        self.events_table.clearContents()
        if snapshot.events:
            for row, event in enumerate(snapshot.events[:5]):
                values = (
                    event.time.strftime("%d %b %H:%M") if event.time else "--",
                    event.event,
                    event.consensus or "--",
                    event.previous or "--",
                )
                for column, value in enumerate(values):
                    self.events_table.setItem(row, column, _item(value, AJAX_TEXT))
        else:
            self.events_table.setItem(0, 0, _item("NO VERIFIED UPCOMING EVENTS", AJAX_MUTED))
            self.events_table.setSpan(0, 0, 1, 4)
        sources = sorted({item.source for item in snapshot.indicators.values() if item.source})
        self.source_label.setText(
            f"SOURCES  {' / '.join(sources) if sources else 'UNAVAILABLE'}\n"
            "VALUES RETAIN THEIR OWN PERIOD AND DATA STATUS"
        )

    def _set_observation_row(
        self,
        table: QTableWidget,
        row: int,
        label: str,
        observation: MacroObservation | None,
        *,
        signed: bool = False,
    ) -> None:
        table.setItem(row, 0, _item(label, AJAX_CYAN))
        if observation is None or observation.value is None:
            table.setItem(row, 1, _item("N/A", AJAX_MUTED, right=True))
            table.setItem(row, 2, _item("--", AJAX_MUTED))
            return
        value = _format_value(observation, signed=signed)
        color = AJAX_TEXT
        if signed:
            color = AJAX_GREEN if observation.value > 0 else AJAX_RED if observation.value < 0 else AJAX_TEXT
        value_item = _item(value, color, right=True)
        value_item.setToolTip(f"{observation.source} | {observation.status}")
        period_item = _item(_compact_period(observation.period), AJAX_MUTED)
        period_item.setToolTip(f"{observation.source} | {observation.status}")
        table.setItem(row, 1, value_item)
        table.setItem(row, 2, period_item)

    def _set_plain_row(self, table: QTableWidget, row: int, label: str, value: str) -> None:
        table.setItem(row, 0, _item(label, AJAX_CYAN))
        table.setItem(row, 1, _item(value, AJAX_TEXT, right=True))
        table.setItem(row, 2, _item("--", AJAX_MUTED))

    def _clear_tables(self, *, loading: bool = False) -> None:
        for row, (_code, label) in enumerate(MACRO_ROWS):
            self._set_plain_row(self.macro_table, row, label, "..." if loading else "N/A")
        for row, label in enumerate(("MAIN EQUITY INDEX", "EQUITY YTD", "10Y YIELD", "FX REFERENCE", "FX YTD")):
            self._set_plain_row(self.market_table, row, label, "..." if loading else "N/A")
        self.events_table.clearSpans()
        self.events_table.setRowCount(1)
        self.events_table.clearContents()
        self.events_table.setItem(0, 0, _item("LOADING..." if loading else "N/A", AJAX_MUTED))
        self.events_table.setSpan(0, 0, 1, 4)

    def _update_shortcuts(self) -> None:
        profile = self.selected
        availability = {
            "ECO": profile is not None,
            "RATES": bool(profile and profile.iso2),
            "INDEX": bool(profile and profile.main_equity_index),
            "FX": bool(profile and profile.fx_reference),
            "NEWS": profile is not None,
            "CAL": profile is not None,
        }
        for label, enabled in availability.items():
            self.shortcut_buttons[label].setEnabled(enabled)

    def _run_shortcut(self, function: str) -> None:
        if self.selected is None:
            return
        profile = self.selected
        command = country_shortcuts(profile).get(function)
        if command and not command.endswith(" "):
            self.command_requested.emit(command)


def build_map_option(dataset: MacroMapDataset, region: str = "WORLD") -> dict[str, object]:
    label = METRIC_LABELS[dataset.metric]
    data = []
    numbers: list[float] = []
    for entry in dataset.values:
        observation = entry.observation
        value = observation.value if observation is not None else None
        if value is not None:
            numbers.append(value)
        data.append(
            {
                "name": entry.profile.map_name,
                "country": entry.profile.name,
                "iso3": entry.profile.iso3,
                "value": value,
                "displayValue": _format_value(observation, signed=dataset.metric in {MacroMapMetric.GDP, MacroMapMetric.EQUITY_YTD}) if observation else "N/A",
                "metricLabel": label,
                "period": observation.period if observation else "",
                "source": observation.source if observation else "",
                "status": observation.status if observation else "UNAVAILABLE",
            }
        )
    center, zoom = {
        "AMERICAS": ([-75, 12], 1.75),
        "EUROPE": ([16, 52], 4.0),
        "ASIA": ([96, 31], 2.1),
    }.get(region, ([5, 18], 1.08))
    return {
        "backgroundColor": AJAX_BACKGROUND,
        "animation": False,
        "textStyle": {"fontFamily": "Consolas, monospace", "fontSize": 13, "color": AJAX_TEXT},
        "tooltip": {
            "trigger": "item",
            "backgroundColor": "#0b0d0f",
            "borderColor": AJAX_BORDER,
            "borderWidth": 1,
            "padding": [7, 9],
            "textStyle": {"color": AJAX_TEXT, "fontFamily": "Consolas, monospace", "fontSize": 13},
        },
        "visualMap": {
            "type": "piecewise",
            "left": "center",
            "bottom": 8,
            "orient": "horizontal",
            "itemWidth": 24,
            "itemHeight": 9,
            "itemGap": 3,
            "textStyle": {"color": AJAX_TEXT, "fontFamily": "Consolas, monospace", "fontSize": 11},
            "pieces": build_visual_pieces(numbers, dataset.metric),
            "outOfRange": {"color": "#161a1d"},
        },
        "series": [
            {
                "type": "map",
                "map": "world",
                "roam": True,
                "selectedMode": "single",
                "center": center,
                "zoom": zoom,
                "left": 8,
                "right": 8,
                "top": 8,
                "bottom": 42,
                "scaleLimit": {"min": 0.8, "max": 8},
                "label": {"show": False},
                "itemStyle": {"areaColor": "#161a1d", "borderColor": "#535a60", "borderWidth": 0.65},
                "emphasis": {
                    "label": {"show": True, "color": "#ffffff", "fontSize": 12, "fontWeight": "bold"},
                    "itemStyle": {"areaColor": "#8a6500", "borderColor": AJAX_AMBER, "borderWidth": 1.2},
                },
                "select": {
                    "label": {"show": True, "color": "#050505", "fontSize": 12, "fontWeight": "bold"},
                    "itemStyle": {"areaColor": AJAX_AMBER, "borderColor": "#ffffff", "borderWidth": 1.1},
                },
                "data": data,
            }
        ],
    }


def build_globe_payload(
    dataset: MacroMapDataset,
    region: str = "WORLD",
    *,
    selected_name: str = "",
) -> dict[str, object]:
    option = build_map_option(dataset, region)
    center, latitude, distance = {
        "AMERICAS": (-82, 15, 3.15),
        "EUROPE": (14, 49, 3.15),
        "ASIA": (96, 27, 3.15),
    }.get(region, (8, 14, 3.15))
    return {
        "backgroundColor": AJAX_BACKGROUND,
        "metricLabel": METRIC_LABELS[dataset.metric],
        "data": option["series"][0]["data"],
        "pieces": option["visualMap"]["pieces"],
        "view": {"longitude": center, "latitude": latitude, "distance": distance},
        "selectedName": selected_name,
    }


def country_shortcuts(profile: CountryProfile) -> dict[str, str]:
    news_target = profile.name.upper() if " " not in profile.name else profile.iso3
    return {
        "ECO": f"ECO {profile.iso2}",
        "RATES": f"RATES {profile.iso2}",
        "INDEX": f"INDEX {profile.main_equity_index}",
        "FX": f"FX {profile.fx_reference}",
        "NEWS": f"NEWS {news_target}",
        "CAL": f"CAL {profile.iso2}",
    }


def build_visual_pieces(values: list[float], metric: MacroMapMetric) -> list[dict[str, object]]:
    if not values:
        return [{"min": 0, "max": 0, "label": "DATA UNAVAILABLE", "color": "#161a1d"}]
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        span = max(abs(minimum) * 0.05, 0.1)
        minimum -= span
        maximum += span
    step = (maximum - minimum) / 5.0
    boundaries = [minimum + step * index for index in range(1, 5)]
    colors = (
        ["#a71f3d", "#d86d24", "#d5a419", "#82a92f", "#258a4b"]
        if metric in {MacroMapMetric.GDP, MacroMapMetric.EQUITY_YTD}
        else ["#174d64", "#2d8397", "#c29e27", "#c56427", "#a92e37"]
    )
    pieces: list[dict[str, object]] = []
    for index, color in enumerate(colors):
        piece: dict[str, object] = {"color": color}
        if index == 0:
            piece["lte"] = boundaries[0]
            piece["label"] = f"<= {boundaries[0]:.1f}"
        elif index == 4:
            piece["gt"] = boundaries[-1]
            piece["label"] = f"> {boundaries[-1]:.1f}"
        else:
            piece["gt"] = boundaries[index - 1]
            piece["lte"] = boundaries[index]
            piece["label"] = f"{boundaries[index - 1]:.1f} to {boundaries[index]:.1f}"
        pieces.append(piece)
    return pieces


@lru_cache(maxsize=1)
def _world_geojson() -> dict[str, object]:
    path = Path(__file__).resolve().parent / "charts" / "assets" / "world.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _panel_table(headers: tuple[str, ...], rows: int) -> QTableWidget:
    table = QTableWidget(rows, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(25)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)
    table.setWordWrap(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if len(headers) > 1:
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    return table


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"background:#303338;color:{AJAX_CYAN};border:1px solid {AJAX_BORDER};font-weight:bold;padding:3px 5px"
    )
    return label


def _item(text: object, color: str, *, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setForeground(QColor(color))
    alignment = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
    return item


def _format_value(observation: MacroObservation | None, *, signed: bool = False) -> str:
    if observation is None or observation.value is None:
        return "N/A"
    prefix = "+" if signed and observation.value > 0 else ""
    suffix = "%" if "%" in observation.unit else f" {observation.unit}" if observation.unit else ""
    return f"{prefix}{observation.value:.2f}{suffix}"


def _compact_period(period: str) -> str:
    if " / " not in period:
        return period or "--"
    parts = period.split(" / ")
    try:
        start, end = (datetime.fromisoformat(value).date() for value in parts)
    except (TypeError, ValueError):
        return period
    return f"{start:%d %b} / {end:%d %b %y}".upper()
