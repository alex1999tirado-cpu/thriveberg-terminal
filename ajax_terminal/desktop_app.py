from __future__ import annotations

import asyncio
import ast
import html
import importlib.util
import re
import sys
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QPoint, QProcess, QSettings, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal import __version__
from ajax_terminal.charts.launcher import (
    ChartRuntimeError,
    launch_curve_chart,
    launch_price_chart,
    launch_volatility_surface,
)
from ajax_terminal.charts.qt_app import _load_curve, _load_price, _load_surface
from ajax_terminal.charts.qt_windows import CurveWindow, PriceChartWindow
from ajax_terminal.charts.ovdv_window import VolatilitySurfaceWorkspace
from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_MUTED, AJAX_RED, AJAX_TEXT, qt_stylesheet
from ajax_terminal.classic_embed import ClassicAction, ClassicSnapshot, render_classic_snapshot
from ajax_terminal.desktop_security import open_external_url, open_local_path
from ajax_terminal.data_quality_desktop import DataQualityWorkspace
from ajax_terminal.fundamentals_desktop import (
    FinancialAnalysisWorkspace,
    FinancialExportWorkspace,
    FinancialStatementsWorkspace,
    SecurityDescriptionWorkspace,
    export_financial_statements,
    load_financial_analysis,
    load_financial_statement,
    load_security_description,
)
from ajax_terminal.games.doom import DoomWorkspace
from ajax_terminal.equity_research_desktop import (
    AnalystWorkspace,
    DividendsWorkspace,
    EstimatesWorkspace,
    EventsWorkspace,
    FilingsWorkspace,
    RelativeValuationWorkspace,
    ResearchLoad,
    ScreenerWorkspace,
    load_analyst_consensus,
    load_dividends,
    load_estimates,
    load_events,
    load_filings,
    load_relative_valuation,
    load_screener,
)
from ajax_terminal.models.quote import StatementType
from ajax_terminal.macro_map_desktop import MacroMapLoad, MacroMapWorkspace, load_macro_map
from ajax_terminal.news_desktop import NewsDesktopWorkspace, NewsLoad, load_news
from ajax_terminal.options_desktop import (
    OptionsDesktopLoad,
    OptionsDesktopWorkspace,
    load_option_monitor,
    load_option_valuation,
)
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.data_quality_service import load_data_quality_dashboard
from ajax_terminal.services.diagnostics_service import collect_diagnostics
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.services.options_service import resolve_option_underlying_symbol
from ajax_terminal.services.social_service import SocialService
from ajax_terminal.secure_settings import SecureSettings, SecureSettingsError
from ajax_terminal.services.workstation_service import (
    load_alerts,
    load_data_audit,
    load_event_calendar,
    load_portfolio,
    load_watchlist,
)
from ajax_terminal.services.update_service import SignedRelease, download_signed_release, fetch_update_catalog
from ajax_terminal.social_desktop import AsyncOperation, SocialDesktopWorkspace
from ajax_terminal.startup import StartupManager, StartupStage
from ajax_terminal.startup_splash import StartupSplash, thriveberg_icon
from ajax_terminal.storage.database import get_connection
from ajax_terminal.storage.workstation import WorkspaceSnapshot, WorkspaceStore
from ajax_terminal.ui.commands.parser import SECURITY_FUNCTIONS, CommandAction, parse_command
from ajax_terminal.ui.suggestions import (
    COMMANDS,
    SYMBOL_FUNCTIONS,
    SecuritySuggestion,
    command_suggestions,
    security_search_context,
    security_suggestions,
)
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period
from ajax_terminal.workstation_desktop import (
    AlertsWorkspace,
    DataAuditWorkspace,
    DiagnosticsWorkspace,
    EventCalendarWorkspace,
    PortfolioWorkspace,
    UpdateWorkspace,
    WatchlistWorkspace,
    WorkspaceManagerWorkspace,
    restore_workspace_geometry,
)


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.=_^-]{0,24}$")

_SECURITY_ROUTE_KINDS = {
    "price",
    "ovdv",
    "option-monitor",
    "option-valuation",
    "select",
    "description",
    "financial-analysis",
    "financial-income",
    "financial-balance",
    "financial-cashflow",
    "financial-export",
    "relative-valuation",
    "estimates",
    "analyst",
    "dividends",
    "events",
    "filings",
    "filings-10k",
    "filings-10q",
    "data-audit",
}


@dataclass(frozen=True, slots=True)
class DesktopRoute:
    kind: str
    target: str
    period: str | None = None
    interval: str | None = None
    raw: str = ""


@dataclass(slots=True)
class _TerminalTabState:
    stack: QStackedWidget
    current_route: DesktopRoute
    current_symbol: str
    history: list[DesktopRoute]
    history_index: int = 0
    engine_text: str = "NATIVE QT / WEBENGINE / VTK"
    instrument_text: str = "NO ACTIVE SECURITY   |   ENTER NAME OR TICKER   |   THEN FUNCTION <GO>"
    popout_enabled: bool = False
    popout_text: str = "POP OUT"
    load_serial: int = 0


@dataclass(frozen=True, slots=True)
class _WorkspaceLoadContext:
    tab: _TerminalTabState
    serial: int
    engine: str
    mount: Callable[[object], None]


_GLOBAL_OVERVIEW_PANELS = (
    ("FX / EURUSD INTRADAY", "GP EURUSD 5D 15M"),
    ("WORLD EQUITIES", "WEI"),
    ("SOVEREIGN RATES / GLOBAL 10Y", "GOVT"),
    ("WORLD MARKET NEWS", "NEWS MARKETS"),
)
_GLOBAL_OVERVIEW_CHOICES = (
    ("GP EURUSD 5D 15M", "GP USDJPY 5D 15M", "FX"),
    ("WEI", "MARKETS", "MAP GDP"),
    ("GOVT", "CURVE USD", "GOVT US", "GOVT DE"),
    ("NEWS MARKETS", "NEWS ECONOMY", "NEWS CENTRAL BANKS", "EVT ALL 7 1"),
)
_GLOBAL_OVERVIEW_FORBIDDEN = ("WALL", "LOGOUT", "SIGN OUT", "SIGNOUT", "SOCIAL", "TAB")


def _global_overview_commands(settings: QSettings) -> tuple[str, str, str, str]:
    stored = settings.value("overview/commands", []) or []
    if isinstance(stored, str):
        stored = [stored]
    commands: list[str] = []
    for index, (_, default) in enumerate(_GLOBAL_OVERVIEW_PANELS):
        value = str(stored[index] if index < len(stored) else default)
        clean = " ".join(value.strip().upper().split())
        if not clean or clean.startswith(_GLOBAL_OVERVIEW_FORBIDDEN):
            clean = default
        commands.append(clean)
    return tuple(commands)  # type: ignore[return-value]


def resolve_desktop_command(raw: str, current_symbol: str = "") -> DesktopRoute:
    clean = " ".join(raw.strip().upper().split())
    parsed = parse_command(clean)
    if not clean or parsed.action == CommandAction.HOME:
        return DesktopRoute("home", current_symbol, raw=clean or "HOME")
    if (
        parsed.action in SECURITY_FUNCTIONS
        and parsed.action not in {CommandAction.FX, CommandAction.FWD, CommandAction.NEWS, CommandAction.EVENTS}
        and not (parsed.target or current_symbol)
    ):
        return DesktopRoute("security-required", "", raw=clean)
    if parsed.action in {CommandAction.SEARCH, CommandAction.UNKNOWN} and len(clean.split()) == 1:
        if _SYMBOL_RE.fullmatch(clean):
            return DesktopRoute("select", clean, raw=clean)
    if parsed.action == CommandAction.CHART:
        target = parsed.target or current_symbol
        period = normalize_history_period(parsed.args[1] if len(parsed.args) > 1 else "1Y")
        interval = normalize_history_interval(period, parsed.args[2] if len(parsed.args) > 2 else None)
        return DesktopRoute("price", target, period, interval, clean)
    if parsed.action == CommandAction.RISK:
        return DesktopRoute("price", parsed.target or current_symbol, "1Y", "1d", clean)
    if parsed.action == CommandAction.VOL:
        return DesktopRoute("ovdv", _option_route_target(parsed.target or current_symbol), raw=clean)
    if parsed.action == CommandAction.OPTIONS:
        return DesktopRoute(
            "option-monitor",
            _option_route_target(parsed.target or current_symbol),
            raw=clean,
        )
    if parsed.action == CommandAction.OPTION_VALUATION:
        return DesktopRoute(
            "option-valuation",
            _option_route_target(parsed.target or current_symbol),
            raw=clean,
        )
    if parsed.action == CommandAction.CURVE:
        return DesktopRoute("curve", parsed.target or "USD", raw=clean)
    if parsed.action == CommandAction.MAP:
        return DesktopRoute("macro-map", parsed.target or "WORLD", raw=clean)
    if parsed.action == CommandAction.NEWS:
        return DesktopRoute("news", parsed.target, raw=clean)
    if parsed.action == CommandAction.SOCIAL:
        return DesktopRoute("social", current_symbol, raw=clean)
    if parsed.action == CommandAction.WATCH:
        return DesktopRoute("watchlist", "", raw=clean)
    if parsed.action == CommandAction.PORTFOLIO:
        return DesktopRoute("portfolio", "", raw=clean)
    if parsed.action == CommandAction.ALERTS:
        return DesktopRoute("alerts", "", raw=clean)
    if parsed.action == CommandAction.WORKSPACES:
        return DesktopRoute("workspaces", "", raw=clean)
    if parsed.action == CommandAction.UPDATES:
        return DesktopRoute("updates", "", raw=clean)
    if parsed.action == CommandAction.DIAGNOSTICS:
        return DesktopRoute("diagnostics", "", raw=clean)
    if parsed.action == CommandAction.DOOM:
        return DesktopRoute("doom", "", raw=clean)
    if parsed.action in {CommandAction.INSTRUMENT, CommandAction.EQUITY}:
        return DesktopRoute("description", parsed.target or current_symbol, raw=clean)
    if parsed.action == CommandAction.DATA_AUDIT:
        return DesktopRoute("data-audit", parsed.target or current_symbol, raw=clean)
    if parsed.action == CommandAction.DATA_QUALITY:
        target = next((arg for arg in parsed.args if arg not in {"PROBE", "REFRESH"}), "")
        return DesktopRoute("data-quality", target, raw=clean)
    if parsed.action == CommandAction.FINANCIAL_ANALYSIS:
        return DesktopRoute("financial-analysis", parsed.target or current_symbol, raw=clean)
    research_actions = {
        CommandAction.RELATIVE_VALUATION: "relative-valuation",
        CommandAction.COMP: "relative-valuation",
        CommandAction.ESTIMATES: "estimates",
        CommandAction.ANALYST: "analyst",
        CommandAction.DIVIDENDS: "dividends",
        CommandAction.FILINGS: "filings",
        CommandAction.TEN_K: "filings-10k",
        CommandAction.TEN_Q: "filings-10q",
    }
    if parsed.action in research_actions:
        return DesktopRoute(research_actions[parsed.action], parsed.target or current_symbol, raw=clean)
    if parsed.action == CommandAction.EVENTS:
        target = parsed.target or current_symbol
        calendar_target = bool(
            not target
            or target in {"ALL", "WATCHLIST", "PORTFOLIO"}
            or target.startswith(("WATC:", "PORT:"))
        )
        if calendar_target:
            days = parsed.args[1] if len(parsed.args) > 1 else "30"
            page = parsed.args[2] if len(parsed.args) > 2 else "1"
            calendar_scope = target or "ALL"
            if calendar_scope == "WATCHLIST":
                calendar_scope = "WATC:DEFAULT"
            elif calendar_scope == "PORTFOLIO":
                calendar_scope = "PORT:MAIN"
            return DesktopRoute(
                "event-calendar",
                calendar_scope,
                period=days,
                interval=page,
                raw=clean or "EVT ALL 30 1",
            )
        return DesktopRoute("events", target, raw=clean)
    if parsed.action == CommandAction.SCREENER:
        return DesktopRoute("screener", current_symbol, raw=clean)
    statement_actions = {
        CommandAction.INCOME_STATEMENT: "income",
        CommandAction.BALANCE_SHEET: "balance",
        CommandAction.CASH_FLOW: "cashflow",
    }
    if parsed.action in statement_actions:
        return DesktopRoute(
            f"financial-{statement_actions[parsed.action]}",
            parsed.target or current_symbol,
            raw=clean,
        )
    if parsed.action == CommandAction.EXPORT:
        return DesktopRoute("financial-export", parsed.target or current_symbol, raw=clean)
    return DesktopRoute("terminal", parsed.target or current_symbol, raw=clean)


def _option_route_target(symbol: str) -> str:
    try:
        return resolve_option_underlying_symbol(symbol)
    except ValueError:
        return symbol


class _Loader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, loader: Callable[[], Any]) -> None:
        super().__init__()
        self.loader = loader

    def run(self) -> None:
        try:
            self.loaded.emit(self.loader())
        except Exception as exc:
            self.failed.emit(str(exc))


class _InteractiveSvgWidget(QSvgWidget):
    action_triggered = Signal(str)

    def __init__(
        self,
        actions: tuple[ClassicAction, ...],
        columns: int,
        rows: int,
    ) -> None:
        super().__init__()
        self._actions = actions
        self._columns = max(columns, 1)
        self._rows = max(rows, 1)
        self.setMouseTracking(True)

    def _action_at(self, position) -> str | None:
        if self.width() <= 0 or self.height() <= 0:
            return None
        column = int(position.x() * self._columns / self.width())
        row = int(position.y() * self._rows / self.height())
        return next(
            (
                item.action
                for item in self._actions
                if item.row == row and item.column_start <= column < item.column_end
            ),
            None,
        )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt callback
        cursor = Qt.CursorShape.PointingHandCursor if self._action_at(event.position()) else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt callback
        action = self._action_at(event.position())
        if action:
            if event.button() == Qt.MouseButton.LeftButton:
                self.action_triggered.emit(action)
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton and action.startswith("app.open_methodology("):
                menu = QMenu(self)
                selected = menu.addAction("OPEN METHODOLOGY")
                if menu.exec(event.globalPosition().toPoint()) == selected:
                    self.action_triggered.emit(action)
                event.accept()
                return
        super().mousePressEvent(event)


@dataclass(frozen=True, slots=True)
class _FunctionEntry:
    code: str
    description: str
    command: str


class _FunctionMenuRow(QFrame):
    triggered = Signal(str)

    def __init__(self, number: int, entry: _FunctionEntry) -> None:
        super().__init__()
        self.command = entry.command
        self.setObjectName(f"functionMenuRow_{entry.code}")
        self.setProperty("functionRow", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(29)
        self.setToolTip(entry.description)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 1, 5, 1)
        row.setSpacing(10)
        code = QLabel(f"{number:>2})  {entry.code}")
        code.setObjectName("functionMenuCode")
        code.setFixedWidth(82)
        code.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        description = QLabel(entry.description)
        description.setObjectName("functionMenuDescription")
        description.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(code)
        row.addWidget(description, 1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt callback
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.triggered.emit(self.command)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _SecurityFunctionMenu(QWidget):
    command_requested = Signal(str)

    def __init__(self, symbol: str, name: str, security_type: str, currency: str = "") -> None:
        super().__init__()
        self.setObjectName("securityFunctionMenu")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 16, 28, 20)
        root.setSpacing(6)

        breadcrumb = QLabel(
            f"MAIN MENU OF THRIVEBERG FUNCTIONS  >  {security_type or 'SECURITY'}  >  "
            f"ANALYZE  >  {name.upper()}  {symbol}"
        )
        breadcrumb.setObjectName("functionBreadcrumb")
        root.addWidget(breadcrumb)
        root.addSpacing(8)

        columns = QGridLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setHorizontalSpacing(66)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)
        left_groups, right_groups = _security_function_groups(symbol, security_type, currency)
        left, next_number = self._menu_column(left_groups, 1)
        right, _ = self._menu_column(right_groups, next_number)
        columns.addWidget(left, 0, 0, Qt.AlignmentFlag.AlignTop)
        columns.addWidget(right, 0, 1, Qt.AlignmentFlag.AlignTop)
        root.addLayout(columns)
        root.addStretch(1)

    def _menu_column(
        self,
        groups: tuple[tuple[str, tuple[_FunctionEntry, ...]], ...],
        number: int,
    ) -> tuple[QWidget, int]:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for title, entries in groups:
            heading = QLabel(f"{title}  >")
            heading.setObjectName("functionGroupTitle")
            layout.addWidget(heading)
            for entry in entries:
                item = _FunctionMenuRow(number, entry)
                item.triggered.connect(self.command_requested)
                layout.addWidget(item)
                number += 1
            layout.addSpacing(15)
        layout.addStretch(1)
        return column, number


