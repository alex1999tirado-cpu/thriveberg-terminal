from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ajax_terminal import __version__
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
from ajax_terminal.startup import StartupStatus


STARTUP_STAGE_NAMES = ("CORE", "DATA", "MARKETS", "NEWS", "WORKSPACE")


@dataclass(frozen=True, slots=True)
class CandleGeometry:
    open: float
    high: float
    low: float
    close: float


# This sequence is deliberately fixed. Startup state may recolor it, never reshape it.
CANDLE_GEOMETRY = (
    CandleGeometry(76, 86, 62, 69),
    CandleGeometry(69, 78, 54, 61),
    CandleGeometry(61, 67, 49, 55),
    CandleGeometry(55, 72, 50, 65),
    CandleGeometry(66, 80, 58, 62),
    CandleGeometry(62, 70, 46, 53),
    CandleGeometry(54, 63, 48, 58),
    CandleGeometry(58, 72, 53, 67),
    CandleGeometry(67, 74, 51, 57),
    CandleGeometry(57, 65, 51, 61),
    CandleGeometry(61, 68, 49, 55),
    CandleGeometry(55, 63, 50, 59),
    CandleGeometry(59, 70, 54, 65),
    CandleGeometry(65, 72, 57, 60),
    CandleGeometry(60, 73, 55, 68),
    CandleGeometry(68, 80, 62, 74),
    CandleGeometry(74, 88, 67, 82),
    CandleGeometry(82, 94, 68, 89),
)

CANDLE_STAGE_INDEX = (0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 4, 4, 4, 4)


def brand_asset_path(filename: str) -> Path:
    if bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS"):
        root = Path(getattr(sys, "_MEIPASS"))
    else:
        root = Path(__file__).resolve().parent.parent
    return root / "ajax_terminal" / "assets" / filename


def thriveberg_icon() -> QIcon:
    path = brand_asset_path("thriveberg-icon.png")
    return QIcon(str(path)) if path.is_file() else QIcon()


