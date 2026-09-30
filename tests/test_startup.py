from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ajax_terminal.startup import StartupManager, StartupStage, StartupStatus
from ajax_terminal.startup_splash import CANDLE_GEOMETRY, StartupSplash


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _run_manager(manager: StartupManager, timeout_ms: int = 2_000) -> tuple[bool, tuple]:
    app = _app()
    result: list[tuple[bool, tuple]] = []
    loop = QEventLoop()
    manager.startup_completed.connect(
        lambda success, failures: (result.append((success, tuple(failures))), loop.quit())
    )
    QTimer.singleShot(timeout_ms, loop.quit)
    manager.start()
    loop.exec()
    app.processEvents()
    manager.stop()
    assert result, "startup manager timed out"
    return result[0]


def test_startup_manager_emits_stages_in_order() -> None:
    observed: list[str] = []
    stages = tuple(
        StartupStage(name, lambda report, stage=name: (report(0.5, stage), stage)[1])
        for name in ("CORE", "DATA", "MARKETS", "NEWS", "WORKSPACE")
    )
    manager = StartupManager(stages, minimum_stage_ms=0)
    manager.stage_started.connect(observed.append)

    success, failures = _run_manager(manager)

    assert success is True
    assert failures == ()
    assert observed == ["CORE", "DATA", "MARKETS", "NEWS", "WORKSPACE"]
    assert all(status == StartupStatus.READY for status in manager.statuses.values())


def test_noncritical_failure_keeps_startup_running() -> None:
    observed: list[str] = []

    def fail(_report) -> None:
        raise RuntimeError("offline")

    manager = StartupManager(
        (
            StartupStage("CORE", lambda _report: "ok", critical=True),
            StartupStage("NEWS", fail),
            StartupStage("WORKSPACE", lambda _report: "ok", critical=True),
        ),
        minimum_stage_ms=0,
    )
    manager.stage_started.connect(observed.append)

    success, failures = _run_manager(manager)

    assert success is True
    assert observed == ["CORE", "NEWS", "WORKSPACE"]
    assert failures == (("NEWS", "offline", False),)
    assert manager.statuses["NEWS"] == StartupStatus.FAILED
    assert manager.statuses["WORKSPACE"] == StartupStatus.READY


def test_critical_failure_stops_later_stages() -> None:
    observed: list[str] = []

    def fail(_report) -> None:
        raise RuntimeError("database unavailable")

    manager = StartupManager(
        (
            StartupStage("CORE", fail, critical=True),
            StartupStage("DATA", lambda _report: "not reached"),
        ),
        minimum_stage_ms=0,
    )
    manager.stage_started.connect(observed.append)

    success, failures = _run_manager(manager)

    assert success is False
    assert observed == ["CORE"]
    assert failures == (("CORE", "database unavailable", True),)
    assert manager.statuses["CORE"] == StartupStatus.FAILED
    assert manager.statuses["DATA"] == StartupStatus.PENDING


def test_splash_recolors_candles_without_changing_ohlc_geometry() -> None:
    splash = StartupSplash()
    original = splash.candle_geometry

    assert original == CANDLE_GEOMETRY
    assert len(original) == 18
    assert len(set(original)) == len(original)
    assert set(splash.candle_colors()) == {"#ff315f"}

    splash.stage_started("CORE")
    loading_colors = splash.candle_colors()
    splash.stage_completed("CORE", "ready")
    ready_colors = splash.candle_colors()

    assert splash.candle_geometry == original
    assert loading_colors[:4] == ("#ffb000",) * 4
    assert ready_colors[:4] == ("#62e600",) * 4
    assert ready_colors[4:] == ("#ff315f",) * 14


def test_brand_icon_contains_required_resolutions() -> None:
    root = Path(__file__).resolve().parents[1]
    png = Image.open(root / "ajax_terminal" / "assets" / "thriveberg-icon.png")
    icon = Image.open(root / "ajax_terminal" / "assets" / "thriveberg.ico")

    assert png.size == (1024, 1024)
    assert set(icon.info["sizes"]) >= {
        (16, 16),
        (32, 32),
        (64, 64),
        (128, 128),
        (256, 256),
    }
    for size in (16, 32, 64, 128, 256):
        icon.size = (size, size)
        rgba = icon.convert("RGBA")
        pixels = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
        amber_pixels = sum(1 for pixel in pixels if pixel[0] > 220 and pixel[1] > 100)
        assert amber_pixels >= max(3, size // 2)
