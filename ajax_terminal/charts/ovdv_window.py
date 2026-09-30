from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.analytics.volatility_surface import (
    build_surface_grid,
    skew_for_tenor,
    term_structure,
    volatility_snapshot,
)
from ajax_terminal.charts.models.volatility import VolPoint, VolSurface
from ajax_terminal.charts.renderers.echarts.series import skew_option, term_structure_option
from ajax_terminal.charts.renderers.pyvista.volatility_surface import VolatilitySurfaceView
from ajax_terminal.charts.theme import AJAX_MUTED, AJAX_RED, qt_stylesheet
from ajax_terminal.charts.widgets.web_chart import EChartsWidget


class VolatilitySurfaceWorkspace(QWidget):
    refresh_requested = Signal(str)

    def __init__(self, surface: VolSurface) -> None:
        super().__init__()
        if not surface.points:
            raise ValueError(f"No supported real option observations are available for {surface.symbol}")
        self.surface = surface
        self.selected_tenor = surface.tenors[0]
        self.term_chart: EChartsWidget | None = None
        self.skew_chart: EChartsWidget | None = None
        self.term_full_chart: EChartsWidget | None = None
        self.skew_full_chart: EChartsWidget | None = None
        self._vtk_first_frame_ready = False
        self.setMinimumSize(1180, 680)
        self.setStyleSheet(qt_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.title = QLabel()
        self.title.setObjectName("titleBar")
        layout.addWidget(self.title)
        layout.addWidget(self._view_strip())
        layout.addWidget(self._toolbar())
        self.market_line = QLabel()
        self.market_line.setObjectName("marketStrip")
        layout.addWidget(self.market_line)
        self.metrics_line = QLabel()
        self.metrics_line.setObjectName("metricsStrip")
        layout.addWidget(self.metrics_line)

        self.surface_view = VolatilitySurfaceView()
        self.surface_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.surface_view.point_tracked.connect(self._tracked)

        self.content_stack = QStackedWidget()
        self.dashboard_page = self._build_dashboard_page()
        self.table = self._build_table_page()
        self.term_page, self.term_page_layout = _empty_chart_page()
        self.skew_page, self.skew_page_layout = _empty_chart_page()
        self.content_stack.addWidget(self.dashboard_page)
        self.content_stack.addWidget(self.table)
        self.content_stack.addWidget(self.term_page)
        self.content_stack.addWidget(self.skew_page)
        layout.addWidget(self.content_stack, 1)
        self.status_line = QLabel("DRAG ROTATE | SHIFT/MIDDLE DRAG PAN | WHEEL ZOOM")
        self.status_line.setObjectName("footerBar")
        layout.addWidget(self.status_line)
        self._load_surface(surface)
        QTimer.singleShot(0, self._initialize_analytics_panel)

    def _view_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(1, 0, 1, 0)
        row.setSpacing(1)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        for label, page in (
            ("1) VOL TABLE", 1),
            ("2) 3D SURFACE", 0),
            ("3) TERM", 2),
            ("4) SKEW", 3),
        ):
            button = _button(label, lambda checked=False, value=page: self.content_stack.setCurrentIndex(value), checkable=True)
            button.setObjectName("functionTab")
            button.setChecked(page == 0)
            self.view_group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)
        return frame

    def _toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("controlStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        axis = QLabel("MONEYNESS")
        axis.setObjectName("amberField")
        row.addWidget(axis)
        listed = QLabel("* LISTED EXP")
        listed.setObjectName("controlLabel")
        row.addWidget(listed)
        row.addWidget(QLabel("o TENORS   o LOCAL VOL   o STRIKES"))

        self.legend_button = _button("LEGEND", self._toggle_legend, checkable=True)
        self.track_button = _button("TRACK", self._toggle_track, checkable=True)
        row.addSpacing(8)
        view = QToolButton()
        view.setText("VIEW")
        view.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(view)
        for label, key in (("DEFAULT", "default"), ("TOP", "top"), ("FRONT", "front"), ("SIDE", "side")):
            action = QAction(label, menu)
            action.triggered.connect(lambda checked=False, value=key: self.surface_view.set_view(value))
            menu.addAction(action)
        view.setMenu(menu)
        row.addWidget(view)
        row.addWidget(_button("RESET VIEW", lambda: self.surface_view.set_view("default")))
        row.addWidget(_button("COPY IMAGE", self._copy_image))
        row.addWidget(self.track_button)
        row.addWidget(self.legend_button)
        row.addSpacing(10)
        interp_label = QLabel("INTERP")
        interp_label.setObjectName("controlLabel")
        row.addWidget(interp_label)
        self.interpolation = QComboBox()
        self.interpolation.setObjectName("amberField")
        self.interpolation.addItems(["linear", "nearest", "cubic"])
        self.interpolation.currentTextChanged.connect(self._change_interpolation)
        row.addWidget(self.interpolation)
        term_label = QLabel("TERM")
        term_label.setObjectName("controlLabel")
        row.addWidget(term_label)
        self.tenor_combo = QComboBox()
        self.tenor_combo.setObjectName("amberField")
        self.tenor_combo.currentIndexChanged.connect(self._select_tenor)
        row.addWidget(self.tenor_combo)
        row.addStretch(1)
        interaction = QLabel("DRAG ROTATE  |  WHEEL ZOOM")
        interaction.setObjectName("muted")
        row.addWidget(interaction)
        row.addWidget(_button("REFRESH", lambda: self.refresh_requested.emit(self.surface.symbol)))
        return frame

    def _build_dashboard_page(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.surface_panel, self.surface_badge = _chart_panel(
            "3D VOLATILITY SURFACE", f"{self.surface.symbol} / LISTED", self.surface_view
        )
        frame = QFrame()
        frame.setMinimumWidth(330)
        frame.setMaximumWidth(600)
        self.analytics_layout = QVBoxLayout(frame)
        self.analytics_layout.setContentsMargins(0, 0, 0, 0)
        self.analytics_layout.setSpacing(3)
        self.analytics_placeholder = QLabel("INITIALIZING VTK VIEWPORT...")
        self.analytics_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.analytics_placeholder.setStyleSheet(f"color:{AJAX_MUTED}")
        self.analytics_layout.addWidget(self.analytics_placeholder)
        splitter.addWidget(self.surface_panel)
        splitter.addWidget(frame)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1150, 500])
        return splitter

    def _build_table_page(self) -> QTableWidget:
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        return table

    def _initialize_analytics_panel(self) -> None:
        if self.term_chart is not None:
            return
        validity_check = getattr(self.surface_view, "isValid", None)
        if validity_check is not None and not validity_check():
            self.surface_view.update()
            QTimer.singleShot(100, self._initialize_analytics_panel)
            return
        if not self._vtk_first_frame_ready:
            self._vtk_first_frame_ready = True
            QTimer.singleShot(1_200, self._initialize_analytics_panel)
            return
        self.analytics_placeholder.hide()
        self.analytics_placeholder.deleteLater()
        self.term_chart = EChartsWidget()
        self.skew_chart = EChartsWidget()
        term_panel, self.term_badge = _chart_panel("VOLATILITY VS. TERM", "MONEYNESS 100.0%", self.term_chart)
        skew_panel, self.skew_badge = _chart_panel(
            "MONEYNESS", f"TERM {_tenor_label(self.selected_tenor)}", self.skew_chart
        )
        self.analytics_layout.addWidget(term_panel, 1)
        self.analytics_layout.addWidget(skew_panel, 1)

        self.term_full_chart = EChartsWidget()
        full_term_panel, self.term_full_badge = _chart_panel(
            "VOLATILITY VS. TERM", "MONEYNESS 100.0%", self.term_full_chart
        )
        self.term_page_layout.addWidget(full_term_panel)
        self.skew_full_chart = EChartsWidget()
        full_skew_panel, self.skew_full_badge = _chart_panel(
            "MONEYNESS", f"TERM {_tenor_label(self.selected_tenor)}", self.skew_full_chart
        )
        self.skew_page_layout.addWidget(full_skew_panel)

        self.term_chart.set_option(term_structure_option(self.surface))
        self.term_full_chart.set_option(term_structure_option(self.surface))
        self._update_tenor_panels()
        self._populate_table()

    def _load_surface(self, surface: VolSurface) -> None:
        self.surface = surface
        self.title.setText(f"OVDV  |  {surface.symbol}  |  IMPLIED VOLATILITY SURFACE")
        rate_text = f"{surface.rate * 100:.3f}%" if surface.rate_available else "--"
        self.market_line.setText(
            f"{surface.symbol}  |  SPOT {surface.spot:.4f} {surface.currency}  |  "
            f"R {rate_text}  |  DIV {surface.dividend_yield * 100:.3f}%  |  "
            f"{len(surface.expiries)} REAL EXPIRIES  |  {surface.source} {surface.status}"
        )
        self.surface_badge.setText(f"{surface.symbol} / LISTED")
        self.tenor_combo.blockSignals(True)
        self.tenor_combo.clear()
        for tenor in surface.tenors:
            self.tenor_combo.addItem(_tenor_label(tenor), tenor)
        self.tenor_combo.blockSignals(False)
        self.selected_tenor = surface.tenors[0]
        self.surface_view.set_surface(surface, interpolation=self.interpolation.currentText())
        if self.term_chart is not None:
            self.term_chart.set_option(term_structure_option(surface))
        if self.term_full_chart is not None:
            self.term_full_chart.set_option(term_structure_option(surface))
        self._update_tenor_panels()
        self._populate_table()

    def set_surface(self, surface: VolSurface) -> None:
        self._load_surface(surface)

    def set_error(self, message: str) -> None:
        self.status_line.setStyleSheet(f"color:{AJAX_RED}")
        self.status_line.setText(message)

    def _select_tenor(self, index: int) -> None:
        value = self.tenor_combo.itemData(index)
        if value is not None:
            self.selected_tenor = int(value)
            self._update_tenor_panels()

    def _update_tenor_panels(self) -> None:
        if self.skew_chart is not None:
            self.skew_chart.set_option(skew_option(self.surface, self.selected_tenor))
            self.skew_badge.setText(f"TERM {_tenor_label(self.selected_tenor)}")
        if self.skew_full_chart is not None:
            self.skew_full_chart.set_option(skew_option(self.surface, self.selected_tenor))
            self.skew_full_badge.setText(f"TERM {_tenor_label(self.selected_tenor)}")
        snapshot = volatility_snapshot(self.surface, self.selected_tenor)
        terms = dict(term_structure(self.surface))
        self.metrics_line.setText(
            f"SPOT {self.surface.spot:.4f}   |   ATM IV {_pct(snapshot.atm_iv)}   |   "
            f"1M {_nearest_term(terms, 30)}   3M {_nearest_term(terms, 91)}   "
            f"6M {_nearest_term(terms, 182)}   |   25D PUT {_pct(snapshot.put_25d_iv)}   "
            f"25D CALL {_pct(snapshot.call_25d_iv)}   |   RR {_points(snapshot.risk_reversal)}   "
            f"FLY {_points(snapshot.butterfly)}"
        )

    def _populate_table(self) -> None:
        if self.table is None:
            return
        grid = build_surface_grid(self.surface, method=self.interpolation.currentText(), moneyness_steps=21)
        x_values = grid.moneyness[0]
        tenors = grid.tenor_days[:, 0]
        self.table.clear()
        self.table.setColumnCount(len(tenors) + 1)
        self.table.setHorizontalHeaderLabels(["K/S", *[_tenor_label(int(value)) for value in tenors]])
        self.table.setRowCount(len(x_values))
        for row, moneyness in enumerate(x_values):
            self.table.setItem(row, 0, QTableWidgetItem(f"{moneyness * 100:.1f}%"))
            for column, value in enumerate(grid.iv[:, row], start=1):
                text = "--" if not np.isfinite(value) else f"{value:.2f}"
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def _toggle_legend(self) -> None:
        self.surface_view.set_legend_visible(self.legend_button.isChecked())

    def _toggle_track(self) -> None:
        active = self.track_button.isChecked()
        self.surface_view.set_tracking(active)
        self.status_line.setText("CLICK A SURFACE POINT" if active else "TRACK OFF | DRAG ROTATE | WHEEL ZOOM")

    def _tracked(self, point: VolPoint) -> None:
        delta = "N/A" if point.delta is None else f"{point.delta:+.4f}"
        self.status_line.setText(
            f"{self.surface.symbol} | {point.expiry} | K {point.strike:.4f} | "
            f"K/S {point.moneyness * 100:.2f}% | DELTA {delta} | "
            f"IV {point.iv * 100:.3f}% | {point.option_type.upper()}"
        )

    def _change_interpolation(self, method: str) -> None:
        try:
            self.surface_view.set_surface(self.surface, interpolation=method)
            self._populate_table()
        except Exception as exc:
            self.set_error(str(exc))

    def _interaction(self, message: str) -> None:
        self.track_button.setChecked(False)
        self.surface_view.set_tracking(False)
        self.surface_view.enable_trackball_style()
        self.status_line.setText(message)

    def _copy_image(self) -> None:
        pixels = self.surface_view.screenshot(return_img=True)
        if pixels is None:
            self.set_error("Unable to capture the VTK canvas")
            return
        image = np.ascontiguousarray(pixels[:, :, :3], dtype=np.uint8)
        height, width, _ = image.shape
        qimage = QImage(image.data, width, height, image.strides[0], QImage.Format.Format_RGB888).copy()
        QApplication.clipboard().setImage(qimage)
        self.status_line.setText("OVDV IMAGE COPIED TO CLIPBOARD")


