from __future__ import annotations

import importlib.util
import os
import struct
import subprocess
import sys
from pathlib import Path

from ajax_terminal.config import application_roots
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period


class ChartRuntimeError(RuntimeError):
    pass


def launch_price_chart(symbol: str, period: str = "1Y", interval: str | None = None) -> subprocess.Popen:
    clean_period = normalize_history_period(period)
    clean_interval = normalize_history_interval(clean_period, interval)
    return _launch("price", symbol.upper().strip(), clean_period, clean_interval)


def launch_curve_chart(currency: str) -> subprocess.Popen:
    return _launch("curve", currency.upper().strip())


def launch_volatility_surface(symbol: str) -> subprocess.Popen:
    return _launch("ovdv", symbol.upper().strip())


def chart_runtime_python() -> Path:
    configured = os.environ.get("AJAX_GUI_PYTHON")
    candidates = [Path(configured)] if configured else []
    for root in application_roots():
        candidates.extend(
            [
                root / ".venv_gui" / "Scripts" / "pythonw.exe",
                root / ".venv_gui" / "Scripts" / "python.exe",
            ]
        )
    if struct.calcsize("P") * 8 == 64 and importlib.util.find_spec("PySide6") is not None:
        candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise ChartRuntimeError(
        "The 64-bit chart runtime is not installed. Run setup_charts.ps1 once, "
        "or set AJAX_GUI_PYTHON to a 64-bit Python with the charts extra installed."
    )


def _launch(kind: str, *args: str) -> subprocess.Popen:
    runtime = chart_runtime_python()
    command = [str(runtime), "-m", "ajax_terminal", "--gui-chart", kind, *args]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    working_directory = next(
        (root for root in application_roots() if (root / ".env").is_file()),
        Path.cwd(),
    )
    return subprocess.Popen(
        command,
        cwd=working_directory,
        env=os.environ.copy(),
        creationflags=creation_flags,
    )
