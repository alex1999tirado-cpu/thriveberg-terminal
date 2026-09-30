from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from ajax_terminal.analytics.chart_indicators import price_indicators
from ajax_terminal.charts.models.curve import CurveChart, normalize_curve
from ajax_terminal.charts.models.ohlcv import OHLCVChart, normalize_ohlcv
from ajax_terminal.charts.models.volatility import VolSurface, normalize_vol_surface
from ajax_terminal.charts.ovdv_window import VolatilitySurfaceWindow
from ajax_terminal.charts.qt_windows import CurveWindow, PriceChartWindow
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.options_service import OptionsService
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period


class _LoadThread(QThread):
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


def run_chart_app(
    kind: str,
    target: str,
    period: str = "1Y",
    interval: str | None = None,
    *,
    screenshot: str | None = None,
) -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("THRIVEBERG Terminal Charts")
    app.setOrganizationName("THRIVEBERG")
    font_path = Path(__file__).resolve().parent / "assets" / "DejaVuSansMono.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    try:
        if kind == "price":
            model = _load_price(target, period, interval)
            window = PriceChartWindow(model)
            window.refresh_requested.connect(lambda symbol, p, i: _reload_price(window, symbol, p, i))
        elif kind == "curve":
            model = _load_curve(target)
            window = CurveWindow(model)
            window.refresh_requested.connect(lambda currency: _reload_curve(window, currency))
        elif kind == "ovdv":
            model = _load_surface(target)
            if screenshot:
                from ajax_terminal.charts.renderers.pyvista.volatility_surface import render_surface_snapshot

                output = Path(screenshot).resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                render_surface_snapshot(model, str(output))
                return 0
            window = VolatilitySurfaceWindow(model)
            window.refresh_requested.connect(lambda symbol: _reload_surface(window, symbol))
        else:
            raise ValueError(f"Unknown chart kind: {kind}")
    except Exception as exc:
        if screenshot:
            print(f"THRIVEBERG CHART ERROR: {exc}", file=sys.stderr)
            return 2
        QMessageBox.critical(None, "THRIVEBERG CHART ERROR", str(exc))
        return 2
    window.show()
    if isinstance(window, VolatilitySurfaceWindow):
        QTimer.singleShot(80, lambda: window.surface_view.set_view("default"))
    if screenshot:
        output = Path(screenshot).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        captured = False

        def capture() -> None:
            nonlocal captured
            if captured:
                return
            captured = True
            if isinstance(window, VolatilitySurfaceWindow):
                window.surface_view.screenshot(str(output))
            else:
                window.grab().save(str(output))
            app.quit()

        chart = getattr(window, "chart", None)
        if chart is not None and hasattr(chart, "loadFinished"):
            chart.loadFinished.connect(lambda _ok: QTimer.singleShot(1_000, capture))
        QTimer.singleShot(10_000, capture)
    return app.exec()


def _load_price(symbol: str, period: str, interval: str | None, *, refresh: bool = False) -> OHLCVChart:
    clean_period = normalize_history_period(period)
    clean_interval = normalize_history_interval(clean_period, interval)
    history = asyncio.run(
        MarketService().history(
            symbol.upper(), clean_period, clean_interval, allow_mock=False, refresh=refresh
        )
    )
    if not history.bars or history.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
        raise ValueError(f"No real {clean_period}/{clean_interval} history is available for {symbol.upper()}")
    model = normalize_ohlcv(history)
    model.indicators = price_indicators(model)
    return model


def _load_curve(currency: str) -> CurveChart:
    curve = asyncio.run(MarketService().curve(currency.upper(), allow_mock=False))
    model = normalize_curve(curve)
    if not model.points or model.quality in {DataQuality.MOCK.value, DataQuality.UNAVAILABLE.value}:
        raise ValueError(f"No real or derived reference curve is available for {currency.upper()}")
    return model


def _load_surface(symbol: str) -> VolSurface:
    market = MarketService()
    legacy = asyncio.run(OptionsService(market).volatility_surface(symbol.upper()))
    model = normalize_vol_surface(legacy)
    if not model.points or model.status in {DataQuality.MOCK.value, DataQuality.UNAVAILABLE.value}:
        message = legacy.message or "The provider did not return a supported real option chain."
        raise ValueError(f"OVDV {symbol.upper()}: {message}")
    return model


def _run_reload(window, loader: Callable[[], object], setter: Callable[[object], None], message: str) -> None:
    if getattr(window, "_ajax_loader", None) is not None and window._ajax_loader.isRunning():
        return
    if hasattr(window, "set_loading"):
        window.set_loading(message)
    else:
        window.statusBar().showMessage(message)
    thread = _LoadThread(loader)
    window._ajax_loader = thread
    thread.loaded.connect(setter)
    thread.failed.connect(window.set_error)
    thread.finished.connect(lambda: setattr(window, "_ajax_loader", None))
    thread.finished.connect(thread.deleteLater)
    thread.start()


def _reload_price(window: PriceChartWindow, symbol: str, period: str, interval: str) -> None:
    _run_reload(
        window,
        lambda: _load_price(symbol, period, interval, refresh=True),
        window.apply_live_model,
        f"LOADING {symbol} {period}/{interval}...",
    )


def _reload_curve(window: CurveWindow, currency: str) -> None:
    _run_reload(window, lambda: _load_curve(currency), window.set_model, f"LOADING {currency} CURVE...")


def _reload_surface(window: VolatilitySurfaceWindow, symbol: str) -> None:
    _run_reload(window, lambda: _load_surface(symbol), window.set_surface, f"LOADING OVDV {symbol}...")