class VolatilitySurfaceWindow(QMainWindow):
    """Optional top-level host for the reusable OVDV workspace."""

    refresh_requested = Signal(str)

    def __init__(self, surface: VolSurface) -> None:
        super().__init__()
        self.setWindowTitle(f"THRIVEBERG OVDV | {surface.symbol}")
        self.setMinimumSize(1180, 680)
        self.resize(1740, 980)
        self.workspace = VolatilitySurfaceWorkspace(surface)
        self.workspace.refresh_requested.connect(self.refresh_requested.emit)
        self.setCentralWidget(self.workspace)

    @property
    def surface_view(self) -> VolatilitySurfaceView:
        return self.workspace.surface_view

    def set_surface(self, surface: VolSurface) -> None:
        self.workspace.set_surface(surface)

    def set_error(self, message: str) -> None:
        self.workspace.set_error(message)


def _chart_panel(title: str, badge: str, content: QWidget) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("chartPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    header = QFrame()
    header.setObjectName("controlStrip")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 3, 0)
    header_layout.setSpacing(0)
    heading = QLabel(title)
    heading.setObjectName("panelHeader")
    badge_label = QLabel(badge)
    badge_label.setObjectName("panelBadge")
    header_layout.addWidget(heading, 1)
    header_layout.addWidget(badge_label)
    layout.addWidget(header)
    layout.addWidget(content, 1)
    return frame, badge_label


def _empty_chart_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return page, layout


def _button(label: str, callback, *, checkable: bool = False) -> QPushButton:
    button = QPushButton(label)
    button.setCheckable(checkable)
    button.clicked.connect(callback)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _tenor_label(days: int) -> str:
    if days < 28:
        return f"{days}D"
    if days < 365:
        return f"{max(1, round(days / 30.4375))}M"
    years = days / 365.25
    return f"{years:.0f}Y" if abs(years - round(years)) < 0.16 else f"{years:.1f}Y"


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.2f}%"


def _points(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:+.2f} VOL"


def _slope(value: float | None) -> str:
    return "--" if value is None else f"{value:+.3f}"


def _nearest_term(values: dict[int, float], target: int) -> str:
    if not values:
        return "--"
    tenor = min(values, key=lambda item: abs(item - target))
    if abs(tenor - target) > max(21, target * 0.5):
        return "--"
    return f"{values[tenor]:.2f}%"
