from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from ajax_terminal.charts.models.ohlcv import OHLCVChart
from ajax_terminal.analytics.chart_indicators import price_indicators
from ajax_terminal.charts.renderers.echarts.renderer import EChartsRenderer
from ajax_terminal.charts.renderers.lightweight.renderer import LightweightChartsRenderer
from ajax_terminal.charts.renderers.three_globe.renderer import ThreeGlobeRenderer


LOGGER = logging.getLogger(__name__)


class _TerminalWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id) -> None:  # noqa: N802
        log = LOGGER.error if "error" in str(level).lower() else LOGGER.debug
        log("web chart javascript %s:%s %s", source_id, line_number, message)


class _TerminalWebView(QWebEngineView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPage(_TerminalWebPage(self))
        handle, filename = tempfile.mkstemp(prefix="ajax-chart-", suffix=".html")
        os.close(handle)
        self._document_path = Path(filename)
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.page().setBackgroundColor("#050708")

    def load_document(self, document: str) -> None:
        self._document_path.write_text(document, encoding="utf-8")
        self.setUrl(QUrl.fromLocalFile(str(self._document_path)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        super().closeEvent(event)
        try:
            self._document_path.unlink(missing_ok=True)
        except OSError:
            pass


class LightweightChartWidget(_TerminalWebView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.renderer = LightweightChartsRenderer()
        self.model: OHLCVChart | None = None
        self.chart_type = "candle"
        self.studies: set[str] = {"volume", "sma20", "ema50"}
        self.horizontal_lines: list[float] = []
        self.trend_lines: list[tuple[int, float, int, float]] = []

    def set_chart(self, model: OHLCVChart) -> None:
        self.model = model
        self.redraw()

    def redraw(self) -> None:
        if self.model is None:
            return
        document = self.renderer.render(
            self.model,
            chart_type=self.chart_type,
            studies=self.studies,
            horizontal_lines=self.horizontal_lines,
            trend_lines=self.trend_lines,
        )
        self.load_document(document)

    def fit(self) -> None:
        self.page().runJavaScript("window.ajaxFit && window.ajaxFit()")

    def update_chart(self, model: OHLCVChart) -> None:
        if self.model is None:
            self.set_chart(model)
            return
        same_series = (
            model.symbol == self.model.symbol
            and model.period == self.model.period
            and model.interval == self.model.interval
            and bool(self.model.points)
        )
        model.indicators = price_indicators(model)
        gained_indicator = any(
            key in self.studies and not self.model.indicators.get(key) and model.indicators.get(key)
            for key in ("sma20", "ema50", "vwap")
        )
        if not same_series or gained_indicator:
            self.set_chart(model)
            return
        last_epoch = self.model.points[-1].epoch
        changed = [point for point in model.points if point.epoch >= last_epoch]
        if not changed:
            self.model = model
            return
        indicator_maps = {key: dict(values) for key, values in model.indicators.items()}
        payloads = []
        for point in changed:
            indicators = {
                key: {"time": point.epoch, "value": values[point.epoch]}
                for key, values in indicator_maps.items()
                if point.epoch in values
            }
            payloads.append(
                {
                    "bar": {
                        "time": point.epoch,
                        "open": point.open,
                        "high": point.high,
                        "low": point.low,
                        "close": point.close,
                    },
                    "volume": {
                        "time": point.epoch,
                        "value": point.volume or 0.0,
                        "color": "#18753b" if point.close >= point.open else "#9b2439",
                    },
                    "indicators": indicators,
                }
            )
        self.model = model
        self.page().runJavaScript(
            f"window.ajaxUpdateBars && window.ajaxUpdateBars({json.dumps(payloads, separators=(',', ':'))})"
        )


class EChartsWidget(_TerminalWebView):
    country_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.renderer = EChartsRenderer()
        self.option: dict[str, object] | None = None
        self._map_geojson: dict[str, object] | None = None
        self._bridge = _EChartsBridge(self)
        self._bridge.country_selected.connect(self.country_clicked)
        self._channel = QWebChannel(self.page())
        self._channel.registerObject("terminalBridge", self._bridge)
        self.page().setWebChannel(self._channel)

    def set_option(self, option: dict[str, object]) -> None:
        self.option = option
        document = self.renderer.render(option)
        self.load_document(document)

    def set_map_option(self, option: dict[str, object], geojson: dict[str, object]) -> None:
        self.option = option
        self._map_geojson = geojson
        document = self.renderer.render(option, map_geojson=geojson, country_events=True)
        self.load_document(document)

    def update_option(self, option: dict[str, object]) -> None:
        self.option = option
        payload = json.dumps(option, separators=(",", ":"))
        self.page().runJavaScript(f"window.ajaxSetOption && window.ajaxSetOption({payload})")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        super().resizeEvent(event)
        self.page().runJavaScript("window.ajaxResize && window.ajaxResize()")

    def select_country(self, name: str) -> None:
        self.page().runJavaScript(f"window.ajaxSelectCountry && window.ajaxSelectCountry({json.dumps(name)})")


class ThreeGlobeWidget(_TerminalWebView):
    country_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.renderer = ThreeGlobeRenderer()
        self.payload: dict[str, object] | None = None
        self._bridge = _EChartsBridge(self)
        self._bridge.country_selected.connect(self.country_clicked)
        self._channel = QWebChannel(self.page())
        self._channel.registerObject("terminalBridge", self._bridge)
        self.page().setWebChannel(self._channel)

    def set_globe(self, payload: dict[str, object], geojson: dict[str, object]) -> None:
        self.payload = payload
        self.load_document(self.renderer.render(payload, geojson))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt callback
        super().resizeEvent(event)
        self.page().runJavaScript("window.ajaxResize && window.ajaxResize()")

    def select_country(self, name: str) -> None:
        payload = json.dumps(name)
        self.page().runJavaScript(
            "(function selectWhenReady(attempts){"
            f"if(window.ajaxSelectCountry){{window.ajaxSelectCountry({payload});return;}}"
            "if(attempts>0){setTimeout(()=>selectWhenReady(attempts-1),50);}})(80)"
        )


class _EChartsBridge(QObject):
    country_selected = Signal(str)

    @Slot(str)
    def selectCountry(self, name: str) -> None:  # noqa: N802 - JavaScript API
        self.country_selected.emit(name)