def _security_function_groups(
    symbol: str,
    security_type: str,
    currency: str,
) -> tuple[
    tuple[tuple[str, tuple[_FunctionEntry, ...]], ...],
    tuple[tuple[str, tuple[_FunctionEntry, ...]], ...],
]:
    kind = security_type.upper()

    def item(code: str, description: str, command: str | None = None) -> _FunctionEntry:
        return _FunctionEntry(code, description, command or f"{symbol} {code}")

    if kind in {"EQUITY", "ETF", "MARKET", ""}:
        return (
            (
                ("COMPANY OVERVIEW", (item("DES", "Security Description"), item("FILINGS", "Company Filings"), item("NEWS", "Company News"))),
                ("COMPANY ANALYSIS", (item("FA", "Financial Analysis"), item("IS", "Income Statement"), item("BS", "Balance Sheet"), item("CF", "Cash Flow Statement"))),
                ("RESEARCH & ESTIMATES", (item("EE", "Earnings & Estimates"), item("ANR", "Analyst Recommendations"), item("EVT", "Company Events"))),
                ("COMPARATIVE ANALYTICS", (item("RV", "Relative Valuation"), item("COMP", "Comparable Company Analysis"))),
            ),
            (
                ("CHARTING & REPORTING", (item("GP", "Price Chart"), item("RISK", "Price & Risk Analytics"), item("FLDS", "Field Source & Methodology"), item("XLS", "Export Financial Statements"))),
                ("DERIVATIVES", (item("OMON", "Option Monitor"), item("OVDV", "Volatility Surface"), item("OVME", "Option Valuation"))),
            ),
        )
    if kind in {"FX", "CURRENCY", "CRYPTOCURRENCY"}:
        return (
            (("MARKET OVERVIEW", (item("GP", "Price Chart"), item("RISK", "Price & Risk Analytics"))),),
            (("FX ANALYTICS", (item("FWD", "Forward Monitor", f"FWD {symbol}"), item("OVDV", "Volatility Surface"), item("OVME", "Option Valuation"))),),
        )
    if kind in {"RATE", "BOND", "FIXED INCOME"}:
        curve_currency = currency if currency in {"USD", "EUR", "JPY"} else "USD"
        return (
            (("SECURITY OVERVIEW", (item("DES", "Security Description"), item("GP", "Price Chart"), item("NEWS", "Issuer News"))),),
            (("FIXED INCOME ANALYTICS", (item("RISK", "Price & Risk Analytics"), item("CURVE", "Reference Yield Curve", f"CURVE {curve_currency}"))),),
        )
    return (
        (("MARKET OVERVIEW", (item("GP", "Price Chart"), item("RISK", "Price & Risk Analytics"), item("NEWS", "Related News"))),),
        (("REFERENCE", (item("DES", "Security Description"),)),),
    )


