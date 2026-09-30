from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QThread, Signal, Slot


class StartupStatus(str, Enum):
    PENDING = "PENDING"
    LOADING = "LOADING"
    READY = "READY"
    FAILED = "FAILED"


ProgressReporter = Callable[[float, str], None]
StartupTask = Callable[[ProgressReporter], str | None]


@dataclass(frozen=True, slots=True)
class StartupStage:
    name: str
    task: StartupTask
    critical: bool = False


class _StartupWorker(QThread):
    stage_started = Signal(str)
    stage_progress = Signal(str, float, str)
    stage_completed = Signal(str, str)
    stage_failed = Signal(str, str, bool)
    startup_completed = Signal(bool, object)

    def __init__(self, stages: tuple[StartupStage, ...], minimum_stage_ms: int) -> None:
        super().__init__()
        self.stages = stages
        self.minimum_stage_ms = max(0, minimum_stage_ms)

    def run(self) -> None:
        failures: list[tuple[str, str, bool]] = []
        startup_ok = True
        for stage in self.stages:
            if self.isInterruptionRequested():
                startup_ok = False
                break
            started = time.monotonic()
            self.stage_started.emit(stage.name)
            self.stage_progress.emit(stage.name, 0.0, "")

            def report(progress: float, detail: str = "") -> None:
                bounded = min(1.0, max(0.0, float(progress)))
                self.stage_progress.emit(stage.name, bounded, detail)

            try:
                detail = stage.task(report) or ""
                self._hold_stage_for_readability(started)
                self.stage_progress.emit(stage.name, 1.0, detail)
                self.stage_completed.emit(stage.name, detail)
            except Exception as exc:  # startup errors must reach the visible status panel
                message = str(exc).strip() or exc.__class__.__name__
                failures.append((stage.name, message, stage.critical))
                self.stage_failed.emit(stage.name, message, stage.critical)
                if stage.critical:
                    startup_ok = False
                    break
        self.startup_completed.emit(startup_ok, tuple(failures))

    def _hold_stage_for_readability(self, started: float) -> None:
        remaining = self.minimum_stage_ms / 1_000 - (time.monotonic() - started)
        if remaining > 0 and not self.isInterruptionRequested():
            self.msleep(round(remaining * 1_000))


class StartupManager(QObject):
    """Runs observable startup work without blocking the Qt event loop."""

    stage_started = Signal(str)
    stage_progress = Signal(str, float, str)
    stage_completed = Signal(str, str)
    stage_failed = Signal(str, str, bool)
    startup_completed = Signal(bool, object)

    def __init__(
        self,
        stages: tuple[StartupStage, ...],
        *,
        minimum_stage_ms: int = 120,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not stages:
            raise ValueError("At least one startup stage is required")
        self.stages = stages
        self.statuses = {stage.name: StartupStatus.PENDING for stage in stages}
        self._worker = _StartupWorker(stages, minimum_stage_ms)
        self._worker.stage_started.connect(self._stage_started)
        self._worker.stage_progress.connect(self.stage_progress)
        self._worker.stage_completed.connect(self._stage_completed)
        self._worker.stage_failed.connect(self._stage_failed)
        self._worker.startup_completed.connect(self.startup_completed)

    @property
    def is_running(self) -> bool:
        return self._worker.isRunning()

    def start(self) -> None:
        if self._worker.isRunning():
            return
        self._worker.start()

    def stop(self, timeout_ms: int = 2_000) -> None:
        if not self._worker.isRunning():
            return
        self._worker.requestInterruption()
        self._worker.wait(timeout_ms)

    @Slot(str)
    def _stage_started(self, name: str) -> None:
        self.statuses[name] = StartupStatus.LOADING
        self.stage_started.emit(name)

    @Slot(str, str)
    def _stage_completed(self, name: str, detail: str) -> None:
        self.statuses[name] = StartupStatus.READY
        self.stage_completed.emit(name, detail)

    @Slot(str, str, bool)
    def _stage_failed(self, name: str, message: str, critical: bool) -> None:
        self.statuses[name] = StartupStatus.FAILED
        self.stage_failed.emit(name, message, critical)
