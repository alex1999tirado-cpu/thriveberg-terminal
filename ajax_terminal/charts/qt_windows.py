from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.analytics.live_bars import TradeTick, merge_trade_ticks
from ajax_terminal.charts.models.curve import CurveChart
from ajax_terminal.charts.models.ohlcv import OHLCVChart
from ajax_terminal.charts.renderers.echarts.series import curve_option
from ajax_terminal.charts.streaming.finnhub import FinnhubTradeStream
from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_MUTED, qt_stylesheet
from ajax_terminal.charts.widgets.web_chart import EChartsWidget, LightweightChartWidget
from ajax_terminal.config import setting
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.utils.periods import HISTORY_PERIODS, chart_intervals_for_period


def _button(label: str, callback: Callable[[], None], *, checkable: bool = False) -> QPushButton:
    button = QPushButton(label)
    button.setCheckable(checkable)
    button.clicked.connect(callback)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


class PriceChartWindow(QMainWindow):
    refresh_requested = Signal(str, str, str)
    news_requested = Signal(str)
    market_updated = Signal(object)

    def __init__(self, model: OHLCVChart) -> None:
        super().__init__()
        self.model = model
        self.setWindowTitle(f"THRIVEBERG GP | {model.symbol}")
        self.setMinimumSize(900, 560)
        self.resize(1480, 860)
        self.setStyleSheet(qt_stylesheet())

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.title = QLabel()
        self.title.setObjectName("titleBar")
        layout.addWidget(self.title)
        layout.addWidget(self._primary_toolbar())
        layout.addWidget(self._study_toolbar())
        self.market_line = QLabel()
        self.market_line.setObjectName("marketStrip")
        layout.addWidget(self.market_line)
        self.chart = LightweightChartWidget()
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.chart, 1)
        self.setCentralWidget(root)
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(30_000)
        self.live_timer.timeout.connect(self._refresh)
        self.live_timer.start()
        self.stream_timer = QTimer(self)
        self.stream_timer.setInterval(500)
        self.stream_timer.timeout.connect(self._flush_stream_ticks)
        self.stream_timer.start()
        self.stream: FinnhubTradeStream | None = None
        self.pending_ticks: list[TradeTick] = []
        self.statusBar().showMessage("READY")
        self.set_model(model)
        QTimer.singleShot(0, self._configure_stream)

    def _primary_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("controlStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        period_label = QLabel("PERIOD")
        period_label.setObjectName("controlLabel")
        row.addWidget(period_label)
        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        for period in HISTORY_PERIODS:
            button = _button(period, lambda checked=False, value=period: self._select_period(value), checkable=True)
            button.setChecked(period == self.model.period)
            self.range_group.addButton(button)
            row.addWidget(button)
        row.addSpacing(8)
        self.interval = QComboBox()
        self.interval.setObjectName("amberField")
        self.interval.currentTextChanged.connect(self._select_interval)
        row.addWidget(QLabel("INTERVAL"))
        row.addWidget(self.interval)
        row.addSpacing(8)
        self.date_from = QLabel("--")
        self.date_from.setObjectName("amberField")
        self.date_to = QLabel("--")
        self.date_to.setObjectName("amberField")
        row.addWidget(QLabel("FROM"))
        row.addWidget(self.date_from)
        row.addWidget(QLabel("TO"))
        row.addWidget(self.date_to)
        row.addSpacing(8)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        chart_label = QLabel("CHART")
        chart_label.setObjectName("controlLabel")
        row.addWidget(chart_label)
        for label, chart_type in (("1) CANDLE", "candle"), ("2) OHLC", "ohlc"), ("3) LINE", "line")):
            button = _button(label, lambda checked=False, value=chart_type: self._select_type(value), checkable=True)
            button.setChecked(chart_type == "candle")
            self.type_group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)
        self.live_button = _button("AUTO 30S", self._toggle_live, checkable=True)
        self.live_button.setObjectName("amberField")
        self.live_button.setChecked(True)
        row.addWidget(self.live_button)
        row.addWidget(_button("FIT", self._fit))
        row.addWidget(_button("REFRESH", self._refresh))
        row.addWidget(_button("NEWS", lambda: self.news_requested.emit(self.model.symbol)))
        return frame

    def _study_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("controlStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        studies_label = QLabel("STUDIES")
        studies_label.setObjectName("controlLabel")
        row.addWidget(studies_label)
        self.study_buttons: dict[str, QPushButton] = {}
        for label, key, selected in (
            ("VOL", "volume", True),
            ("SMA 20", "sma20", True),
            ("EMA 50", "ema50", True),
            ("VWAP", "vwap", False),
        ):
            button = _button(label, lambda checked=False, value=key: self._toggle_study(value), checkable=True)
            button.setChecked(selected)
            self.study_buttons[key] = button
            row.addWidget(button)
        row.addWidget(_button("H-LINE", self._add_horizontal_line))
        row.addWidget(_button("CLEAR", self._clear_drawings))
        row.addStretch(1)
        note = QLabel("PAN: DRAG  |  ZOOM: WHEEL  |  CROSSHAIR: MOVE")
        note.setObjectName("muted")
        note.setStyleSheet(f"color:{AJAX_MUTED}")
        row.addWidget(note)
        return frame

    def set_model(self, model: OHLCVChart) -> None:
        symbol_changed = model.symbol != self.model.symbol
        self.model = model
        self.title.setText(f"GP  |  {model.symbol}  |  PRICE HISTORY")
        if model.points:
            self.date_from.setText(model.points[0].timestamp.strftime("%d %b %Y").upper())
            self.date_to.setText(model.points[-1].timestamp.strftime("%d %b %Y").upper())
        self.market_line.setText(
            f"{model.symbol}  {model.period} / {model.interval}  |  {len(model.points):,} BARS  |  "
            f"{model.provider}  {model.quality}  |  AUTO 30S"
        )
        self._populate_intervals(model.period, model.interval)
        self.chart.set_chart(model)
        self.statusBar().showMessage(f"{model.symbol} | STRIKE/PRICE CROSSHAIR ACTIVE | CHARTS BY TRADINGVIEW")
        self.market_updated.emit(model)
        if symbol_changed:
            self._configure_stream()

    def apply_live_model(self, model: OHLCVChart) -> None:
        changed_context = (
            model.symbol != self.model.symbol
            or model.period != self.model.period
            or model.interval != self.model.interval
        )
        self.model = model
        if changed_context:
            self.set_model(model)
            return
        self.chart.update_chart(model)
        self.market_line.setText(
            f"{model.symbol}  {model.period} / {model.interval}  |  {len(model.points):,} BARS  |  "
            f"{model.provider}  {model.quality}  |  AUTO 30S"
        )
        self.statusBar().showMessage("LIVE UPDATE RECEIVED | PROVIDER MAY BE DELAYED | CHARTS BY TRADINGVIEW")
        self.market_updated.emit(model)

    def set_loading(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def set_error(self, message: str) -> None:
        self.statusBar().setStyleSheet("color:#ff315f")
        self.statusBar().showMessage(message)

    def _populate_intervals(self, period: str, selected: str) -> None:
        self.interval.blockSignals(True)
        self.interval.clear()
        values = chart_intervals_for_period(period)
        self.interval.addItems(values)
        self.interval.setCurrentText(selected if selected in values else values[-1])
        self.interval.blockSignals(False)

    def _select_period(self, period: str) -> None:
        self._populate_intervals(period, chart_intervals_for_period(period)[-1])
        self.refresh_requested.emit(self.model.symbol, period, self.interval.currentText())

    def _select_interval(self, interval: str) -> None:
        if interval:
            period = next((button.text() for button in self.range_group.buttons() if button.isChecked()), self.model.period)
            self.refresh_requested.emit(self.model.symbol, period, interval)

    def _select_type(self, chart_type: str) -> None:
        self.chart.chart_type = chart_type
        self.chart.redraw()

    def _toggle_study(self, key: str) -> None:
        if self.study_buttons[key].isChecked():
            self.chart.studies.add(key)
        else:
            self.chart.studies.discard(key)
        self.chart.redraw()

    def _add_horizontal_line(self) -> None:
        if not self.model.points:
            return
        self.chart.horizontal_lines.append(self.model.points[-1].close)
        self.chart.redraw()

    def _clear_drawings(self) -> None:
        self.chart.horizontal_lines.clear()
        self.chart.trend_lines.clear()
        self.chart.redraw()

    def _fit(self) -> None:
        self.chart.fit()

    def _refresh(self) -> None:
        period = next((button.text() for button in self.range_group.buttons() if button.isChecked()), self.model.period)
        self.refresh_requested.emit(self.model.symbol, period, self.interval.currentText())

    def _toggle_live(self) -> None:
        if self.live_button.isChecked():
            self.live_timer.start()
            self.stream_timer.start()
            if self.stream is not None:
                self.stream.start()
            self.statusBar().showMessage("AUTO UPDATE ON | STREAM 2HZ WHEN ENTITLED | AUTO 30S FALLBACK")
        else:
            self.live_timer.stop()
            self.stream_timer.stop()
            if self.stream is not None:
                self.stream.stop()
            self.statusBar().showMessage("AUTO UPDATE OFF")

    def _configure_stream(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.deleteLater()
            self.stream = None
        self.pending_ticks.clear()
        instrument = INSTRUMENT_REGISTRY.resolve(self.model.symbol)
        api_key = setting("FINNHUB_KEY")
        if instrument.asset_class != AssetClass.EQUITY or not api_key:
            reason = "NON-EQUITY / AUTO 30S" if instrument.asset_class != AssetClass.EQUITY else "ADD FINNHUB_KEY FOR STREAM 2HZ"
            self.statusBar().showMessage(reason)
            return
        self.stream = FinnhubTradeStream(api_key, instrument.symbol, self)
        self.stream.trade_received.connect(self._queue_stream_tick)
        self.stream.status_changed.connect(self._stream_status)
        if self.live_button.isChecked():
            self.stream.start()

    def _queue_stream_tick(self, tick: TradeTick) -> None:
        self.pending_ticks.append(tick)

    def _flush_stream_ticks(self) -> None:
        if not self.pending_ticks or not self.live_button.isChecked():
            return
        ticks, self.pending_ticks = self.pending_ticks, []
        model = merge_trade_ticks(self.model, ticks)
        if model.points == self.model.points:
            return
        self.model = model
        self.chart.update_chart(model)
        self.market_line.setText(
            f"{model.symbol}  {model.period} / {model.interval}  |  {len(model.points):,} BARS  |  "
            "FINNHUB WEBSOCKET  STREAM 2HZ  |  YAHOO HISTORY"
        )
        self.statusBar().showMessage("STREAM TICK RECEIVED | 500MS UI THROTTLE | CHARTS BY TRADINGVIEW")
        self.market_updated.emit(model)

    def _stream_status(self, message: str) -> None:
        self.statusBar().showMessage(f"{message} | AUTO 30S FALLBACK AVAILABLE")


class CurveWindow(QMainWindow):
    refresh_requested = Signal(str)

    def __init__(self, model: CurveChart) -> None:
        super().__init__()
        self.model = model
        self.setWindowTitle(f"THRIVEBERG CURVE | {model.currency}")
        self.setMinimumSize(820, 520)
        self.resize(1180, 720)
        self.setStyleSheet(qt_stylesheet())
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(2)
        self.title = QLabel(f"CURVE  |  {model.currency}  |  {model.name.upper()}")
        self.title.setObjectName("titleBar")
        layout.addWidget(self.title)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("TENOR / YIELD"))
        controls.addStretch(1)
        controls.addWidget(_button("REFRESH", lambda: self.refresh_requested.emit(self.model.currency)))
        layout.addLayout(controls)
        self.market_line = QLabel()
        self.market_line.setStyleSheet("color:#d7d7d7;padding:2px 5px")
        layout.addWidget(self.market_line)
        self.chart = EChartsWidget()
        layout.addWidget(self.chart, 1)
        self.setCentralWidget(root)
        self.set_model(model)

    def set_model(self, model: CurveChart) -> None:
        self.model = model
        self.market_line.setText(
            f"{model.provider}  |  {model.quality}  |  {model.method}  |  {len(model.points)} TENORS"
        )
        self.chart.set_option(curve_option(model))
        slopes = _curve_slopes(model)
        self.statusBar().showMessage("  |  ".join(slopes) if slopes else "REFERENCE CURVE")

    def set_error(self, message: str) -> None:
        self.statusBar().setStyleSheet("color:#ff315f")
        self.statusBar().showMessage(message)


def _curve_slopes(curve: CurveChart) -> list[str]:
    values = {point.tenor: point.yield_pct for point in curve.points}
    result: list[str] = []
    for label, short, long in (("2s10s", "2Y", "10Y"), ("5s30s", "5Y", "30Y"), ("3m10y", "3M", "10Y")):
        if short in values and long in values:
            result.append(f"{label.upper()} {(values[long] - values[short]) * 100:+.1f}BP")
    return result