class _WindowChrome(QFrame):
    compact_activated = Signal()

    def __init__(
        self,
        owner: QMainWindow,
        *,
        title: str = "THRIVEBERG TERMINAL",
        compact: bool = False,
    ) -> None:
        super().__init__()
        self.owner = owner
        self.compact = compact
        self._drag_position: QPoint | None = None
        self.setObjectName("windowChrome")
        self.setFixedHeight(26 if compact else 32)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("windowTitle")
        row.addWidget(self.title)
        row.addStretch(1)
        if compact:
            return
        row.addWidget(
            self._control(QStyle.StandardPixmap.SP_TitleBarMinButton, owner.showMinimized, "Minimize")
        )
        self.maximize_button = self._control(
            QStyle.StandardPixmap.SP_TitleBarMaxButton,
            self._toggle_maximize,
            "Maximize",
        )
        row.addWidget(self.maximize_button)
        close = self._control(QStyle.StandardPixmap.SP_TitleBarCloseButton, owner.close, "Close")
        close.setObjectName("windowClose")
        row.addWidget(close)

    def _control(
        self,
        icon: QStyle.StandardPixmap,
        callback: Callable[[], None],
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setIcon(self.owner.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setObjectName("windowControl")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _toggle_maximize(self) -> None:
        if self.owner.isMaximized():
            self.owner.showNormal()
            icon = QStyle.StandardPixmap.SP_TitleBarMaxButton
            self.maximize_button.setToolTip("Maximize")
        else:
            self.owner.showMaximized()
            icon = QStyle.StandardPixmap.SP_TitleBarNormalButton
            self.maximize_button.setToolTip("Restore")
        self.maximize_button.setIcon(self.owner.style().standardIcon(icon))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt callback
        if self.compact:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt callback
        if (
            self._drag_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.owner.isMaximized()
        ):
            self.owner.move(event.globalPosition().toPoint() - self._drag_position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt callback
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt callback
        if event.button() == Qt.MouseButton.LeftButton:
            if self.compact:
                self.compact_activated.emit()
            else:
                self._toggle_maximize()
        super().mouseDoubleClickEvent(event)


class _DataConnectionsDialog(QDialog):
    CONNECTIONS = (
        ("FINNHUB_KEY", "FINNHUB / REALTIME EQUITIES"),
        ("COMPANIES_HOUSE_API_KEY", "COMPANIES HOUSE / UK FILINGS"),
        ("FRED_API_KEY", "FRED / US MACRO"),
        ("ALPHA_VANTAGE_KEY", "ALPHA VANTAGE"),
        ("FMP_KEY", "FINANCIAL MODELING PREP"),
        ("NEWS_API_KEY", "NEWS API"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("THRIVEBERG Data Connections")
        self.setModal(True)
        self.setMinimumWidth(720)
        self.setStyleSheet(qt_stylesheet())
        self.store = SecureSettings()
        self.inputs: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        heading = QLabel("DATA CONNECTIONS")
        heading.setStyleSheet(f"color:{AJAX_AMBER};font-size:18px;font-weight:bold")
        layout.addWidget(heading)

        panel = QFrame()
        panel.setObjectName("terminalPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        for row, (name, label) in enumerate(self.CONNECTIONS):
            caption = QLabel(label)
            caption.setStyleSheet(f"color:{AJAX_TEXT};font-weight:bold")
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(
                "CONFIGURED / ENTER TO REPLACE" if self.store.configured(name) else "NOT CONFIGURED"
            )
            clear = _button("CLEAR", lambda _checked=False, key=name: self._clear(key))
            clear.setEnabled(self.store.configured(name))
            grid.addWidget(caption, row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(clear, row, 2)
            self.inputs[name] = field
        grid.setColumnStretch(1, 1)
        layout.addWidget(panel)

        self.status = QLabel("WINDOWS DPAPI / CURRENT USER")
        self.status.setStyleSheet(f"color:{AJAX_MUTED}")
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = _button("CANCEL", self.reject)
        save = _button("SAVE CONNECTIONS", self._save)
        save.setObjectName("amberButton")
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

    def _clear(self, name: str) -> None:
        try:
            self.store.delete(name)
        except SecureSettingsError as exc:
            self.status.setText(str(exc).upper())
            self.status.setStyleSheet(f"color:{AJAX_RED}")
            return
        self.status.setText(f"{name} REMOVED")
        self.status.setStyleSheet(f"color:{AJAX_AMBER}")

    def _save(self) -> None:
        updates = {
            name: field.text().strip()
            for name, field in self.inputs.items()
            if field.text().strip()
        }
        try:
            if updates:
                self.store.set_many(updates)
        except SecureSettingsError as exc:
            self.status.setText(str(exc).upper())
            self.status.setStyleSheet(f"color:{AJAX_RED}")
            return
        self.accept()


class GlobalOverviewSettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Global Overview")
        self.setWindowIcon(thriveberg_icon())
        self.setModal(True)
        self.setMinimumWidth(720)
        self.setStyleSheet(qt_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        heading = QLabel("GLOBAL OVERVIEW / MULTI-MONITOR WALL")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)

        self.enabled = QCheckBox("OPEN AUTOMATICALLY AFTER SIGN-IN")
        self.enabled.setChecked(settings.value("overview/enabled", True, type=bool))
        layout.addWidget(self.enabled)

        screen_row = QHBoxLayout()
        screen_row.addWidget(QLabel("TARGET DISPLAY"))
        self.screen = QComboBox()
        selected_screen = str(settings.value("overview/screen_name", "") or "")
        for index, screen in enumerate(QApplication.screens()):
            geometry = screen.availableGeometry()
            label = f"{index + 1}) {screen.name()}  {geometry.width()}x{geometry.height()}"
            self.screen.addItem(label, screen.name())
            if screen.name() == selected_screen:
                self.screen.setCurrentIndex(index)
        if not selected_screen and self.screen.count() > 1:
            primary = QApplication.primaryScreen()
            secondary = next(
                (index for index, candidate in enumerate(QApplication.screens()) if candidate is not primary),
                1,
            )
            self.screen.setCurrentIndex(secondary)
        screen_row.addWidget(self.screen, 1)
        layout.addLayout(screen_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        commands = _global_overview_commands(settings)
        self.command_boxes: list[QComboBox] = []
        positions = ("TOP LEFT", "TOP RIGHT", "BOTTOM LEFT", "BOTTOM RIGHT")
        for index, ((title, _default), choices, command) in enumerate(
            zip(_GLOBAL_OVERVIEW_PANELS, _GLOBAL_OVERVIEW_CHOICES, commands, strict=True)
        ):
            label = QLabel(f"{positions[index]}  /  {title}")
            label.setStyleSheet(f"color:{AJAX_TEXT};font-weight:bold")
            box = QComboBox()
            box.setEditable(True)
            box.addItems(choices)
            if box.findText(command) < 0:
                box.addItem(command)
            box.setCurrentText(command)
            box.setMinimumContentsLength(24)
            self.command_boxes.append(box)
            row, column = divmod(index, 2)
            cell = QVBoxLayout()
            cell.setSpacing(3)
            cell.addWidget(label)
            cell.addWidget(box)
            grid.addLayout(cell, row, column)
        layout.addLayout(grid)

        note = QLabel(
            "THE WALL USES THE SELECTED DISPLAY AS A 2x2 MARKET GRID. "
            "DOUBLE-CLICK A PANEL HEADER TO EXPAND OR RESTORE IT."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{AJAX_MUTED}")
        layout.addWidget(note)

        actions = QHBoxLayout()
        reset = QPushButton("RESTORE GLOBAL DEFAULTS")
        reset.setObjectName("menuButton")
        reset.clicked.connect(self._restore_defaults)
        cancel = QPushButton("CANCEL")
        cancel.setObjectName("menuButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("SAVE & OPEN")
        save.setObjectName("amberButton")
        save.clicked.connect(self.accept)
        actions.addWidget(reset)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

    def configuration(self) -> tuple[bool, str, tuple[str, str, str, str]]:
        commands = []
        for box, (_, default) in zip(self.command_boxes, _GLOBAL_OVERVIEW_PANELS, strict=True):
            clean = " ".join(box.currentText().strip().upper().split())
            if not clean or clean.startswith(_GLOBAL_OVERVIEW_FORBIDDEN):
                clean = default
            commands.append(clean)
        return (
            self.enabled.isChecked(),
            str(self.screen.currentData() or ""),
            tuple(commands),  # type: ignore[arg-type]
        )

    def _restore_defaults(self) -> None:
        self.enabled.setChecked(True)
        for box, (_, command) in zip(self.command_boxes, _GLOBAL_OVERVIEW_PANELS, strict=True):
            box.setCurrentText(command)


class AjaxDesktopWindow(QMainWindow):
    """Native desktop shell for interactive chart workspaces.

    The market services and command parser remain shared with the Textual terminal,
    while QWebEngine and VTK receive real native viewports in the central stack.
    """

    workspace_ready = Signal()

    def __init__(
        self,
        *,
        require_login: bool = True,
        settings: QSettings | None = None,
        compact_mode: bool = False,
        compact_title: str = "",
    ) -> None:
        super().__init__()
        self._compact_mode = compact_mode
        self._compact_title = compact_title or "MARKET PANEL"
        self.setWindowTitle("THRIVEBERG Terminal")
        self.setWindowIcon(thriveberg_icon())
        self.setWindowFlags(
            Qt.WindowType.Widget
            if compact_mode
            else Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        if compact_mode:
            self.setMinimumSize(360, 260)
            self.resize(900, 480)
        elif require_login:
            self.setMinimumSize(900, 600)
            self.setMaximumSize(1000, 660)
            self.resize(1000, 660)
        else:
            self.setMinimumSize(1100, 700)
            self.resize(1900, 1030)
        self.setStyleSheet(qt_stylesheet())

        self.social_service = SocialService()
        self.market_service = MarketService()
        self.news_service = NewsService(self.market_service.cache)
        self.registry = self.market_service.registry
        self.settings = settings or QSettings("THRIVEBERG", "THRIVEBERG TERMINAL")
        self.workspace_store = WorkspaceStore()
        self._require_login = require_login
        self._authenticated = not require_login
        self._session_persistence_enabled = require_login and not compact_mode
        self._previous_clean_shutdown = bool(
            self.settings.value("session/clean_shutdown", True, type=bool)
        )
        self._restored_session_command = str(
            self.settings.value("session/last_command", "") or ""
        ).strip()
        restored_tabs = self.settings.value("session/open_tabs", []) or []
        if isinstance(restored_tabs, str):
            restored_tabs = [restored_tabs]
        self._restored_tab_commands = tuple(
            str(command).strip()
            for command in restored_tabs
            if str(command).strip()
        )[:12]
        self._restored_tab_index = max(
            0,
            int(self.settings.value("session/active_tab", 0) or 0),
        )
        if self._session_persistence_enabled:
            self.settings.setValue("session/clean_shutdown", False)
            self.settings.sync()
        self._startup_command: str | None = None
        self._auth_worker: AsyncOperation | None = None
        self._logout_worker: AsyncOperation | None = None
        self._startup_manager: StartupManager | None = None
        self._startup_completed_once = False
        self.current_symbol = ""
        self.current_route = DesktopRoute("home", self.current_symbol, raw="HOME")
        self._history: list[DesktopRoute] = [self.current_route]
        self._history_index = 0
        self._loader: _Loader | None = None
        self._workspace_loaders: list[_Loader] = []
        self._workspace_load_contexts: dict[_Loader, _WorkspaceLoadContext] = {}
        self._pending_mount: Callable[[object], None] | None = None
        self._pending_engine = ""
        self._load_serial = 0
        self._suggestion_serial = 0
        self._suggestion_workers: list[_Loader] = []
        self._suggestions: list[SecuritySuggestion] = []
        self._security_directory: dict[str, tuple[str, str]] = {}
        self._pending_methodology_symbol: str | None = None
        self._alert_worker: _Loader | None = None
        self._alert_session_serial = 0
        self._alert_worker_session: int | None = None
        self._alert_started_once = False
        self._terminal_tabs: dict[QStackedWidget, _TerminalTabState] = {}
        self._active_terminal_tab: _TerminalTabState | None = None
        self._secondary_windows: list[AjaxDesktopWindow] = []
        self._global_overview_window: GlobalOverviewWindow | None = None
        self._global_overview_opened_once = False

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        self.window_chrome = _WindowChrome(
            self,
            title=self._compact_title if compact_mode else "THRIVEBERG TERMINAL",
            compact=compact_mode,
        )
        host_layout.addWidget(self.window_chrome)

        self.lifecycle = QStackedWidget()
        self.splash_page = self._build_splash_page()
        self.auth_page = self._build_auth_page()
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("workspaceTabs")
        self.workspace_tabs.setDocumentMode(True)
        self.workspace_tabs.tabBar().setExpanding(False)
        self.workspace_tabs.currentChanged.connect(self._workspace_tab_changed)

        terminal = self._build_terminal_workspace()
        self.social_workspace = SocialDesktopWorkspace(
            self.social_service,
            lambda: self.current_route.raw,
        )
        self.social_workspace.command_requested.connect(self._open_shared_command)
        self.workspace_tabs.addTab(terminal, "1) TERMINAL")
        self.workspace_tabs.addTab(self.social_workspace, "2) SOCIAL")
        self.lifecycle.addWidget(self.splash_page)
        self.lifecycle.addWidget(self.auth_page)
        self.lifecycle.addWidget(self.workspace_tabs)
        host_layout.addWidget(self.lifecycle, 1)
        self.setCentralWidget(host)

        if compact_mode:
            self._configure_compact_panel()

        self._workspace_shortcuts: list[QShortcut] = []
        for sequence, callback in (
            ("Ctrl+L", self._focus_command),
            ("Ctrl+1", lambda: self.workspace_tabs.setCurrentIndex(0)),
            ("Ctrl+2", lambda: self.workspace_tabs.setCurrentIndex(1)),
            ("Ctrl+T", self.new_terminal_tab),
            ("Ctrl+W", self.close_current_terminal_tab),
            ("Ctrl+Shift+D", self.open_current_tab_window),
            ("Ctrl+PgUp", lambda: self._cycle_terminal_tab(-1)),
            ("Ctrl+PgDown", lambda: self._cycle_terminal_tab(1)),
            ("Alt+Left", self.go_back),
            ("Alt+Right", self.go_forward),
            ("F8", lambda: self.execute_text("GP")),
            ("F10", lambda: self.execute_text("OVDV")),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self.workspace_tabs)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._workspace_shortcuts.append(shortcut)

        self._auth_shortcuts: list[QShortcut] = []
        for sequence, callback in (
            ("Alt+L", self.auth_email.setFocus),
            ("Alt+P", self.auth_password.setFocus),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self.auth_page)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._auth_shortcuts.append(shortcut)

        QShortcut(QKeySequence("Escape"), self, activated=self._escape_action)

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1_000)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start()
        self.alert_timer = QTimer(self)
        self.alert_timer.setInterval(30_000)
        self.alert_timer.timeout.connect(self._run_background_alerts)
        self._tray_icon: QSystemTrayIcon | None = None
        if self._session_persistence_enabled and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = QSystemTrayIcon(thriveberg_icon(), self)
            self._tray_icon.setToolTip("THRIVEBERG Terminal alerts")
            self._tray_icon.show()
        self._update_clock()
        self._set_route_labels(self.current_route)
        self._show_message("LOADING WORKSPACE", "PREPARING MARKET MONITOR", ready=False)

        if self._require_login:
            self.lifecycle.setCurrentWidget(self.auth_page)
            self.window_chrome.hide()
            QTimer.singleShot(0, self._show_login)
        else:
            self.lifecycle.setCurrentWidget(self.workspace_tabs)
            QTimer.singleShot(0, self.command.setFocus)

    def _center_on_active_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def _configure_login_window(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.setMinimumSize(900, 600)
        self.setMaximumSize(1000, 660)
        self.resize(1000, 660)
        self._center_on_active_screen()

    def _configure_workspace_window(self) -> None:
        self.setMaximumSize(16_777_215, 16_777_215)
        self.setMinimumSize(1100, 700)
        geometry = self.settings.value("session/window_geometry") if self._session_persistence_enabled else None
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.showNormal()
            self.restoreGeometry(geometry)
            if bool(self.settings.value("session/window_maximized", True, type=bool)):
                self.showMaximized()
        else:
            self.showMaximized()

    def _build_terminal_workspace(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(3)
        self.terminal_layout = layout
        self.system_bar = self._system_bar()
        self.menu_frame = self._menu_bar()
        layout.addWidget(self.system_bar)
        layout.addWidget(self.menu_frame)
        self.function_bar = QLabel()
        self.function_bar.setObjectName("functionBar")
        self.function_bar.setTextFormat(Qt.TextFormat.RichText)
        self.function_bar.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.function_bar.setOpenExternalLinks(False)
        self.function_bar.linkActivated.connect(self._function_bar_link)
        layout.addWidget(self.function_bar)
        self.instrument_bar = QLabel()
        self.instrument_bar.setObjectName("instrumentBar")
        layout.addWidget(self.instrument_bar)

        self.command_row_widget = QWidget()
        command_row = QHBoxLayout(self.command_row_widget)
        command_row.setContentsMargins(0, 0, 0, 0)
        command_row.setSpacing(6)
        prompt = QLabel(">")
        prompt.setStyleSheet(f"color:{AJAX_AMBER};font-weight:bold")
        command_row.addWidget(prompt)
        self.command = QLineEdit()
        self.command.setPlaceholderText("ENTER SECURITY OR FUNCTION")
        self.command.returnPressed.connect(self._submit_command)
        self.command.textChanged.connect(self._command_text_changed)
        self.command.installEventFilter(self)
        command_row.addWidget(self.command, 1)
        layout.addWidget(self.command_row_widget)
        self.suggestion_panel = self._build_suggestion_panel()
        layout.addWidget(self.suggestion_panel)

        self.document_tabs = QTabWidget()
        self.document_tabs.setObjectName("terminalDocumentTabs")
        self.document_tabs.setDocumentMode(True)
        self.document_tabs.setTabsClosable(True)
        self.document_tabs.setMovable(True)
        self.document_tabs.tabBar().setExpanding(False)
        self.document_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.document_tabs.currentChanged.connect(self._terminal_tab_changed)
        self.document_tabs.tabCloseRequested.connect(self.close_terminal_tab)
        self.document_tabs.tabBarDoubleClicked.connect(self._terminal_tab_double_clicked)

        tab_tools = QWidget()
        tab_tools.setObjectName("terminalTabTools")
        tab_tools_row = QHBoxLayout(tab_tools)
        tab_tools_row.setContentsMargins(2, 0, 2, 0)
        tab_tools_row.setSpacing(2)
        self.new_tab_button = QToolButton()
        self.new_tab_button.setObjectName("workspaceTabTool")
        self.new_tab_button.setText("+")
        self.new_tab_button.setToolTip("New workspace tab (Ctrl+T)")
        self.new_tab_button.clicked.connect(self.new_terminal_tab)
        tab_tools_row.addWidget(self.new_tab_button)
        self.new_window_button = QToolButton()
        self.new_window_button.setObjectName("workspaceTabTool")
        self.new_window_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
        self.new_window_button.setToolTip("Open this workspace in another window (Ctrl+Shift+D)")
        self.new_window_button.clicked.connect(self.open_current_tab_window)
        tab_tools_row.addWidget(self.new_window_button)
        self.document_tabs.setCornerWidget(tab_tools, Qt.Corner.TopRightCorner)
        layout.addWidget(self.document_tabs, 1)
        self._create_terminal_tab("HOME", activate=True, execute=False, inherit_symbol=False)
        self.footer = QLabel(
            "F1 HELP   F2 MARKETS   F5 EQUITY   F8 GP   F9 SOCIAL   F10 OPTIONS   |   CTRL+T TAB   CTRL+W CLOSE   CTRL+SHIFT+D WINDOW"
        )
        self.footer.setObjectName("footerBar")
        layout.addWidget(self.footer)
        return root

    def _configure_compact_panel(self) -> None:
        self.workspace_tabs.tabBar().hide()
        self.system_bar.hide()
        self.menu_frame.hide()
        self.command_row_widget.hide()
        self.suggestion_panel.hide()
        self.footer.hide()
        self.document_tabs.tabBar().hide()
        corner = self.document_tabs.cornerWidget(Qt.Corner.TopRightCorner)
        if corner is not None:
            corner.hide()
        self.terminal_layout.setContentsMargins(3, 3, 3, 3)
        self.terminal_layout.setSpacing(2)
        self.statusBar().hide()

    def _build_suggestion_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("commandSuggestions")
        panel.setVisible(False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.suggestion_status = QLabel("SECURITY SEARCH")
        self.suggestion_status.setObjectName("suggestionStatus")
        layout.addWidget(self.suggestion_status)

        self.suggestion_table = QTableWidget(0, 4)
        self.suggestion_table.setObjectName("suggestionTable")
        self.suggestion_table.setHorizontalHeaderLabels(("SECURITY", "DESCRIPTION", "TYPE", "ACTION"))
        self.suggestion_table.verticalHeader().hide()
        self.suggestion_table.verticalHeader().setDefaultSectionSize(28)
        self.suggestion_table.setShowGrid(False)
        self.suggestion_table.setAlternatingRowColors(True)
        self.suggestion_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.suggestion_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.suggestion_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.suggestion_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestion_table.cellClicked.connect(self._accept_suggestion)
        header = self.suggestion_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.suggestion_table)

        self._suggestion_timer = QTimer(self)
        self._suggestion_timer.setSingleShot(True)
        self._suggestion_timer.setInterval(240)
        self._suggestion_timer.timeout.connect(self._start_remote_suggestion_search)
        return panel

    def _build_splash_page(self) -> StartupSplash:
        return StartupSplash()

    def _build_auth_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("authPage")
        grid = QGridLayout(page)
        self.auth_grid = grid
        grid.setContentsMargins(32, 42, 18, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 310)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 480)
        grid.setColumnStretch(3, 1)
        grid.setRowMinimumHeight(0, 92)

        brand_box = QWidget()
        brand_layout = QVBoxLayout(brand_box)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)
        brand = QLabel("THRIVEBERG")
        brand.setObjectName("authBrand")
        brand_layout.addWidget(brand)
        subtitle = QLabel("TERMINAL")
        subtitle.setObjectName("authBrandSub")
        brand_layout.addWidget(subtitle)
        grid.addWidget(brand_box, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        login_code = QLabel("LOGI")
        login_code.setObjectName("authCode")
        grid.addWidget(login_code, 0, 3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        login_panel = QWidget()
        login_layout = QVBoxLayout(login_panel)
        login_layout.setContentsMargins(0, 10, 0, 0)
        login_layout.setSpacing(3)
        self.auth_email_row, self.auth_email_caption, self.auth_email = self._auth_labeled_input(
            "Login Name"
        )
        self.auth_username_row, _username_caption, self.auth_username = self._auth_labeled_input(
            "Username"
        )
        self.auth_name_row, _name_caption, self.auth_name = self._auth_labeled_input("Display Name")
        self.auth_password_row, _password_caption, self.auth_password = self._auth_labeled_input(
            "Password", password=True
        )
        self.auth_confirm_row, _confirm_caption, self.auth_confirm = self._auth_labeled_input(
            "Confirm Password", password=True
        )
        for row in (
            self.auth_email_row,
            self.auth_username_row,
            self.auth_name_row,
            self.auth_password_row,
            self.auth_confirm_row,
        ):
            login_layout.addWidget(row)
        self.auth_password.returnPressed.connect(self._submit_auth)
        self.auth_confirm.returnPressed.connect(self._submit_auth)
        self.auth_username.returnPressed.connect(self._submit_auth)
        self.auth_name.returnPressed.connect(self._submit_auth)
        login_layout.addSpacing(10)
        self.auth_submit = QPushButton("Login")
        self.auth_submit.setObjectName("authSubmit")
        self.auth_submit.setFixedWidth(160)
        self.auth_submit.clicked.connect(self._submit_auth)
        login_layout.addWidget(self.auth_submit, 0, Qt.AlignmentFlag.AlignLeft)
        self.auth_status = QLabel("SECURE SESSION REQUIRED")
        self.auth_status.setObjectName("authStatus")
        self.auth_status.setWordWrap(True)
        self.auth_status.setFixedWidth(300)
        login_layout.addWidget(self.auth_status)
        self.auth_link_spacer = QWidget()
        self.auth_link_spacer.setFixedHeight(70)
        login_layout.addWidget(self.auth_link_spacer)
        self.forgot_link = _auth_link("Forgot Login Name or Password?", self._forgot_login)
        self.support_link = _auth_link("Contact Support", self._contact_support)
        self.create_link = _auth_link("Create a New Login", lambda: self._set_auth_mode("register"))
        login_layout.addWidget(self.forgot_link)
        login_layout.addSpacing(20)
        login_layout.addWidget(self.support_link)
        login_layout.addWidget(self.create_link)
        grid.addWidget(login_panel, 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        language_panel = QWidget()
        self.language_panel = language_panel
        language_layout = QVBoxLayout(language_panel)
        language_layout.setContentsMargins(0, 34, 0, 0)
        language_layout.setSpacing(9)
        language_title = QLabel("Select Language for Analytics and\nCommunication Functions:")
        language_title.setObjectName("languageTitle")
        language_layout.addWidget(language_title)
        language_layout.addSpacing(12)
        language_grid = QGridLayout()
        language_grid.setContentsMargins(0, 0, 0, 0)
        language_grid.setHorizontalSpacing(24)
        language_grid.setVerticalSpacing(2)
        self._language_group = QButtonGroup(self)
        self._language_group.setExclusive(True)
        self._language_buttons: dict[str, QPushButton] = {}
        languages = (
            ("English", 0, 0),
            ("Español", 0, 1),
            ("한국어", 0, 2),
            ("日本語", 1, 0),
            ("Português", 1, 1),
            ("简体中文", 1, 2),
            ("Français", 2, 0),
            ("Italiano", 2, 1),
            ("Русский", 2, 2),
            ("Deutsch", 3, 0),
            ("繁體中文", 3, 1),
        )
        selected_language = str(self.settings.value("login/language", "English"))
        for language, row_index, column_index in languages:
            button = QPushButton(language)
            button.setObjectName("languageOption")
            script_fonts = {
                "한국어": "Malgun Gothic",
                "日本語": "Yu Gothic UI",
                "简体中文": "Microsoft YaHei UI",
                "繁體中文": "Microsoft JhengHei UI",
            }
            if language in script_fonts:
                button.setStyleSheet(f'font-family:"{script_fonts[language]}"')
            button.setCheckable(True)
            button.setChecked(language == selected_language)
            button.clicked.connect(lambda _checked=False, value=language: self._select_language(value))
            self._language_group.addButton(button)
            self._language_buttons[language] = button
            language_grid.addWidget(button, row_index, column_index)
        if not any(button.isChecked() for button in self._language_buttons.values()):
            self._language_buttons["English"].setChecked(True)
            selected_language = "English"
        self._select_language(selected_language)
        language_layout.addLayout(language_grid)
        language_layout.addSpacing(16)
        language_note = QLabel(
            "To customize your News language experience\n"
            "type LANG <GO> after login."
        )
        language_note.setObjectName("languageNote")
        language_layout.addWidget(language_note)
        grid.addWidget(language_panel, 1, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        grid.setRowStretch(2, 1)
        self.auth_terminal_id = QLabel(
            f"S/N THR-001  |  SID LOCAL  |  Version {__version__} Beta  |  Netid AUTO"
        )
        self.auth_terminal_id.setObjectName("authTechnical")
        grid.addWidget(self.auth_terminal_id, 3, 0, 1, 4)
        self.auth_legal = QLabel(
            "THRIVEBERG TERMINAL is an independent financial software project.  "
            "Market data may be delayed and is provided by third-party data sources.\n"
            "Information displayed is for informational and analytical purposes only.  "
            "THRIVEBERG does not provide investment advice or guarantee data accuracy."
        )
        self.auth_legal.setObjectName("authLegal")
        self.auth_legal.setWordWrap(True)
        self.auth_legal.setMaximumWidth(950)
        self.auth_legal.setMinimumHeight(80)
        grid.addWidget(
            self.auth_legal,
            4,
            0,
            1,
            4,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        grid.setRowStretch(5, 1)
        remembered = str(self.settings.value("login/name", ""))
        self.auth_email.setText(remembered)
        self._auth_mode = "signin"
        self._set_auth_mode("signin")
        return page

    def _auth_labeled_input(
        self,
        label: str,
        *,
        password: bool = False,
    ) -> tuple[QWidget, QLabel, QLineEdit]:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 5)
        layout.setSpacing(1)
        caption = QLabel(label)
        caption.setObjectName("authFieldLabel")
        layout.addWidget(caption)
        field = QLineEdit()
        field.setObjectName("authInput")
        field.setFixedWidth(300)
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(field)
        return row, caption, field

    def _set_auth_mode(self, mode: str) -> None:
        registering = mode == "register"
        self._auth_mode = mode
        self.auth_grid.setRowMinimumHeight(0, 72 if registering else 92)
        self.auth_email_caption.setText("Email" if registering else "Login Name")
        self.auth_username_row.setVisible(registering)
        self.auth_name_row.setVisible(registering)
        self.auth_confirm_row.setVisible(registering)
        self.language_panel.setVisible(not registering)
        self.auth_legal.setVisible(not registering)
        self.auth_link_spacer.setFixedHeight(8 if registering else 70)
        for field in (
            self.auth_email,
            self.auth_username,
            self.auth_name,
            self.auth_password,
            self.auth_confirm,
        ):
            field.setFixedHeight(28 if registering else 40)
        self.auth_submit.setText("Create Login" if registering else "Login")
        self.forgot_link.setVisible(not registering)
        self.support_link.setVisible(not registering)
        self.create_link.setText("Back to Login" if registering else "Create a New Login")
        try:
            self.create_link.clicked.disconnect()
        except RuntimeError:
            pass
        self.create_link.clicked.connect(
            (lambda: self._set_auth_mode("signin"))
            if registering
            else (lambda: self._set_auth_mode("register"))
        )
        self.auth_status.setText("EMAIL CONFIRMATION MAY BE REQUIRED" if registering else "SECURE SESSION REQUIRED")
        self.auth_status.setStyleSheet(f"color:{AJAX_MUTED}")

    def _show_login(self) -> None:
        if self._authenticated:
            return
        self._configure_login_window()
        self.window_chrome.hide()
        self.lifecycle.setCurrentWidget(self.auth_page)
        if self.social_service.configured:
            self.auth_status.setText("SECURE SESSION REQUIRED")
            self.auth_status.setStyleSheet(f"color:{AJAX_MUTED}")
        else:
            self.auth_status.setText("SOCIAL SERVER NOT CONFIGURED")
            self.auth_status.setStyleSheet(f"color:{AJAX_RED}")
        QTimer.singleShot(0, self.auth_email.setFocus)

    def _forgot_login(self) -> None:
        self.auth_status.setText("PASSWORD RECOVERY IS PROVIDED BY THE ACCOUNT ADMINISTRATOR")
        self.auth_status.setStyleSheet(f"color:{AJAX_TEXT}")

    def _contact_support(self) -> None:
        self.auth_status.setText("SUPPORT: CONTACT THE THRIVEBERG TERMINAL ADMINISTRATOR")
        self.auth_status.setStyleSheet(f"color:{AJAX_TEXT}")

    def _select_language(self, language: str) -> None:
        for name, button in self._language_buttons.items():
            selected = name == language
            button.setChecked(selected)
            button.setText(f"✓ {name}" if selected else name)
        self.settings.setValue("login/language", language)
        self.settings.sync()

    def _submit_auth(self) -> None:
        if self._auth_worker is not None:
            return
        email = self.auth_email.text().strip()
        password = self.auth_password.text()
        registering = self._auth_mode == "register"
        if not email or not password:
            self._auth_failed("Email and password are required")
            return
        if registering:
            username = self.auth_username.text().strip()
            display_name = self.auth_name.text().strip()
            if password != self.auth_confirm.text():
                self._auth_failed("Passwords do not match")
                return
            operation = lambda: self.social_service.register(email, password, username, display_name)
            status = "CREATING SECURE ACCOUNT..."
        else:
            operation = lambda: self.social_service.sign_in(email, password)
            status = "AUTHENTICATING..."
        self.auth_submit.setEnabled(False)
        self.auth_status.setText(status)
        self.auth_status.setStyleSheet(f"color:{AJAX_AMBER}")
        worker = AsyncOperation(operation)
        self._auth_worker = worker
        worker.succeeded.connect(self._auth_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._auth_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._auth_thread_finished, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @Slot(object)
    def _auth_succeeded(self, result: object) -> None:
        self.auth_submit.setEnabled(True)
        message = "SIGNED IN"
        session = result
        if isinstance(result, tuple):
            session, message = result
        if session is None:
            self._set_auth_mode("signin")
            self.auth_status.setText(str(message).upper())
            self.auth_status.setStyleSheet(f"color:{AJAX_AMBER}")
            return
        self._alert_session_serial += 1
        self._authenticated = True
        self.settings.setValue("login/name", self.auth_email.text().strip())
        self.settings.sync()
        self.auth_password.clear()
        self.auth_confirm.clear()
        self.user_label.setText(f"@{session.username.upper()}")
        self._begin_boot_sequence(session)

    def _begin_boot_sequence(self, _session: object) -> None:
        if self._startup_completed_once:
            self._enter_workspace()
            return
        self.window_chrome.hide()
        self._configure_splash_window()
        self.splash_page.reset()
        self.lifecycle.setCurrentWidget(self.splash_page)
        manager = StartupManager(self._startup_stages(), parent=self)
        self._startup_manager = manager
        manager.stage_started.connect(self.splash_page.stage_started)
        manager.stage_progress.connect(self.splash_page.stage_progress)
        manager.stage_completed.connect(self.splash_page.stage_completed)
        manager.stage_failed.connect(self.splash_page.stage_failed)
        manager.startup_completed.connect(self._startup_finished)
        manager.start()

    def _configure_splash_window(self) -> None:
        self.setMaximumSize(16_777_215, 16_777_215)
        self.setMinimumSize(1100, 700)
        self.showMaximized()

    def _startup_stages(self) -> tuple[StartupStage, ...]:
        def core(report) -> str:
            report(0.25, "CHECKING LOCAL STORE")
            required = {"cache", "watchlists", "workspace_snapshots"}
            with get_connection(self.market_service.cache.path) as connection:
                rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                available = {str(row["name"]) for row in rows}
                connection.execute("SELECT 1").fetchone()
            missing = sorted(required - available)
            if missing:
                raise RuntimeError("Missing local tables: " + ", ".join(missing))
            report(0.75, "LOCAL STORE READY")
            if self._require_login and not self.social_service.configured:
                raise RuntimeError("Authentication service is not configured")
            return "CORE SERVICES READY"

        def data(report) -> str:
            report(0.25, "CHECKING PROVIDERS")
            providers = tuple(self.market_service.market_providers)
            statements = tuple(self.market_service.statement_providers)
            if not providers or not statements:
                raise RuntimeError("No market data providers are configured")
            report(0.65, "CHECKING LOCAL CACHE")
            with get_connection(self.market_service.cache.path) as connection:
                connection.execute("SELECT COUNT(*) FROM cache").fetchone()
            return f"{len(providers)} MARKET / {len(statements)} STATEMENT PROVIDERS"

        def markets(report) -> str:
            report(0.25, "LOADING INSTRUMENT CATALOG")
            instruments = self.registry.list()
            if not instruments:
                raise RuntimeError("Instrument catalog is empty")
            report(0.65, "LOADING WATCHLISTS")
            watchlists = self.market_service.watchlists.names()
            self.market_service.watchlists.symbols(watchlists[0])
            return f"{len(instruments)} INSTRUMENTS / {len(watchlists)} WATCHLISTS"

        def news(report) -> str:
            report(0.3, "CHECKING NEWS SOURCES")
            providers = tuple(self.news_service.providers)
            if not providers:
                raise RuntimeError("No news providers are configured")
            report(0.7, "READING NEWS CACHE")
            cached = self.news_service._cached_items(None)
            return f"{len(providers)} SOURCES / {len(cached)} CACHED HEADLINES"

        def workspace(report) -> str:
            report(0.3, "READING WORKSPACES")
            snapshots = self.workspace_store.list()
            report(0.7, "RESTORING SESSION ROUTE")
            if self._restored_session_command:
                resolve_desktop_command(self._restored_session_command)
            return f"{len(snapshots)} SAVED WORKSPACES"

        return (
            StartupStage("CORE", core, critical=True),
            StartupStage("DATA", data),
            StartupStage("MARKETS", markets),
            StartupStage("NEWS", news),
            StartupStage("WORKSPACE", workspace, critical=True),
        )

    @Slot(bool, object)
    def _startup_finished(self, success: bool, failures: object) -> None:
        failure_rows = tuple(failures) if isinstance(failures, (tuple, list)) else ()
        if not success:
            self.splash_page.finish(failed=True)
            return
        self._startup_completed_once = True
        self.splash_page.finish(degraded=bool(failure_rows))
        QTimer.singleShot(350, self._enter_workspace)

    def _enter_workspace(self) -> None:
        if not self._authenticated:
            return
        self.window_chrome.show()
        self.lifecycle.setCurrentWidget(self.workspace_tabs)
        self.workspace_tabs.setCurrentIndex(0)
        self._configure_workspace_window()
        self.social_workspace.activate()
        self._start_background_alerts()
        if self._session_persistence_enabled:
            restored_symbol = str(self.settings.value("session/current_symbol", "") or "").strip().upper()
            restored_history = self.settings.value("session/history", []) or []
            if isinstance(restored_history, str):
                restored_history = [restored_history]
            self.current_symbol = restored_symbol
            routes = [
                resolve_desktop_command(str(item), restored_symbol)
                for item in restored_history
                if str(item).strip()
            ]
            if routes:
                self._history = routes[-50:]
                self._history_index = len(self._history) - 1
                self._update_navigation()
        command = self._startup_command
        self._startup_command = None
        if not command and self._restored_tab_commands:
            QTimer.singleShot(0, self._restore_session_tabs)
            if not self._previous_clean_shutdown:
                self.statusBar().showMessage("PREVIOUS SESSION RECOVERED", 8_000)
        elif command:
            QTimer.singleShot(0, lambda: self.execute_text(command))
            if not self._previous_clean_shutdown:
                self.statusBar().showMessage("PREVIOUS SESSION RECOVERED", 8_000)
        elif self._restored_session_command:
            QTimer.singleShot(0, lambda: self.execute_text(self._restored_session_command))
        else:
            QTimer.singleShot(0, lambda: self.execute_text("HOME"))
        if self._session_persistence_enabled:
            QTimer.singleShot(900, self._open_startup_global_overview)

    def _restore_session_tabs(self) -> None:
        commands = self._restored_tab_commands or (self._restored_session_command or "HOME",)
        self.document_tabs.setCurrentIndex(0)
        self.execute_text(commands[0], record_history=False)
        for command in commands[1:12]:
            self._create_terminal_tab(command)
        active = min(self._restored_tab_index, self.document_tabs.count() - 1)
        self.document_tabs.setCurrentIndex(max(active, 0))

    @Slot(str)
    def _auth_failed(self, message: str) -> None:
        self.auth_submit.setEnabled(True)
        self.auth_status.setText(message.upper())
        self.auth_status.setStyleSheet(f"color:{AJAX_RED}")

    @Slot()
    def _auth_thread_finished(self) -> None:
        worker = self.sender()
        if worker is self._auth_worker:
            self._auth_worker = None

    def start(self, initial_command: str | None = None) -> None:
        self._startup_command = initial_command
        if self._authenticated:
            self.lifecycle.setCurrentWidget(self.workspace_tabs)
            if initial_command:
                QTimer.singleShot(0, lambda: self.execute_text(initial_command))
            else:
                QTimer.singleShot(0, lambda: self.execute_text("HOME"))

    def logout(self) -> None:
        if not self._authenticated:
            self._show_login()
            return
        session = self.social_service.session
        provider = self.social_service.provider
        self.alert_timer.stop()
        self._alert_session_serial += 1
        self._alert_started_once = False
        self.alert_status_label.setText("ALRT BG --")
        self.alert_status_label.setStyleSheet(f"color:{AJAX_MUTED}")
        self._authenticated = False
        self.social_workspace.poll_timer.stop()
        self.current_symbol = ""
        self.current_route = DesktopRoute("home", "", raw="HOME")
        self._history = [self.current_route]
        self._history_index = 0
        self._update_navigation()
        self.user_label.setText("SIGNED OUT")
        self.auth_password.clear()
        self.auth_confirm.clear()
        self.social_service.session = None
        self.close_global_overview()
        self._set_auth_mode("signin")
        self._show_login()
        if provider is not None and session is not None:
            worker = AsyncOperation(lambda: provider.sign_out(session))
            self._logout_worker = worker
            worker.succeeded.connect(self._logout_finished, Qt.ConnectionType.QueuedConnection)
            worker.failed.connect(self._logout_finished, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(self._logout_thread_finished, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(worker.deleteLater)
            worker.start()

    @Slot()
    @Slot(object)
    def _logout_finished(self, _result: object = None) -> None:
        pass

    @Slot()
    def _logout_thread_finished(self) -> None:
        worker = self.sender()
        if worker is self._logout_worker:
            self._logout_worker = None

    def _escape_action(self) -> None:
        if self.lifecycle.currentWidget() in {self.auth_page, self.splash_page}:
            self.close()
        elif not self.suggestion_panel.isHidden():
            self._hide_suggestions()
        else:
            self.command.clear()
            self.command.setFocus()

    def _focus_command(self) -> None:
        if not self._authenticated:
            return
        self.workspace_tabs.setCurrentIndex(0)
        self.command.setFocus()

    @Slot(int)
    def _workspace_tab_changed(self, index: int) -> None:
        if index == 1 and self._authenticated:
            self.social_workspace.activate()

    def _create_terminal_tab(
        self,
        command: str = "HOME",
        *,
        activate: bool = True,
        execute: bool = True,
        inherit_symbol: bool = True,
    ) -> _TerminalTabState:
        inherited_symbol = self.current_symbol if inherit_symbol else ""
        home = DesktopRoute("home", inherited_symbol, raw="HOME")
        stack = QStackedWidget()
        stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        placeholder = QFrame()
        placeholder.setObjectName("emptyWorkspace")
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(36, 30, 36, 30)
        placeholder_layout.addWidget(QLabel("NEW WORKSPACE"))
        placeholder_layout.addStretch(1)
        stack.addWidget(placeholder)
        state = _TerminalTabState(stack, home, inherited_symbol, [home])
        self._terminal_tabs[stack] = state
        index = self.document_tabs.addTab(stack, "MARKETS")
        self.document_tabs.setTabToolTip(index, "HOME")
        if activate or self._active_terminal_tab is None:
            self.document_tabs.setCurrentIndex(index)
            self._terminal_tab_changed(index)
        if execute:
            self.execute_text(command)
        return state

    @Slot()
    def new_terminal_tab(self) -> None:
        self.workspace_tabs.setCurrentIndex(0)
        self._create_terminal_tab("HOME")
        QTimer.singleShot(0, self.command.setFocus)

    @Slot(int)
    def _terminal_tab_changed(self, index: int) -> None:
        stack = self.document_tabs.widget(index)
        state = self._terminal_tabs.get(stack)
        if state is None:
            return
        previous = self._active_terminal_tab
        if previous is not None and previous is not state:
            self._capture_terminal_tab_state(previous)
        self._active_terminal_tab = state
        self._restore_terminal_tab_state(state)
        if hasattr(self, "footer"):
            self._persist_session_state()

    def _capture_terminal_tab_state(self, state: _TerminalTabState | None = None) -> None:
        state = state or self._active_terminal_tab
        if state is None:
            return
        state.current_route = self.current_route
        state.current_symbol = self.current_symbol
        state.history = self._history
        state.history_index = self._history_index
        state.engine_text = self.engine_label.text()
        state.instrument_text = self.instrument_bar.text()
        state.popout_enabled = self.popout_button.isEnabled()
        state.popout_text = self.popout_button.text()
        index = self.document_tabs.indexOf(state.stack)
        if index >= 0:
            self.document_tabs.setTabText(index, self._terminal_tab_title(state.current_route))
            self.document_tabs.setTabToolTip(index, state.current_route.raw or "HOME")

    def _restore_terminal_tab_state(self, state: _TerminalTabState) -> None:
        self.stack = state.stack
        self.current_route = state.current_route
        self.current_symbol = state.current_symbol
        self._history = state.history
        self._history_index = state.history_index
        self._set_route_labels(state.current_route)
        self.engine_label.setText(state.engine_text)
        self.instrument_bar.setText(state.instrument_text)
        self.popout_button.setEnabled(state.popout_enabled)
        self.popout_button.setText(state.popout_text)
        self._update_navigation()

    def _terminal_tab_title(self, route: DesktopRoute) -> str:
        if route.kind == "home":
            return "MARKETS"
        if route.kind == "select":
            return f"{route.target} MENU"[:28]
        parsed = parse_command(route.raw)
        command = parsed.action.value if parsed.action != CommandAction.UNKNOWN else route.kind.upper()
        if route.target:
            if route.kind in _SECURITY_ROUTE_KINDS:
                return f"{route.target} {command}"[:28]
            return f"{command} {route.target}"[:28]
        return str(command)[:28]

    @Slot(int)
    def close_terminal_tab(self, index: int) -> None:
        if self.document_tabs.count() <= 1:
            self.document_tabs.setCurrentIndex(0)
            self.execute_text("HOME")
            return
        stack = self.document_tabs.widget(index)
        state = self._terminal_tabs.get(stack)
        if state is None:
            return
        was_active = state is self._active_terminal_tab
        if was_active:
            self._capture_terminal_tab_state(state)
        state.load_serial += 1
        self.document_tabs.blockSignals(True)
        self.document_tabs.removeTab(index)
        self.document_tabs.blockSignals(False)
        self._terminal_tabs.pop(stack, None)
        while stack.count():
            widget = stack.widget(0)
            stack.removeWidget(widget)
            self._dispose_workspace(widget)
        stack.deleteLater()
        if was_active:
            self._active_terminal_tab = None
            next_index = min(index, self.document_tabs.count() - 1)
            self.document_tabs.setCurrentIndex(next_index)
            self._terminal_tab_changed(next_index)
        self._persist_session_state()

    @Slot()
    def close_current_terminal_tab(self) -> None:
        if self.workspace_tabs.currentIndex() != 0:
            self.workspace_tabs.setCurrentIndex(0)
            return
        self.close_terminal_tab(self.document_tabs.currentIndex())

    @Slot(int)
    def _terminal_tab_double_clicked(self, index: int) -> None:
        if index >= 0:
            self.document_tabs.setCurrentIndex(index)
            self.open_current_tab_window()

    def _cycle_terminal_tab(self, step: int) -> None:
        count = self.document_tabs.count()
        if count < 2:
            return
        self.workspace_tabs.setCurrentIndex(0)
        self.document_tabs.setCurrentIndex((self.document_tabs.currentIndex() + step) % count)

    @Slot()
    def open_current_tab_window(self) -> None:
        state = self._active_terminal_tab
        if state is None:
            return
        self._capture_terminal_tab_state(state)
        command = state.current_route.raw or "HOME"
        window = AjaxDesktopWindow(require_login=False)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.setWindowTitle(f"THRIVEBERG Terminal - {self._terminal_tab_title(state.current_route)}")
        self._secondary_windows.append(window)
        window.destroyed.connect(lambda _obj=None, child=window: self._forget_secondary_window(child))
        window.showNormal()
        screens = QApplication.screens()
        if screens:
            current_screen = self.screen() or QApplication.primaryScreen()
            current_index = screens.index(current_screen) if current_screen in screens else 0
            target = screens[(current_index + len(self._secondary_windows)) % len(screens)]
            window.move(target.availableGeometry().topLeft())
            window.resize(target.availableGeometry().size())
            window.showMaximized()
        else:
            window.show()
        window.start(command)
        self.statusBar().showMessage(f"WORKSPACE WINDOW OPENED: {command}", 6_000)

    def _forget_secondary_window(self, window: AjaxDesktopWindow) -> None:
        if window in self._secondary_windows:
            self._secondary_windows.remove(window)

    @Slot()
    def configure_global_overview(self) -> None:
        if self._compact_mode:
            return
        dialog = GlobalOverviewSettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        enabled, screen_name, commands = dialog.configuration()
        self.settings.setValue("overview/enabled", enabled)
        self.settings.setValue("overview/screen_name", screen_name)
        self.settings.setValue("overview/commands", list(commands))
        self.settings.sync()
        self.close_global_overview()
        if enabled:
            self.open_global_overview(force=True)
        else:
            self.statusBar().showMessage("GLOBAL OVERVIEW DISABLED", 6_000)

    @Slot()
    def open_global_overview(self, *, force: bool = False) -> None:
        if self._compact_mode:
            return
        existing = self._global_overview_window
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        target = self._global_overview_target_screen(allow_current=force)
        if target is None:
            self.statusBar().showMessage(
                "GLOBAL OVERVIEW REQUIRES A SECOND DISPLAY; USE WALL CONFIG TO CHOOSE ONE",
                8_000,
            )
            return
        wall = GlobalOverviewWindow(_global_overview_commands(self.settings), target)
        self._global_overview_window = wall
        wall.destroyed.connect(
            lambda _obj=None, active=wall: self._forget_global_overview(active)
        )
        wall.show_on_screen()
        self._global_overview_opened_once = True
        self.statusBar().showMessage(
            f"GLOBAL OVERVIEW OPENED ON {target.name()}",
            6_000,
        )

    @Slot()
    def close_global_overview(self) -> None:
        wall = self._global_overview_window
        self._global_overview_window = None
        if wall is not None:
            wall.close()

    def _forget_global_overview(self, wall: GlobalOverviewWindow) -> None:
        if wall is self._global_overview_window:
            self._global_overview_window = None

    def _global_overview_target_screen(self, *, allow_current: bool = False):
        screens = QApplication.screens()
        if not screens:
            return None
        selected = str(self.settings.value("overview/screen_name", "") or "")
        current = self.screen() or QApplication.primaryScreen()
        named = next((screen for screen in screens if screen.name() == selected), None)
        if named is not None and (allow_current or named is not current or len(screens) > 1):
            return named
        secondary = next((screen for screen in screens if screen is not current), None)
        if secondary is not None:
            return secondary
        return current if allow_current else None

    def _open_startup_global_overview(self) -> None:
        if (
            self._compact_mode
            or self._global_overview_opened_once
            or not self.settings.value("overview/enabled", True, type=bool)
        ):
            return
        self.open_global_overview(force=False)

    def _execute_for_stack(self, stack: QStackedWidget, command: str) -> None:
        index = self.document_tabs.indexOf(stack)
        if index < 0:
            return
        self.workspace_tabs.setCurrentIndex(0)
        self.document_tabs.setCurrentIndex(index)
        self.execute_text(command)

    def _connect_tab_command(self, signal: Signal) -> None:
        stack = self.stack
        signal.connect(lambda command, target=stack: self._execute_for_stack(target, command))

    def _run_in_terminal_tab(self, state: _TerminalTabState, callback: Callable[[], None]) -> None:
        if state.stack not in self._terminal_tabs:
            return
        active = self._active_terminal_tab
        if active is state:
            callback()
            self._capture_terminal_tab_state(state)
            return
        if active is not None:
            self._capture_terminal_tab_state(active)
        self.current_route = state.current_route
        self.current_symbol = state.current_symbol
        self._history = state.history
        self._history_index = state.history_index
        self.stack = state.stack
        try:
            callback()
            self._capture_terminal_tab_state(state)
        finally:
            if active is not None and active.stack in self._terminal_tabs:
                self._active_terminal_tab = active
                self._restore_terminal_tab_state(active)

    @Slot(str)
    def _open_shared_command(self, command: str) -> None:
        self.workspace_tabs.setCurrentIndex(0)
        self.execute_text(command)

    def _system_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("systemBar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(24)
        brand = QLabel("THRIVEBERG TERMINAL")
        brand.setStyleSheet(f"color:{AJAX_AMBER};font-weight:bold")
        row.addWidget(brand)
        self.local_clock = QLabel()
        self.utc_clock = QLabel()
        row.addWidget(self.local_clock)
        row.addWidget(self.utc_clock)
        row.addWidget(QLabel("DATA: AUTO"))
        row.addWidget(QLabel("MARKET WORKSTATION"))
        self.alert_status_label = QLabel("ALRT BG --")
        self.alert_status_label.setStyleSheet(f"color:{AJAX_MUTED}")
        row.addWidget(self.alert_status_label)
        row.addStretch(1)
        self.user_label = QLabel("SIGNED OUT")
        self.user_label.setStyleSheet(f"color:{AJAX_TEXT}")
        row.addWidget(self.user_label)
        self.engine_label = QLabel("NATIVE QT / WEBENGINE / VTK")
        self.engine_label.setStyleSheet(f"color:{AJAX_MUTED}")
        row.addWidget(self.engine_label)
        return frame

    def _menu_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("menuBar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(1)
        self.back_button = _button("<", self.go_back)
        self.forward_button = _button(">", self.go_forward)
        row.addWidget(_button("GO", lambda: self.command.setFocus()))
        row.addWidget(self.back_button)
        row.addWidget(self.forward_button)
        row.addWidget(_button("F1 HELP", lambda: self._show_message("HELP", "TYPE A SECURITY, THEN GP, OVDV OR CURVE.")))
        row.addWidget(_button("MARKETS", lambda: self.execute_text("HOME")))
        row.addWidget(_button("WATC", lambda: self.execute_text("WATC")))
        row.addWidget(_button("PORT", lambda: self.execute_text("PORT")))
        row.addWidget(_button("ALRT", lambda: self.execute_text("ALRT")))
        row.addWidget(_button("EQS", lambda: self.execute_text("EQS")))
        row.addWidget(_button("EVT", lambda: self.execute_text("EVT")))
        row.addWidget(_button("MAP", lambda: self.execute_text("MAP")))
        row.addWidget(_button("WALL", lambda: self.execute_text("WALL")))
        row.addWidget(_button("SOCIAL", lambda: self.execute_text("SOCIAL")))
        tools_button = _button("TOOLS", lambda: None)
        tools_menu = QMenu(tools_button)
        tools_menu.addAction("CURVE  YIELD CURVES", lambda: self.execute_text("CURVE USD"))
        tools_menu.addAction("DQM  DATA QUALITY", lambda: self.execute_text("DQM"))
        tools_menu.addAction("WSP  WORKSPACES", lambda: self.execute_text("WSP"))
        tools_menu.addAction("UPD  BETA RELEASES", lambda: self.execute_text("UPD"))
        tools_menu.addAction("DIAG  SYSTEM DIAGNOSTICS", lambda: self.execute_text("DIAG"))
        tools_menu.addAction("DOOM  CLASSIC GAME", lambda: self.execute_text("DOOM"))
        tools_menu.addSeparator()
        tools_menu.addAction(
            "WALL  GLOBAL OVERVIEW",
            lambda: self.open_global_overview(force=True),
        )
        tools_menu.addAction("WALL CONFIG  DISPLAY LAYOUT", self.configure_global_overview)
        tools_menu.addSeparator()
        tools_menu.addAction("NEW WORKSPACE TAB    CTRL+T", self.new_terminal_tab)
        tools_menu.addAction("OPEN TAB IN WINDOW   CTRL+SHIFT+D", self.open_current_tab_window)
        tools_menu.addSeparator()
        tools_menu.addAction("DATA CONNECTIONS", self._show_data_connections)
        tools_button.setMenu(tools_menu)
        row.addWidget(tools_button)
        row.addStretch(1)
        row.addWidget(_button("LOGOUT", self.logout))
        self.popout_button = _button("POP OUT", self.pop_out)
        self.popout_button.setEnabled(False)
        row.addWidget(self.popout_button)
        return frame

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt callback
        if watched is self.command and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if not self.suggestion_panel.isHidden():
                if key in {Qt.Key.Key_Down, Qt.Key.Key_Up} and self._suggestions:
                    current = max(self.suggestion_table.currentRow(), 0)
                    step = 1 if key == Qt.Key.Key_Down else -1
                    row = (current + step) % len(self._suggestions)
                    self.suggestion_table.setCurrentCell(row, 0)
                    return True
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab} and self._suggestions:
                    self._accept_suggestion(max(self.suggestion_table.currentRow(), 0))
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_suggestions()
                    return True
        return super().eventFilter(watched, event)

    @Slot(str)
    def _command_text_changed(self, text: str) -> None:
        clean = " ".join(text.strip().upper().split())
        self._suggestion_timer.stop()
        self._suggestion_serial += 1
        if not clean:
            self._hide_suggestions(invalidate=False)
            return

        command_rows = self._command_suggestion_rows(clean)
        if command_rows:
            self._render_suggestions(command_rows, "FUNCTION SEARCH  |  LOCAL COMMAND DIRECTORY")
            return

        search_query, _function = security_search_context(clean)
        if not search_query:
            self._hide_suggestions(invalidate=False)
            return
        local_results = [
            (item.symbol, item.name, str(item.asset_class))
            for item in self.registry.search(search_query, limit=8)
        ]
        local_rows = security_suggestions(clean, local_results, source="LOCAL")
        status = "SECURITY SEARCH  |  LOCAL MATCHES  |  GLOBAL DIRECTORY..."
        self._render_suggestions(local_rows, status, show_empty=True)
        if len(search_query.replace(" ", "")) >= 2:
            self._suggestion_timer.start()

    def _command_suggestion_rows(self, clean: str) -> list[SecuritySuggestion]:
        parts = clean.split()
        is_command_prefix = any(item.command.startswith(clean) for item in COMMANDS)
        is_bare_security_function = len(parts) == 1 and parts[0] in SYMBOL_FUNCTIONS
        if not (is_command_prefix or is_bare_security_function):
            return []
        if is_bare_security_function and not any(item.command == clean for item in COMMANDS):
            function = parts[0]
            return [
                SecuritySuggestion(
                    command=function,
                    symbol=function,
                    name=SYMBOL_FUNCTIONS[function],
                    security_type="FUNCTION",
                    source="LOCAL",
                )
            ]
        return [
            SecuritySuggestion(
                command=item.command,
                symbol=item.command,
                name=item.description,
                security_type="FUNCTION",
                source="LOCAL",
            )
            for item in command_suggestions(clean, self.registry, limit=8)
            if item.description != "Resolve ticker dynamically"
        ]

    def _start_remote_suggestion_search(self) -> None:
        raw = " ".join(self.command.text().strip().upper().split())
        search_query, _function = security_search_context(raw)
        if not search_query:
            return
        self._suggestion_serial += 1
        serial = self._suggestion_serial
        worker = _Loader(lambda: asyncio.run(self.market_service.search(search_query)))
        self._suggestion_workers.append(worker)
        worker.loaded.connect(
            lambda results, token=serial, query=raw: self._remote_suggestions_loaded(token, query, results),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            lambda _error, token=serial, query=raw: self._remote_suggestions_failed(token, query),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(
            lambda active=worker: self._release_suggestion_worker(active),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _remote_suggestions_loaded(self, serial: int, raw: str, results: object) -> None:
        if serial != self._suggestion_serial:
            return
        current = " ".join(self.command.text().strip().upper().split())
        if current != raw or not isinstance(results, list):
            return
        rows = security_suggestions(raw, results, source="GLOBAL")
        self._render_suggestions(rows, "SECURITY SEARCH  |  LOCAL CATALOG + GLOBAL DIRECTORY")

    def _remote_suggestions_failed(self, serial: int, raw: str) -> None:
        if serial != self._suggestion_serial:
            return
        current = " ".join(self.command.text().strip().upper().split())
        if current == raw:
            self.suggestion_status.setText("SECURITY SEARCH  |  LOCAL CATALOG  |  GLOBAL DIRECTORY UNAVAILABLE")

    def _release_suggestion_worker(self, worker: _Loader) -> None:
        if worker in self._suggestion_workers:
            self._suggestion_workers.remove(worker)

    def _render_suggestions(
        self,
        rows: list[SecuritySuggestion],
        status: str,
        *,
        show_empty: bool = False,
    ) -> None:
        unique: list[SecuritySuggestion] = []
        seen: set[str] = set()
        for row in rows:
            if row.command in seen:
                continue
            seen.add(row.command)
            unique.append(row)
        self._suggestions = unique[:8]
        self.suggestion_status.setText(status)
        self.suggestion_table.setRowCount(len(self._suggestions))
        for index, suggestion in enumerate(self._suggestions):
            action = "SELECT" if suggestion.command == suggestion.symbol else suggestion.command.split()[-1]
            values = (suggestion.symbol, suggestion.name, suggestion.security_type, action)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if column == 0:
                    item.setForeground(QColor(AJAX_TEXT))
                elif column == 3:
                    item.setForeground(QColor(AJAX_AMBER))
                self.suggestion_table.setItem(index, column, item)
        if self._suggestions:
            self.suggestion_table.setCurrentCell(0, 0)
        table_height = 31 + 28 * max(len(self._suggestions), 1)
        self.suggestion_table.setFixedHeight(table_height)
        self.suggestion_panel.setFixedHeight(28 + table_height)
        self.suggestion_panel.setVisible(bool(self._suggestions) or show_empty)

    @Slot(int)
    @Slot(int, int)
    def _accept_suggestion(self, row: int, _column: int = 0) -> None:
        if not 0 <= row < len(self._suggestions):
            return
        suggestion = self._suggestions[row]
        command = suggestion.command
        if suggestion.security_type != "FUNCTION":
            self._security_directory[suggestion.symbol] = (suggestion.name, suggestion.security_type)
        self._hide_suggestions()
        self.command.clear()
        self.execute_text(command)
        QTimer.singleShot(0, self.command.setFocus)

    def _hide_suggestions(self, *, invalidate: bool = True) -> None:
        self._suggestion_timer.stop()
        if invalidate:
            self._suggestion_serial += 1
        self._suggestions = []
        self.suggestion_table.setRowCount(0)
        self.suggestion_panel.hide()

    def _submit_command(self) -> None:
        raw = self.command.text()
        self._hide_suggestions()
        self.command.clear()
        if raw.strip():
            self.execute_text(raw)

    def execute_text(self, raw: str, *, record_history: bool = True) -> None:
        self._hide_suggestions()
        clean = " ".join(raw.strip().upper().split())
        if clean in {"LOGOUT", "SIGN OUT", "SIGNOUT"}:
            self.logout()
            return
        if clean in {"TAB", "TAB NEW", "NEWTAB"}:
            self.new_terminal_tab()
            return
        if clean.startswith("TAB NEW "):
            self._create_terminal_tab(clean.removeprefix("TAB NEW "))
            return
        if clean in {"TAB CLOSE", "CLOSETAB"}:
            self.close_current_terminal_tab()
            return
        if clean in {"TAB WINDOW", "TAB DETACH", "NEWWINDOW"}:
            self.open_current_tab_window()
            return
        if clean in {"WALL", "WALL OPEN", "GLOBAL OVERVIEW"}:
            self.open_global_overview(force=True)
            return
        if clean in {"WALL CONFIG", "WALL SETTINGS"}:
            self.configure_global_overview()
            return
        if clean == "WALL ON":
            self.settings.setValue("overview/enabled", True)
            self.settings.sync()
            self.open_global_overview(force=True)
            return
        if clean in {"WALL CLOSE", "WALL HIDE"}:
            self.close_global_overview()
            return
        if clean == "WALL OFF":
            self.settings.setValue("overview/enabled", False)
            self.settings.sync()
            self.close_global_overview()
            self.statusBar().showMessage("GLOBAL OVERVIEW AUTO-OPEN DISABLED", 6_000)
            return
        if clean == "WALL RESET":
            self.settings.setValue("overview/enabled", True)
            self.settings.setValue(
                "overview/commands",
                [command for _title, command in _GLOBAL_OVERVIEW_PANELS],
            )
            self.settings.sync()
            self.close_global_overview()
            self.open_global_overview(force=True)
            return
        route = resolve_desktop_command(raw, self.current_symbol)
        if route.kind == "social":
            self.workspace_tabs.setCurrentIndex(1)
            self.social_workspace.activate()
            QTimer.singleShot(0, self.workspace_ready.emit)
            return
        self.popout_button.setText("POP OUT")
        parsed = parse_command(route.raw)
        if route.kind != "social":
            self.workspace_tabs.setCurrentIndex(0)
        if route.kind == "select":
            self.current_symbol = route.target
            self.current_route = route
            self._record(route, record_history)
            self._set_route_labels(route)
            self._capture_terminal_tab_state()
            self._persist_session_state()
            self._show_security_function_menu(route.target)
            return
        if self._is_security_context(route, parsed):
            self.current_symbol = route.target
        self.current_route = route
        self._record(route, record_history)
        self._set_route_labels(route)
        self._capture_terminal_tab_state()
        self._persist_session_state()
        if route.kind == "home":
            self._show_home()
        elif route.kind == "security-required":
            self.engine_label.setText("SECURITY SELECTION REQUIRED")
            self.popout_button.setEnabled(False)
            self._show_message(
                "NO SECURITY LOADED",
                f"{route.raw} REQUIRES AN ACTIVE SECURITY. ENTER A NAME OR TICKER, THEN SELECT THE FUNCTION.",
            )
            QTimer.singleShot(0, self.command.setFocus)
        elif route.kind == "price":
            self._load_workspace(
                "LIGHTWEIGHT CHARTS",
                lambda: _load_price(route.target, route.period or "1Y", route.interval),
                self._mount_price,
            )
        elif route.kind == "curve":
            self._load_workspace("APACHE ECHARTS", lambda: _load_curve(route.target), self._mount_curve)
        elif route.kind == "macro-map":
            self._load_workspace(
                "APACHE ECHARTS / GLOBAL MACRO",
                lambda: load_macro_map(parsed.args),
                self._mount_macro_map,
            )
        elif route.kind == "news":
            self._load_workspace(
                "NATIVE NEWS WIRE",
                lambda: load_news(route.target),
                self._mount_news,
            )
        elif route.kind == "watchlist":
            self._load_workspace(
                "NATIVE EDITABLE WATCHLIST",
                lambda: load_watchlist(parsed.args),
                self._mount_watchlist,
            )
        elif route.kind == "portfolio":
            self._load_workspace(
                "NATIVE PORTFOLIO MANAGER",
                lambda: load_portfolio(parsed.args),
                self._mount_portfolio,
            )
        elif route.kind == "alerts":
            self._load_workspace(
                "NATIVE MARKET ALERTS",
                lambda: load_alerts(parsed.args),
                self._mount_alerts,
            )
        elif route.kind == "workspaces":
            self._show_workspace_manager()
        elif route.kind == "updates":
            self._load_workspace(
                "SIGNED RELEASE MANAGER",
                fetch_update_catalog,
                self._mount_updates,
            )
        elif route.kind == "diagnostics":
            self._load_workspace(
                "SYSTEM DIAGNOSTICS",
                collect_diagnostics,
                self._mount_diagnostics,
            )
        elif route.kind == "doom":
            self._mount_doom()
        elif route.kind == "ovdv":
            self._load_workspace("PYVISTA / VTK", lambda: _load_surface(route.target), self._mount_ovdv)
        elif route.kind == "option-monitor":
            expiry = parsed.args[1] if len(parsed.args) > 1 else None
            self._load_workspace(
                "NATIVE OPTION MONITOR",
                lambda: load_option_monitor(route.target, expiry),
                self._mount_options,
            )
        elif route.kind == "option-valuation":
            side = parsed.args[1] if len(parsed.args) > 1 else None
            strike = parsed.args[2] if len(parsed.args) > 2 else None
            expiry = parsed.args[3] if len(parsed.args) > 3 else None
            self._load_workspace(
                "NATIVE OPTION VALUATION",
                lambda: load_option_valuation(route.target, side, strike, expiry),
                self._mount_options,
            )
        elif route.kind == "description":
            self._load_workspace(
                "NATIVE SECURITY DESCRIPTION",
                lambda: load_security_description(route.target),
                self._mount_description,
            )
        elif route.kind == "data-audit":
            field_filter = " ".join(parsed.args[1:]) if len(parsed.args) > 1 else ""
            self._load_workspace(
                "FIELD PROVENANCE AUDIT",
                lambda: load_data_audit(route.target, field_filter),
                self._mount_data_audit,
            )
        elif route.kind == "data-quality":
            self._load_workspace(
                "NATIVE DATA QUALITY MONITOR",
                lambda: load_data_quality_dashboard(parsed.args),
                self._mount_data_quality,
            )
        elif route.kind == "financial-analysis":
            self._load_workspace(
                "NATIVE FINANCIAL ANALYSIS",
                lambda: load_financial_analysis(route.target),
                self._mount_financial_analysis,
            )
        elif route.kind.startswith("financial-") and route.kind != "financial-export":
            statement_types = {
                "financial-income": StatementType.INCOME,
                "financial-balance": StatementType.BALANCE_SHEET,
                "financial-cashflow": StatementType.CASH_FLOW,
            }
            refresh = route.raw.endswith(" REFRESH")
            self._load_workspace(
                "NATIVE FINANCIAL STATEMENTS",
                lambda: load_financial_statement(
                    route.target,
                    statement_types[route.kind],
                    refresh=refresh,
                ),
                self._mount_financial_statement,
            )
        elif route.kind == "financial-export":
            self._load_workspace(
                "EXCEL EXPORT",
                lambda: export_financial_statements(route.target),
                self._mount_financial_export,
            )
        elif route.kind == "relative-valuation":
            peers = list(parsed.args[1:]) if len(parsed.args) > 1 else None
            self._load_workspace(
                "NATIVE RELATIVE VALUATION",
                lambda: load_relative_valuation(route.target, peers),
                self._mount_research,
            )
        elif route.kind == "estimates":
            self._load_workspace(
                "NATIVE CONSENSUS ESTIMATES",
                lambda: load_estimates(route.target),
                self._mount_research,
            )
        elif route.kind == "analyst":
            self._load_workspace(
                "NATIVE ANALYST CONSENSUS",
                lambda: load_analyst_consensus(route.target),
                self._mount_research,
            )
        elif route.kind == "dividends":
            self._load_workspace(
                "NATIVE DIVIDEND ANALYSIS",
                lambda: load_dividends(route.target),
                self._mount_research,
            )
        elif route.kind == "events":
            self._load_workspace(
                "NATIVE CORPORATE EVENTS",
                lambda: load_events(route.target),
                self._mount_research,
            )
        elif route.kind == "event-calendar":
            try:
                days = max(1, min(365, int(route.period or "30")))
            except ValueError:
                days = 30
            try:
                page = max(1, int(route.interval or "1"))
            except ValueError:
                page = 1
            scope = "ALL"
            selection = ""
            if route.target.startswith("WATC:"):
                scope = "WATCHLIST"
                selection = urllib.parse.unquote(route.target.split(":", 1)[1])
            elif route.target.startswith("PORT:"):
                scope = "PORTFOLIO"
                selection = urllib.parse.unquote(route.target.split(":", 1)[1])
            filters = {"MCAP": "LARGEST", "IND": "ALL", "GEO": "US_LISTED"}
            for token in parsed.args[3:]:
                if ":" not in token:
                    continue
                key, value = token.split(":", 1)
                if key in filters and value:
                    filters[key] = urllib.parse.unquote(value)
            self._load_workspace(
                "NATIVE CORPORATE CALENDAR",
                lambda: load_event_calendar(
                    days,
                    scope,
                    selection,
                    page,
                    market_cap_filter=filters["MCAP"],
                    industry_filter=filters["IND"],
                    geography_filter=filters["GEO"],
                ),
                self._mount_event_calendar,
            )
        elif route.kind in {"filings", "filings-10k", "filings-10q"}:
            filing_modes = {
                "filings": (("10-K", "10-Q"), "FILINGS"),
                "filings-10k": (("10-K",), "10K"),
                "filings-10q": (("10-Q",), "10Q"),
            }
            forms, active = filing_modes[route.kind]
            self._load_workspace(
                "NATIVE REGULATORY FILINGS",
                lambda: load_filings(route.target, forms, active),
                self._mount_research,
            )
        elif route.kind == "screener":
            self._load_workspace(
                "NATIVE EQUITY SCREENING",
                lambda: load_screener(parsed.args),
                self._mount_research,
            )
        elif route.kind == "social":
            self.workspace_tabs.setCurrentIndex(1)
            self.social_workspace.activate()
            QTimer.singleShot(0, self.workspace_ready.emit)
        else:
            columns = max(120, self.stack.width() // 10)
            rows = max(34, self.stack.height() // 20)
            classic_command = route.raw
            global_without_target = {CommandAction.FX, CommandAction.FWD}
            if (
                parsed.action in SECURITY_FUNCTIONS
                and not parsed.target
                and parsed.action not in global_without_target
                and self.current_symbol
            ):
                classic_command = f"{self.current_symbol} {route.raw}"
            self._load_workspace(
                "TEXTUAL / RICH",
                lambda: render_classic_snapshot(
                    classic_command,
                    self.social_service,
                    columns=columns,
                    rows=rows,
                ),
                self._mount_classic,
            )

    def _record(self, route: DesktopRoute, enabled: bool) -> None:
        if not enabled:
            return
        if self._history and self._history[self._history_index] == route:
            return
        del self._history[self._history_index + 1 :]
        self._history.append(route)
        self._history_index = len(self._history) - 1
        self._update_navigation()

    def _persist_session_state(self) -> None:
        if not self._session_persistence_enabled:
            return
        self._capture_terminal_tab_state()
        open_tabs = []
        if hasattr(self, "document_tabs"):
            for index in range(self.document_tabs.count()):
                state = self._terminal_tabs.get(self.document_tabs.widget(index))
                if state is not None:
                    open_tabs.append(state.current_route.raw or "HOME")
        self.settings.setValue("session/last_command", self.current_route.raw or "HOME")
        self.settings.setValue("session/current_symbol", self.current_symbol)
        self.settings.setValue("session/history", [route.raw for route in self._history[-50:] if route.raw])
        self.settings.setValue("session/open_tabs", open_tabs)
        self.settings.setValue("session/active_tab", self.document_tabs.currentIndex())
        self.settings.setValue("session/window_geometry", self.saveGeometry())
        self.settings.setValue("session/window_maximized", self.isMaximized())

    def go_back(self) -> None:
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._open_route(self._history[self._history_index])

    def go_forward(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._open_route(self._history[self._history_index])

    def _open_route(self, route: DesktopRoute) -> None:
        if route.kind == "select":
            self.current_symbol = route.target
            self.current_route = route
            self._set_route_labels(route)
            self._show_message(f"{route.target} SELECTED", "ENTER A FUNCTION: GP  |  OVDV")
        else:
            self.execute_text(route.raw, record_history=False)
        self._update_navigation()

    def _update_navigation(self) -> None:
        self.back_button.setEnabled(self._history_index > 0)
        self.forward_button.setEnabled(self._history_index < len(self._history) - 1)

    def _load_workspace(
        self,
        engine: str,
        loader: Callable[[], object],
        mount: Callable[[object], None],
    ) -> None:
        tab = self._active_terminal_tab
        if tab is None:
            return
        self._load_serial += 1
        serial = self._load_serial
        tab.load_serial += 1
        tab_serial = tab.load_serial
        self.popout_button.setEnabled(False)
        self.engine_label.setText(f"LOADING {engine}...")
        self._show_message(
            f"LOADING {self.current_route.raw}",
            f"INITIALIZING {engine}",
            ready=False,
        )
        thread = _Loader(loader)
        thread.setProperty("ajaxSerial", serial)
        thread.setProperty("terminalTabSerial", tab_serial)
        self._workspace_loaders.append(thread)
        self._workspace_load_contexts[thread] = _WorkspaceLoadContext(
            tab,
            tab_serial,
            engine,
            mount,
        )
        self._loader = thread
        self._pending_mount = mount
        self._pending_engine = engine
        thread.loaded.connect(self._workspace_loaded, Qt.ConnectionType.QueuedConnection)
        thread.failed.connect(self._workspace_failed, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(self._workspace_thread_finished, Qt.ConnectionType.QueuedConnection)
        thread.start()

    @Slot(object)
    def _workspace_loaded(self, model: object) -> None:
        thread = self.sender()
        context = self._workspace_load_contexts.get(thread)
        if context is None or context.serial != context.tab.load_serial:
            return
        self._run_in_terminal_tab(context.tab, lambda: context.mount(model))

    @Slot(str)
    def _workspace_failed(self, message: str) -> None:
        thread = self.sender()
        context = self._workspace_load_contexts.get(thread)
        if context is None or context.serial != context.tab.load_serial:
            return

        def show_error() -> None:
            self.engine_label.setText(f"{context.engine} ERROR")
            self._show_message("DATA / ENGINE ERROR", message, error=True)

        self._run_in_terminal_tab(context.tab, show_error)

    @Slot()
    def _workspace_thread_finished(self) -> None:
        thread = self.sender()
        if thread in self._workspace_loaders:
            self._workspace_loaders.remove(thread)
        self._workspace_load_contexts.pop(thread, None)
        if thread is self._loader:
            self._loader = None
            self._pending_mount = None
        thread.deleteLater()

    def _mount_price(self, model: object) -> None:
        tab_stack = self.stack
        controller = PriceChartWindow(model)
        controller.title.hide()
        controller.market_updated.connect(
            lambda updated, target=tab_stack: self._update_price_instrument_for_stack(target, updated)
        )
        controller.chart.loadFinished.connect(lambda _ok: self.workspace_ready.emit())
        controller.refresh_requested.connect(
            lambda symbol, period, interval, target=tab_stack: self._execute_for_stack(
                target,
                f"GP {symbol} {period} {interval}",
            )
        )
        workspace = controller.takeCentralWidget()
        workspace._ajax_controller = controller
        self._replace_workspace(workspace)
        self.engine_label.setText("TRADINGVIEW LIGHTWEIGHT CHARTS 5.2.1")
        self._update_price_instrument(model)
        self.popout_button.setEnabled(True)
        QTimer.singleShot(6_000, self.workspace_ready.emit)

    def _mount_curve(self, model: object) -> None:
        tab_stack = self.stack
        controller = CurveWindow(model)
        controller.title.hide()
        controller.chart.loadFinished.connect(lambda _ok: self.workspace_ready.emit())
        controller.refresh_requested.connect(
            lambda currency, target=tab_stack: self._execute_for_stack(target, f"CURVE {currency}")
        )
        workspace = controller.takeCentralWidget()
        workspace._ajax_controller = controller
        self._replace_workspace(workspace)
        self.engine_label.setText("APACHE ECHARTS 6.1.0")
        self.instrument_bar.setText(
            f"{model.currency}   |   {model.name.upper()}   |   {len(model.points)} TENORS   |   "
            f"{model.provider} {model.quality}"
        )
        self.popout_button.setEnabled(True)
        QTimer.singleShot(6_000, self.workspace_ready.emit)

    def _mount_macro_map(self, model: object) -> None:
        if not isinstance(model, MacroMapLoad):
            raise TypeError("Macro map loader returned an invalid result")
        workspace = MacroMapWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        workspace.ready.connect(self.workspace_ready.emit)
        self._replace_workspace(workspace)
        self.engine_label.setText("THREE.JS 0.186 / OFFICIAL MACRO + MARKET DATA")
        self.instrument_bar.setText(
            f"MAP   |   {model.dataset.metric.value}   |   {model.region}   |   "
            f"{len(model.dataset.available)} COUNTRIES WITH DATA"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(6_000, self.workspace_ready.emit)

    def _mount_data_audit(self, model: object) -> None:
        workspace = DataAuditWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / VERIFIED FIELD PROVENANCE")
        self.instrument_bar.setText(
            f"{model.symbol}   |   {len(model.entries)} AUDITED FIELDS   |   "
            "SOURCE + QUALITY + TIMESTAMP + BASIS"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_data_quality(self, model: object) -> None:
        workspace = DataQualityWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / PROVIDER + CACHE DIAGNOSTICS")
        self.instrument_bar.setText(
            f"DQM   |   {len(model.providers)} PROVIDERS   |   "
            f"{model.available_count} AVAILABLE   |   {model.failed_count} FAILED   |   "
            f"CACHE {model.fresh_cache_count} FRESH / {model.stale_cache_count} STALE"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_watchlist(self, model: object) -> None:
        workspace = WatchlistWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / EDITABLE WATCHLIST")
        self.instrument_bar.setText(
            f"WATC   |   {model.name}   |   {len(model.quotes)} SECURITIES   |   MARKET DATA AUTO"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_portfolio(self, model: object) -> None:
        workspace = PortfolioWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / PORTFOLIO ANALYTICS")
        self.instrument_bar.setText(
            f"PORT   |   {model.name}   |   {len(model.lines)} POSITIONS   |   "
            f"VALUE {model.market_value:,.2f} {model.base_currency}   |   P&L {model.profit_loss:+,.2f}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_alerts(self, model: object) -> None:
        workspace = AlertsWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        triggered = sum(1 for item in model.evaluations if item.triggered)
        self.engine_label.setText("NATIVE QT / BACKGROUND ALERT ENGINE")
        self.instrument_bar.setText(
            f"ALRT   |   {len(model.evaluations)} RULES   |   {triggered} ACTIVE   |   "
            f"{model.unacknowledged} UNREAD   |   BACKGROUND SCHEDULER"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_event_calendar(self, model: object) -> None:
        workspace = EventCalendarWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / CORPORATE EVENT CALENDAR")
        self.instrument_bar.setText(
            f"EVT   |   {model.days} DAYS   |   {len(model.events)} EVENTS   |   "
            f"PAGE {model.page}   |   {model.total_symbols:,} SECURITIES   |   {model.universe}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_updates(self, model: object) -> None:
        workspace = UpdateWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        workspace.update_requested.connect(self._download_update)
        self._replace_workspace(workspace)
        self.engine_label.setText("SIGNED RELEASE MANAGER / ED25519 + SHA-256")
        self.instrument_bar.setText(
            f"UPD   |   RUNNING BETA {model.current_beta:03d}   |   "
            f"{len(model.cached_installers)} SIGNED INSTALLERS   |   {len(model.local_releases)} LEGACY BUILDS   |   "
            f"{model.status}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    @Slot(object)
    def _download_update(self, release: object) -> None:
        if not isinstance(release, SignedRelease):
            self._show_message("UPDATE REJECTED", "INVALID SIGNED RELEASE MODEL", error=True)
            return
        self._load_workspace(
            f"SIGNED BETA {release.beta:03d} DOWNLOAD",
            lambda: download_signed_release(release),
            self._launch_update_installer,
        )

    def _launch_update_installer(self, model: object) -> None:
        path = Path(model)
        if not path.is_file():
            self._show_message("UPDATE FAILED", "VERIFIED INSTALLER WAS NOT FOUND", error=True)
            return
        launched, _process_id = QProcess.startDetached(str(path), [], str(path.parent))
        if not launched:
            self._show_message("UPDATE FAILED", "WINDOWS COULD NOT START THE VERIFIED INSTALLER", error=True)
            return
        self._show_message(
            "SIGNED UPDATE READY",
            "THE VERIFIED INSTALLER HAS STARTED. WINDOWS MAY ASK TO CLOSE THIS TERMINAL.",
        )

    def _mount_diagnostics(self, model: object) -> None:
        workspace = DiagnosticsWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("LOCAL DIAGNOSTICS / SANITIZED SUPPORT")
        self.instrument_bar.setText(
            f"DIAG   |   {len(model.checks)} CHECKS   |   {model.failed_count} FAILED   |   "
            f"{model.warning_count} WARNINGS   |   NO USER DATA EXPORTED"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_doom(self) -> None:
        workspace = DoomWorkspace()
        workspace.status_changed.connect(
            lambda message, active=workspace: self._doom_status_changed(active, message)
        )
        self._replace_workspace(workspace)
        self.engine_label.setText("CHOCOLATE DOOM 3.1.1 / FREEDOOM 0.13.0")
        self.instrument_bar.setText(
            "DOOM   |   FREEDOOM: PHASE 1   |   FREE IWAD   |   LOCAL SAVEGAMES"
        )
        self.popout_button.setEnabled(False)

    def _doom_status_changed(self, workspace: DoomWorkspace, message: str) -> None:
        state = next(
            (
                candidate
                for candidate in self._terminal_tabs.values()
                if candidate.stack.currentWidget() is workspace
            ),
            None,
        )
        if state is None:
            return
        state.popout_enabled = workspace.can_pop_out
        state.popout_text = "DOCK" if "POPPED OUT" in message else "POP OUT"
        if state is self._active_terminal_tab:
            self.statusBar().showMessage(message, 8_000)
            self.popout_button.setEnabled(state.popout_enabled)
            self.popout_button.setText(state.popout_text)
        if "READY" in message or "ERROR" in message:
            self.workspace_ready.emit()

    def _show_workspace_manager(self) -> None:
        history = tuple(route.raw for route in self._history if route.raw and route.kind != "workspaces")
        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        workspace = WorkspaceManagerWorkspace(
            self.workspace_store,
            history[-1] if history else "HOME",
            self.current_symbol,
            history,
            geometry,
        )
        self._connect_tab_command(workspace.command_requested)
        workspace.workspace_selected.connect(self._restore_saved_workspace)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / PERSISTENT WORKSPACES")
        self.instrument_bar.setText("WSP   |   SAVE OR RESTORE TERMINAL CONTEXT")
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    @Slot(object)
    def _restore_saved_workspace(self, snapshot: object) -> None:
        if not isinstance(snapshot, WorkspaceSnapshot):
            return
        geometry = restore_workspace_geometry(snapshot)
        if not geometry.isEmpty():
            self.restoreGeometry(geometry)
        self.current_symbol = snapshot.current_symbol
        restored = [resolve_desktop_command(raw, self.current_symbol) for raw in snapshot.history]
        self._history = restored or [DesktopRoute("home", self.current_symbol, raw="HOME")]
        self._history_index = len(self._history) - 1
        self._update_navigation()
        self.execute_text(snapshot.active_command, record_history=False)

    def _mount_ovdv(self, model: object) -> None:
        tab_stack = self.stack
        workspace = VolatilitySurfaceWorkspace(model)
        workspace.title.hide()
        workspace.refresh_requested.connect(
            lambda symbol, target=tab_stack: self._execute_for_stack(target, f"OVDV {symbol}")
        )
        self._replace_workspace(workspace)
        self.engine_label.setText("PYVISTA 0.49 / VTK 9.7 / NATIVE INTERACTOR")
        self.instrument_bar.setText(
            f"{model.symbol}   {model.spot:,.4f} {model.currency}   |   R {model.rate * 100:.3f}%   |   "
            f"DIV {model.dividend_yield * 100:.3f}%   |   {len(model.expiries)} REAL EXPIRIES   |   "
            f"{model.source} {model.status}"
        )
        self.popout_button.setEnabled(True)
        QTimer.singleShot(800, self.workspace_ready.emit)

    def _mount_options(self, model: object) -> None:
        if not isinstance(model, OptionsDesktopLoad):
            raise TypeError("Options loader returned an invalid result")
        workspace = OptionsDesktopWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / LISTED OPTIONS")
        chain = model.chain
        expiry = chain.selected_expiry.isoformat() if chain.selected_expiry else "--"
        self.instrument_bar.setText(
            f"{chain.symbol}   SPOT {_number(chain.spot, 4)} {chain.currency or '--'}   |   "
            f"EXP {expiry}   |   {len(chain.calls)} CALLS   {len(chain.puts)} PUTS   |   "
            f"{chain.provider} {str(chain.quality).upper()}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_description(self, model: object) -> None:
        workspace = SecurityDescriptionWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        if self._pending_methodology_symbol == model.quote.symbol and hasattr(workspace, "rate_tabs"):
            workspace.rate_tabs.setCurrentIndex(1)
            self._pending_methodology_symbol = None
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT SECURITY DESCRIPTION")
        self._update_quote_instrument(model.quote)
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_financial_analysis(self, model: object) -> None:
        workspace = FinancialAnalysisWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT FINANCIAL ANALYSIS")
        self.instrument_bar.setText(
            f"{model.symbol}   |   {model.name.upper()}   |   {model.currency or '--'}   |   "
            f"{model.provider} {model.quality}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_financial_statement(self, model: object) -> None:
        workspace = FinancialStatementsWorkspace(model)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT FINANCIAL STATEMENTS")
        self.instrument_bar.setText(
            f"{model.symbol}   |   {model.name.upper()}   |   {model.currency or '--'}   |   "
            f"{model.provider} {model.quality}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_news(self, loaded: object) -> None:
        if not isinstance(loaded, NewsLoad):
            raise TypeError("News loader returned an invalid result")
        workspace = NewsDesktopWorkspace(loaded)
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText("NATIVE QT / VERIFIED NEWS SOURCES")
        topic = loaded.topic or "TOP STORIES"
        sources = len({item.source for item in loaded.items})
        self.instrument_bar.setText(
            f"NEWS   |   {topic.upper()}   |   {len(loaded.items)} HEADLINES   |   {sources} SOURCES"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_financial_export(self, model: object) -> None:
        workspace = FinancialExportWorkspace(model)
        self._replace_workspace(workspace)
        self.engine_label.setText("OPENPYXL / XLSX EXPORT COMPLETE")
        self.instrument_bar.setText(
            f"{model.symbol}   |   WORKBOOK SAVED   |   {model.path}"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_research(self, loaded: object) -> None:
        if not isinstance(loaded, ResearchLoad):
            raise TypeError("Research loader returned an invalid result")
        active = loaded.active_function
        if active == "RV":
            workspace = RelativeValuationWorkspace(loaded.model)
        elif active == "EE":
            workspace = EstimatesWorkspace(loaded.model)
        elif active == "ANR":
            workspace = AnalystWorkspace(loaded.model)
        elif active == "DVD":
            workspace = DividendsWorkspace(loaded.model)
        elif active == "EVT":
            workspace = EventsWorkspace(self.current_route.target, loaded.model)
        elif active in {"FILINGS", "10K", "10Q"}:
            workspace = FilingsWorkspace(loaded.model, active)
        elif active == "EQS":
            workspace = ScreenerWorkspace(loaded.model)
        else:
            raise TypeError(f"Unsupported research workspace: {active}")
        self._connect_tab_command(workspace.command_requested)
        self._replace_workspace(workspace)
        self.engine_label.setText(f"NATIVE QT / {active} STRUCTURED DATA")
        if loaded.quote is not None:
            self._update_quote_instrument(loaded.quote)
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _mount_classic(self, snapshot: object) -> None:
        if not isinstance(snapshot, ClassicSnapshot):
            raise TypeError("Classic renderer returned an invalid snapshot")
        page = QFrame()
        page.setObjectName("terminalPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        view = _InteractiveSvgWidget(snapshot.actions, snapshot.columns, snapshot.rows)
        view.load(QByteArray(snapshot.svg.encode("utf-8")))
        view.renderer().setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.action_triggered.connect(self._run_classic_action)
        layout.addWidget(view)
        page._ajax_svg = view
        self._replace_workspace(page)
        self.engine_label.setText("TEXTUAL / RICH EMBEDDED")
        self.popout_button.setEnabled(False)
        if snapshot.quote is not None and self._is_security_context(self.current_route):
            self._update_quote_instrument(snapshot.quote)
        QTimer.singleShot(0, self.workspace_ready.emit)

    @Slot(str)
    def _run_classic_action(self, action: str) -> None:
        if action == "app.focus_command":
            self.command.setFocus()
            return
        handlers = (
            ("app.run_command", lambda value: self.execute_text(str(value))),
            ("app.open_instrument", lambda value: self.execute_text(f"DES {value}")),
            ("app.open_methodology", self._open_methodology),
            ("app.open_url", open_external_url),
            ("app.open_export", open_local_path),
        )
        for prefix, callback in handlers:
            if not action.startswith(f"{prefix}(") or not action.endswith(")"):
                continue
            try:
                value = ast.literal_eval(action[len(prefix) + 1 : -1])
            except (SyntaxError, ValueError):
                return
            callback(value)
            return

    def _open_methodology(self, symbol: object) -> None:
        clean_symbol = str(symbol).strip().upper()
        if not _SYMBOL_RE.fullmatch(clean_symbol):
            return
        self._pending_methodology_symbol = clean_symbol
        self.execute_text(f"DES {clean_symbol}")

    def _replace_workspace(self, widget: QWidget) -> None:
        old = self.stack.currentWidget()
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)
        if old is not None:
            self.stack.removeWidget(old)
            self._dispose_workspace(old)

    def _dispose_workspace(self, widget: QWidget) -> None:
        controller = getattr(widget, "_ajax_controller", widget)
        stream = getattr(controller, "stream", None)
        if stream is not None:
            stream.stop()
        surface_view = getattr(controller, "surface_view", None)
        if surface_view is not None:
            surface_view.close()
        widget.close()
        widget.deleteLater()
        if controller is not widget:
            controller.close()
            controller.deleteLater()

    def _show_home(self) -> None:
        columns = max(120, self.stack.width() // 10)
        rows = max(34, self.stack.height() // 20)
        self._load_workspace(
            "MARKET MONITOR",
            lambda: render_classic_snapshot(
                "HOME",
                self.social_service,
                columns=columns,
                rows=rows,
            ),
            self._mount_classic,
        )

    def _show_security_function_menu(self, symbol: str) -> None:
        registered = self.registry.get(symbol)
        stored_name, stored_type = self._security_directory.get(symbol, ("", ""))
        name = stored_name or (registered.name if registered is not None else symbol)
        security_type = stored_type or (str(registered.asset_class) if registered is not None else "EQUITY")
        currency = registered.currency if registered is not None else ""
        menu = _SecurityFunctionMenu(symbol, name, security_type, currency)
        self._connect_tab_command(menu.command_requested)
        self._replace_workspace(menu)
        self.engine_label.setText(f"FUNCTION DIRECTORY / {security_type}")
        self.instrument_bar.setText(
            f"{symbol}   |   {name.upper()}   |   {security_type}   |   SELECT FUNCTION"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _show_security_settings(self, symbol: str) -> None:
        registered = self.registry.get(symbol)
        stored_name, stored_type = self._security_directory.get(symbol, ("", ""))
        name = stored_name or (registered.name if registered is not None else symbol)
        security_type = stored_type or (str(registered.asset_class) if registered is not None else "EQUITY")
        provider_names = [
            str(getattr(provider, "name", provider.__class__.__name__)).upper()
            for provider in self.market_service.market_providers
        ]
        live_feed = "FINNHUB ENABLED" if any("FINNHUB" in name for name in provider_names) else "DELAYED / OFFICIAL SOURCES"
        social_status = "SIGNED IN" if self.social_service.signed_in else (
            "CONFIGURED" if self.social_service.configured else "NOT CONFIGURED"
        )

        page = QFrame()
        page.setObjectName("securitySettings")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        heading = QLabel(f"SECURITY SETTINGS / {symbol}")
        heading.setStyleSheet(f"color:{AJAX_AMBER};font-size:18px;font-weight:bold")
        identity = QLabel(f"{name.upper()}  |  {security_type.upper()}")
        identity.setStyleSheet(f"color:{AJAX_TEXT};font-size:14px")
        layout.addWidget(heading)
        layout.addWidget(identity)

        status = QFrame()
        status.setObjectName("terminalPanel")
        grid = QGridLayout(status)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        settings_rows = (
            ("ACTIVE SECURITY", symbol),
            ("MARKET DATA", " | ".join(provider_names) or "NOT CONFIGURED"),
            ("LIVE EQUITY FEED", live_feed),
            ("SOCIAL SERVER", social_status),
            ("DATA POLICY", "OBSERVED | CACHED | EXPLICITLY MARKED ESTIMATES"),
        )
        for row, (label, value) in enumerate(settings_rows):
            field = QLabel(label)
            field.setStyleSheet(f"color:{AJAX_MUTED};font-weight:bold")
            content = QLabel(value)
            content.setWordWrap(True)
            content.setStyleSheet(f"color:{AJAX_TEXT}")
            grid.addWidget(field, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(content, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(status)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        actions.addWidget(_button("DES  SECURITY DESCRIPTION", lambda: self.execute_text(f"{symbol} DES")))
        actions.addWidget(_button("91  FUNCTION DIRECTORY", lambda: self.execute_text(symbol)))
        actions.addWidget(_button("SOCIAL CONNECTION", self._open_social_settings))
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

        self._replace_workspace(page)
        self.engine_label.setText("NATIVE QT / SECURITY SETTINGS")
        self.instrument_bar.setText(
            f"{symbol}   |   {name.upper()}   |   {security_type.upper()}   |   SETTINGS"
        )
        self.popout_button.setEnabled(False)
        QTimer.singleShot(0, self.workspace_ready.emit)

    def _open_social_settings(self) -> None:
        self.workspace_tabs.setCurrentIndex(1)
        self.social_workspace.activate()

    def _show_data_connections(self) -> None:
        dialog = _DataConnectionsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.market_service = MarketService()
        self.registry = self.market_service.registry
        self._show_message(
            "DATA CONNECTIONS SAVED",
            "ENCRYPTED FOR THE CURRENT WINDOWS USER / NEW PROVIDERS ARE ACTIVE",
        )

    def _function_bar_link(self, link: str) -> None:
        action, separator, raw_symbol = link.partition(":")
        symbol = raw_symbol.strip().upper()
        if not separator or not _SYMBOL_RE.fullmatch(symbol):
            return
        if action == "asset":
            self.execute_text(f"{symbol} DES")
        elif action == "actions":
            self.execute_text(symbol)
        elif action == "settings":
            self._show_security_settings(symbol)

    def _is_security_context(self, route: DesktopRoute, parsed=None) -> bool:
        if route.kind in _SECURITY_ROUTE_KINDS:
            return True
        if route.kind not in {"terminal", "news"}:
            return False
        parsed = parsed or parse_command(route.raw)
        if parsed.action not in SECURITY_FUNCTIONS or not parsed.target:
            return False
        if parsed.action != CommandAction.NEWS:
            return True
        target = route.target.upper()
        return (
            target == self.current_symbol
            or self.registry.get(target) is not None
            or target in self._security_directory
        )

    def _show_message(
        self,
        title: str,
        detail: str,
        *,
        error: bool = False,
        ready: bool = True,
    ) -> None:
        page = QFrame()
        page.setObjectName("emptyWorkspace")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 30, 36, 30)
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color:{AJAX_RED if error else AJAX_AMBER};font-size:18px;font-weight:bold"
        )
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        detail_label.setStyleSheet(f"color:{AJAX_MUTED};font-size:13px")
        layout.addWidget(heading)
        layout.addSpacing(12)
        layout.addWidget(detail_label)
        layout.addStretch(1)
        self._replace_workspace(page)
        if ready:
            QTimer.singleShot(0, self.workspace_ready.emit)

    def pop_out(self) -> None:
        route = self.current_route
        try:
            if route.kind == "price":
                launch_price_chart(route.target, route.period or "1Y", route.interval)
            elif route.kind == "curve":
                launch_curve_chart(route.target)
            elif route.kind == "ovdv":
                launch_volatility_surface(route.target)
            elif route.kind == "doom":
                workspace = self.stack.currentWidget()
                if not isinstance(workspace, DoomWorkspace) or not workspace.toggle_pop_out():
                    return
                return
            else:
                return
        except ChartRuntimeError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(f"POP OUT STARTED: {route.raw}")

    def _set_route_labels(self, route: DesktopRoute) -> None:
        parsed = parse_command(route.raw)
        command_name = parsed.action.value if parsed.action != CommandAction.UNKNOWN else route.raw
        labels = {
            "home": "MARKETS  |  PROFESSIONAL WORKSPACE",
            "security-required": f"SELECT SECURITY  |  {route.raw}",
            "select": f"{route.target}  |  SECURITY SELECTED",
            "price": f"GP  |  {route.target}  |  PRICE CHART",
            "curve": f"CURVE  |  {route.target}  |  YIELD CURVE",
            "macro-map": f"MAP  |  GLOBAL ECONOMIC MAP  |  {route.target}",
            "news": f"NEWS  |  {route.target or 'TOP STORIES'}",
            "watchlist": "WATC  |  EDITABLE WATCHLISTS",
            "portfolio": "PORT  |  PORTFOLIO MANAGER",
            "alerts": "ALRT  |  MARKET ALERTS",
            "workspaces": "WSP  |  PERSISTENT WORKSPACES",
            "updates": "UPD  |  BETA RELEASE MANAGER",
            "diagnostics": "DIAG  |  SYSTEM DIAGNOSTICS",
            "doom": "DOOM  |  FREEDOOM: PHASE 1  |  CLASSIC GAME",
            "ovdv": f"OVDV  |  {route.target}  |  IMPLIED VOLATILITY SURFACE",
            "option-monitor": f"OMON  |  {route.target}  |  OPTION MONITOR",
            "option-valuation": f"OVME  |  {route.target}  |  OPTION VALUATION",
            "description": f"DES  |  {route.target}  |  SECURITY DESCRIPTION",
            "data-audit": f"FLDS  |  {route.target}  |  FIELD PROVENANCE",
            "data-quality": f"DQM  |  DATA QUALITY MONITOR{f'  |  {route.target}' if route.target else ''}",
            "financial-analysis": f"FA  |  {route.target}  |  FINANCIAL ANALYSIS",
            "financial-income": f"IS  |  {route.target}  |  INCOME STATEMENT",
            "financial-balance": f"BS  |  {route.target}  |  BALANCE SHEET",
            "financial-cashflow": f"CF  |  {route.target}  |  CASH FLOW STATEMENT",
            "financial-export": f"XLS  |  {route.target}  |  FINANCIAL EXPORT",
            "relative-valuation": f"RV  |  {route.target}  |  RELATIVE VALUATION",
            "estimates": f"EE  |  {route.target}  |  CONSENSUS ESTIMATES",
            "analyst": f"ANR  |  {route.target}  |  ANALYST RECOMMENDATIONS",
            "dividends": f"DVD  |  {route.target}  |  DIVIDEND ANALYSIS",
            "events": f"EVT  |  {route.target}  |  CORPORATE EVENTS",
            "event-calendar": "EVT  |  CORPORATE CALENDAR",
            "filings": f"FILINGS  |  {route.target}  |  REGULATORY REPORTS",
            "filings-10k": f"10K  |  {route.target}  |  ANNUAL FILINGS",
            "filings-10q": f"10Q  |  {route.target}  |  QUARTERLY FILINGS",
            "screener": "EQS  |  EQUITY SCREENING",
            "social": "SOCIAL  |  CONTACTS  |  MESSAGING",
            "terminal": f"{command_name}  |  {route.target}",
        }
        title = labels.get(route.kind, route.raw)
        if self._is_security_context(route, parsed):
            security = route.target
            registered = self.registry.get(security)
            _name, stored_type = self._security_directory.get(security, ("", ""))
            security_type = stored_type or (str(registered.asset_class) if registered is not None else "EQUITY")
            safe_security = html.escape(security)
            safe_type = html.escape(security_type.title())
            safe_title = html.escape(title)
            self.function_bar.setText(
                f"<span style='background:#d99116;color:#050505'> {safe_security} {safe_type} </span>"
                f"&nbsp;&nbsp;<a style='color:#ffffff;text-decoration:none' href='asset:{safe_security}'>90) Asset</a>"
                f"&nbsp;&nbsp;&nbsp;<a style='color:#ffffff;text-decoration:none' href='actions:{safe_security}'>91) Actions</a>"
                f"&nbsp;&nbsp;&nbsp;<a style='color:#ffffff;text-decoration:none' href='settings:{safe_security}'>92) Settings</a>"
                f"&nbsp;&nbsp;&nbsp;{safe_title}"
            )
        else:
            self.function_bar.setText(html.escape(title))
        if self.current_symbol:
            self.instrument_bar.setText(
                f"{self.current_symbol}   |   ACTIVE SECURITY   |   FUNCTION {route.kind.upper()}"
            )
        else:
            self.instrument_bar.setText(
                "NO ACTIVE SECURITY   |   ENTER NAME OR TICKER   |   THEN FUNCTION <GO>"
            )

    @Slot(object)
    def _update_quote_instrument(self, quote: object) -> None:
        price = getattr(quote, "price", None)
        change = getattr(quote, "change", None)
        percent = getattr(quote, "change_percent", None)
        currency = getattr(quote, "currency", "")
        bid = getattr(quote, "bid", None)
        ask = getattr(quote, "ask", None)
        high = getattr(quote, "day_high", None)
        low = getattr(quote, "day_low", None)
        volume = getattr(quote, "volume", None)
        color = "#62e600" if change is not None and change >= 0 else "#ff315f"
        self.instrument_bar.setText(
            f"{getattr(quote, 'symbol', self.current_symbol)}   {_number(price, 4)} {currency}   |   "
            f"<span style='color:{color}'>{_signed(change, 4)} / {_signed(percent, 2)}%</span>   |   "
            f"BID {_number(bid, 4)}   ASK {_number(ask, 4)}   |   "
            f"H {_number(high, 4)}   L {_number(low, 4)}   |   VOL {_number(volume, 0)}"
        )

    @Slot(object)
    def _update_price_instrument(self, model: object) -> None:
        if not model.points:
            return
        last = model.points[-1]
        previous = model.points[-2].close if len(model.points) > 1 else last.close
        change = last.close - previous
        percent = change / previous * 100.0 if previous else 0.0
        color = "#62e600" if change >= 0 else "#ff315f"
        volume = f"{last.volume:,.0f}" if last.volume is not None else "--"
        self.instrument_bar.setText(
            f"{model.symbol}   {last.close:,.4f} {model.currency}   |   "
            f"<span style='color:{color}'>{change:+,.4f} / {percent:+.2f}%</span>   |   "
            f"O {last.open:,.4f}   H {last.high:,.4f}   L {last.low:,.4f}   |   "
            f"VOL {volume}"
        )

    def _update_price_instrument_for_stack(self, stack: QStackedWidget, model: object) -> None:
        state = self._terminal_tabs.get(stack)
        if state is None:
            return
        self._run_in_terminal_tab(state, lambda: self._update_price_instrument(model))

    def _update_clock(self) -> None:
        local = datetime.now().astimezone()
        utc = datetime.now(timezone.utc)
        offset_hours = (local.utcoffset().total_seconds() / 3_600) if local.utcoffset() else 0
        local_zone = "CEST" if offset_hours == 2 else "CET" if offset_hours == 1 else local.tzname() or "LOCAL"
        self.local_clock.setText(f"{local:%H:%M:%S} {local_zone}")
        self.utc_clock.setText(utc.strftime("UTC %H:%M:%S"))

    def _start_background_alerts(self) -> None:
        if not self._session_persistence_enabled or not self._authenticated:
            return
        if not self.alert_timer.isActive():
            self.alert_timer.start()
        if not self._alert_started_once:
            self._alert_started_once = True
            QTimer.singleShot(5_000, self._run_background_alerts)

    @Slot()
    def _run_background_alerts(self) -> None:
        if not self._authenticated or self._alert_worker is not None:
            return
        worker = _Loader(lambda: load_alerts(("BACKGROUND",)))
        self._alert_worker = worker
        self._alert_worker_session = self._alert_session_serial
        self.alert_status_label.setText("ALRT BG CHECK")
        self.alert_status_label.setStyleSheet(f"color:{AJAX_AMBER}")
        worker.loaded.connect(self._background_alerts_ready, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._background_alerts_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._background_alerts_finished, Qt.ConnectionType.QueuedConnection)
        worker.start()

    @Slot(object)
    def _background_alerts_ready(self, model: object) -> None:
        if (
            not self._authenticated
            or self._alert_worker_session != self._alert_session_serial
        ):
            return
        unread = int(getattr(model, "unacknowledged", 0))
        new_events = tuple(getattr(model, "new_events", ()))
        failures = int(getattr(model, "failures", 0))
        self.alert_status_label.setText(
            f"ALRT BG {len(new_events)} HIT" if new_events else
            f"ALRT BG {failures} ERR" if failures else
            f"ALRT BG {unread} NEW" if unread else "ALRT BG ARMED"
        )
        color = AJAX_RED if new_events or failures else "#62e600"
        self.alert_status_label.setStyleSheet(f"color:{color};font-weight:bold")
        if not new_events:
            return
        latest = new_events[0]
        message = latest.title
        if len(new_events) > 1:
            message = f"{latest.title}  |  +{len(new_events) - 1} MORE"
        self.statusBar().showMessage(f"ALERT: {message}", 15_000)
        QApplication.alert(self, 5_000)
        if self._tray_icon is not None:
            self._tray_icon.showMessage(
                "THRIVEBERG ALERT",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                12_000,
            )

    @Slot(str)
    def _background_alerts_failed(self, message: str) -> None:
        if (
            not self._authenticated
            or self._alert_worker_session != self._alert_session_serial
        ):
            return
        self.alert_status_label.setText("ALRT BG ERROR")
        self.alert_status_label.setStyleSheet(f"color:{AJAX_RED};font-weight:bold")
        self.statusBar().showMessage(f"BACKGROUND ALERT ENGINE: {message}", 8_000)

    @Slot()
    def _background_alerts_finished(self) -> None:
        worker = self.sender()
        if worker is self._alert_worker:
            self._alert_worker = None
            self._alert_worker_session = None
        worker.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        self._persist_session_state()
        if self._session_persistence_enabled:
            self.settings.setValue("session/clean_shutdown", True)
            self.settings.sync()
        self._load_serial += 1
        self._suggestion_serial += 1
        self._suggestion_timer.stop()
        self.alert_timer.stop()
        if self._alert_worker is not None and self._alert_worker.isRunning():
            self._alert_worker.requestInterruption()
            self._alert_worker.wait()
        for worker in tuple(self._suggestion_workers):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(2_000)
        for worker in tuple(self._workspace_loaders):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait()
        if self._auth_worker is not None and self._auth_worker.isRunning():
            self._auth_worker.requestInterruption()
            self._auth_worker.wait(2_000)
        if self._logout_worker is not None and self._logout_worker.isRunning():
            self._logout_worker.requestInterruption()
            self._logout_worker.wait(2_000)
        if self._startup_manager is not None:
            self._startup_manager.stop()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        social_worker = getattr(self.social_workspace, "_worker", None)
        if social_worker is not None and social_worker.isRunning():
            social_worker.requestInterruption()
            social_worker.wait(2_000)
        self.close_global_overview()
        for window in tuple(self._secondary_windows):
            window.close()
        for state in tuple(self._terminal_tabs.values()):
            state.load_serial += 1
            while state.stack.count():
                widget = state.stack.widget(0)
                state.stack.removeWidget(widget)
                self._dispose_workspace(widget)
        super().closeEvent(event)


class GlobalOverviewWindow(QMainWindow):
    def __init__(self, commands: tuple[str, str, str, str], target_screen) -> None:
        super().__init__()
        self.target_screen = target_screen
        self.commands = commands
        self.panels: list[AjaxDesktopWindow] = []
        self._expanded_panel: AjaxDesktopWindow | None = None
        self.setWindowTitle("THRIVEBERG Global Overview")
        self.setWindowIcon(thriveberg_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet(qt_stylesheet())

        host = QFrame()
        host.setObjectName("globalOverviewWall")
        host.setStyleSheet("#globalOverviewWall{background:#050606}")
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(3, 3, 3, 3)
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setRowStretch(0, 1)
        self.grid.setRowStretch(1, 1)
        self.setCentralWidget(host)

        for index, ((title, _default), command) in enumerate(
            zip(_GLOBAL_OVERVIEW_PANELS, commands, strict=True)
        ):
            panel = AjaxDesktopWindow(
                require_login=False,
                compact_mode=True,
                compact_title=f"{title}  |  {command}",
            )
            panel.window_chrome.compact_activated.connect(
                lambda active=panel: self._toggle_panel(active)
            )
            self.panels.append(panel)
            row, column = divmod(index, 2)
            self.grid.addWidget(panel, row, column)
            QTimer.singleShot(0, lambda active=panel, value=command: active.start(value))

    def show_on_screen(self) -> None:
        geometry = self.target_screen.availableGeometry()
        self.showNormal()
        self.setGeometry(geometry)
        self.show()
        self.raise_()

    def _toggle_panel(self, panel: AjaxDesktopWindow) -> None:
        if panel not in self.panels:
            return
        if self._expanded_panel is panel:
            self._restore_grid()
            return
        for candidate in self.panels:
            self.grid.removeWidget(candidate)
            candidate.hide()
        self.grid.addWidget(panel, 0, 0, 2, 2)
        panel.show()
        self._expanded_panel = panel

    def _restore_grid(self) -> None:
        for index, panel in enumerate(self.panels):
            self.grid.removeWidget(panel)
            row, column = divmod(index, 2)
            self.grid.addWidget(panel, row, column)
            panel.show()
        self._expanded_panel = None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        for panel in tuple(self.panels):
            panel.close()
        self.panels.clear()
        super().closeEvent(event)


def _button(label: str, callback: Callable[[], None]) -> QPushButton:
    button = QPushButton(label)
    button.setObjectName("menuButton")
    button.clicked.connect(callback)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _auth_link(label: str, callback: Callable[[], None]) -> QPushButton:
    button = QPushButton(label)
    button.setObjectName("authLink")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(callback)
    return button


def _number(value: float | None, decimals: int) -> str:
    if value is None:
        return "--"
    return f"{value:,.{decimals}f}"


def _signed(value: float | None, decimals: int) -> str:
    if value is None:
        return "--"
    return f"{value:+,.{decimals}f}"


def run_desktop_app(
    *,
    initial_command: str | None = None,
    screenshot: str | None = None,
    splash_screenshot: str | None = None,
) -> int:
    if importlib.util.find_spec("PySide6") is None:
        raise RuntimeError("PySide6 is required for the THRIVEBERG professional desktop shell")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("THRIVEBERG Terminal")
    app.setOrganizationName("THRIVEBERG")
    app.setWindowIcon(thriveberg_icon())
    font_path = Path(__file__).resolve().parent / "charts" / "assets" / "DejaVuSansMono.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    window = AjaxDesktopWindow(require_login=screenshot is None and splash_screenshot is None)
    if screenshot or splash_screenshot:
        window.showNormal()
        window.resize(1920, 1080)
    else:
        window.show()
    if splash_screenshot:
        output = Path(splash_screenshot).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        captured = False

        def capture_splash(_success: bool = True, _failures: object = ()) -> None:
            nonlocal captured
            if captured:
                return
            captured = True
            window.grab().save(str(output))
            app.quit()

        window._authenticated = True
        window._begin_boot_sequence(None)
        window.showNormal()
        window.resize(1920, 1080)
        if window._startup_manager is not None:
            window._startup_manager.startup_completed.connect(
                lambda success, failures: QTimer.singleShot(
                    80, lambda: capture_splash(success, failures)
                )
            )
        QTimer.singleShot(15_000, capture_splash)
        return app.exec()
    if screenshot:
        output = Path(screenshot).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        captured = False
        expected_kind = (
            resolve_desktop_command(initial_command).kind if initial_command else window.current_route.kind
        )

        def capture() -> None:
            nonlocal captured
            if captured:
                return
            captured = True
            current = window.stack.currentWidget()
            surface_view = getattr(current, "surface_view", None)
            if surface_view is not None:
                viewport = output.with_name(f"{output.stem}-vtk{output.suffix}")
                surface_view.render()
                surface_view.screenshot(str(viewport))
            frame = window.grab()
            if surface_view is not None:
                native_viewport = QPixmap(str(viewport))
                if not native_viewport.isNull():
                    position = surface_view.mapTo(window, QPoint(0, 0))
                    painter = QPainter(frame)
                    painter.drawPixmap(position, native_viewport)
                    painter.end()
            if isinstance(current, DoomWorkspace) and current.can_pop_out and not current._popped_out:
                screen = window.screen() or QApplication.primaryScreen()
                bridge = current._bridge
                if screen is not None and bridge is not None:
                    native_game = screen.grabWindow(bridge.hwnd)
                    if not native_game.isNull():
                        position = current._host.mapTo(window, QPoint(0, 0))
                        painter = QPainter(frame)
                        painter.drawPixmap(position, native_game)
                        painter.end()
            frame.save(str(output))
            window.close()
            app.quit()

        def workspace_ready() -> None:
            if window.current_route.kind == expected_kind:
                delay = 6_000 if expected_kind == "ovdv" else 2_500
                QTimer.singleShot(delay, capture)

        window.workspace_ready.connect(workspace_ready)
        QTimer.singleShot(20_000, capture)
    window.start(initial_command)
    return app.exec()