def reduced_motion_enabled() -> bool:
    value = os.environ.get("THRIVEBERG_REDUCE_MOTION", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not bool(enabled.value)
    except (AttributeError, OSError):
        return False


class StartupSplash(QWidget):
    """Sparse, terminal-native startup display with immutable OHLC geometry."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startupSplash")
        self.setMinimumSize(1000, 620)
        self._statuses = {name: StartupStatus.PENDING for name in STARTUP_STAGE_NAMES}
        self._progress = {name: 0.0 for name in STARTUP_STAGE_NAMES}
        self._details = {name: "" for name in STARTUP_STAGE_NAMES}
        self._cursor_visible = True
        self._final_status = "INITIALIZING..."
        self._timestamp = datetime.now().astimezone()
        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._tick)
        if not reduced_motion_enabled():
            self._timer.start()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(1500, 860)

    @property
    def candle_geometry(self) -> tuple[CandleGeometry, ...]:
        return CANDLE_GEOMETRY

    @property
    def statuses(self) -> dict[str, StartupStatus]:
        return dict(self._statuses)

    def reset(self) -> None:
        for name in STARTUP_STAGE_NAMES:
            self._statuses[name] = StartupStatus.PENDING
            self._progress[name] = 0.0
            self._details[name] = ""
        self._final_status = "INITIALIZING..."
        self.update()

    @Slot(str)
    def stage_started(self, name: str) -> None:
        if name in self._statuses:
            self._statuses[name] = StartupStatus.LOADING
            self.update()

    @Slot(str, float, str)
    def stage_progress(self, name: str, progress: float, detail: str) -> None:
        if name in self._statuses:
            self._progress[name] = min(1.0, max(0.0, progress))
            if detail:
                self._details[name] = detail
            self.update()

    @Slot(str, str)
    def stage_completed(self, name: str, detail: str) -> None:
        if name in self._statuses:
            self._statuses[name] = StartupStatus.READY
            self._progress[name] = 1.0
            self._details[name] = detail
            self.update()

    @Slot(str, str, bool)
    def stage_failed(self, name: str, message: str, _critical: bool) -> None:
        if name in self._statuses:
            self._statuses[name] = StartupStatus.FAILED
            self._details[name] = message
            self.update()

    def finish(self, *, degraded: bool = False, failed: bool = False) -> None:
        if failed:
            self._final_status = "STARTUP FAILED"
        elif degraded:
            self._final_status = "READY / DEGRADED"
        else:
            self._final_status = "READY"
        self.update()

    def candle_colors(self) -> tuple[str, ...]:
        return tuple(self._color_for_status(self._statuses[STARTUP_STAGE_NAMES[index]]) for index in CANDLE_STAGE_INDEX)

    def _tick(self) -> None:
        self._cursor_visible = not self._cursor_visible
        self._timestamp = datetime.now().astimezone()
        self.update()

    @staticmethod
    def _color_for_status(status: StartupStatus) -> str:
        if status == StartupStatus.READY:
            return AJAX_GREEN
        if status == StartupStatus.LOADING:
            return AJAX_AMBER
        return AJAX_RED

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(AJAX_BACKGROUND))
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        bounds = QRectF(self.rect()).adjusted(40, 34, -40, -34)
        painter.setPen(QPen(QColor(AJAX_BORDER), 1))
        painter.drawRect(bounds)

        self._draw_topline(painter, bounds)
        self._draw_brand(painter, bounds)
        candle_centers = self._draw_candles(painter, bounds)
        self._draw_stage_labels(painter, bounds, candle_centers)
        self._draw_status_rows(painter, bounds)
        self._draw_footer(painter, bounds)

    def _draw_topline(self, painter: QPainter, bounds: QRectF) -> None:
        font = QFont("DejaVu Sans Mono", 12)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.setPen(QColor(AJAX_CYAN))
        painter.drawText(
            QRectF(bounds.left() + 30, bounds.top() + 28, 420, 54),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"THRIVEBERG v{__version__}\nINITIALIZING...",
        )
        stamp = self._timestamp.strftime("MADRID %Y-%m-%d %H:%M:%S")
        painter.drawText(
            QRectF(bounds.right() - 430, bounds.top() + 28, 400, 54),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            f"MARKETS. DATA. ANALYTICS.\n{stamp}",
        )

    def _draw_brand(self, painter: QPainter, bounds: QRectF) -> None:
        font = QFont("DejaVu Sans Mono", 46, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
        painter.setFont(font)
        painter.setPen(QColor(AJAX_AMBER))
        text = "THRIVEBERG_" if self._cursor_visible else "THRIVEBERG "
        painter.drawText(
            QRectF(bounds.left(), bounds.top() + 110, bounds.width(), 82),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _draw_candles(self, painter: QPainter, bounds: QRectF) -> tuple[float, ...]:
        left = bounds.left() + bounds.width() * 0.17
        right = bounds.right() - bounds.width() * 0.17
        top = bounds.top() + 228
        bottom = bounds.top() + min(420.0, bounds.height() * 0.55)
        step = (right - left) / (len(CANDLE_GEOMETRY) - 1)
        body_width = min(14.0, max(7.0, step * 0.26))
        centers: list[float] = []

        def price_y(value: float) -> float:
            return bottom - (value - 42.0) / 56.0 * (bottom - top)

        for index, candle in enumerate(CANDLE_GEOMETRY):
            center = left + index * step
            centers.append(center)
            color = QColor(self.candle_colors()[index])
            painter.setPen(QPen(color, 2))
            painter.drawLine(round(center), round(price_y(candle.high)), round(center), round(price_y(candle.low)))
            open_y = price_y(candle.open)
            close_y = price_y(candle.close)
            body_top = min(open_y, close_y)
            body_height = max(4.0, abs(open_y - close_y))
            painter.fillRect(QRectF(center - body_width / 2, body_top, body_width, body_height), color)
        return tuple(centers)

    def _draw_stage_labels(self, painter: QPainter, bounds: QRectF, centers: tuple[float, ...]) -> None:
        font = QFont("DejaVu Sans Mono", 11)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.setPen(QColor(AJAX_CYAN))
        y = bounds.top() + min(438.0, bounds.height() * 0.575)
        for stage_index, name in enumerate(STARTUP_STAGE_NAMES):
            indexes = [i for i, value in enumerate(CANDLE_STAGE_INDEX) if value == stage_index]
            center = sum(centers[i] for i in indexes) / len(indexes)
            painter.drawText(
                QRectF(center - 72, y, 144, 28),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                name,
            )

    def _draw_status_rows(self, painter: QPainter, bounds: QRectF) -> None:
        font = QFont("DejaVu Sans Mono", 11)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        painter.setFont(font)
        start_y = bounds.bottom() - 150
        for index, name in enumerate(STARTUP_STAGE_NAMES):
            status = self._statuses[name]
            status_text = status.value
            if status == StartupStatus.LOADING:
                status_text = f"LOADING... {self._progress[name] * 100:3.0f}%"
            elif status == StartupStatus.PENDING:
                status_text = "PENDING..."
            painter.setPen(QColor(AJAX_CYAN if status != StartupStatus.FAILED else AJAX_RED))
            painter.drawText(bounds.left() + 30, start_y + index * 25, f">  {name:<12} {status_text}")

    def _draw_footer(self, painter: QPainter, bounds: QRectF) -> None:
        font = QFont("DejaVu Sans Mono", 11)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        status_color = AJAX_RED if self._final_status == "STARTUP FAILED" else AJAX_AMBER
        painter.setPen(QColor(status_color))
        metrics = QFontMetricsF(font)
        status_width = metrics.horizontalAdvance(self._final_status)
        painter.drawText(bounds.right() - status_width - 30, bounds.bottom() - 54, self._final_status)
        painter.setPen(QColor(AJAX_CYAN))
        tagline = "BUILT FOR A CLEARER PERSPECTIVE."
        tagline_width = metrics.horizontalAdvance(tagline)
        painter.drawText(bounds.right() - tagline_width - 30, bounds.bottom() - 25, tagline)
