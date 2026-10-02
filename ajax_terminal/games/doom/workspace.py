from __future__ import annotations

import ctypes
import hashlib
import json
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_CYAN, AJAX_MUTED, AJAX_RED, AJAX_TEXT
from ajax_terminal.secure_settings import user_data_directory


DOOM_MANIFEST_SHA256 = (
    "0a2e073f7a6582d4ae17dbcdcfdb01c31f7935a6f74c8dfcc4f412df5371716e"  # pragma: allowlist secret - public asset checksum
)
DOOM_WINDOW_TIMEOUT_MS = 12_000


class DoomAssetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DoomAssets:
    root: Path
    executable: Path
    iwad: Path


def doom_asset_root() -> Path:
    if bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS"):
        package_root = Path(getattr(sys, "_MEIPASS")) / "ajax_terminal"
    else:
        package_root = Path(__file__).resolve().parents[2]
    return package_root / "games" / "doom" / "assets"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_doom_assets(root: Path | None = None) -> DoomAssets:
    asset_root = (root or doom_asset_root()).resolve()
    manifest_path = asset_root / "manifest.json"
    if not manifest_path.is_file():
        raise DoomAssetError("DOOM runtime manifest is missing.")
    if _sha256(manifest_path) != DOOM_MANIFEST_SHA256:
        raise DoomAssetError("DOOM runtime manifest failed its integrity check.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DoomAssetError("DOOM runtime manifest is unreadable.") from exc
    if manifest.get("schema") != 1 or not isinstance(manifest.get("assets"), list):
        raise DoomAssetError("DOOM runtime manifest has an unsupported format.")

    verified: set[str] = set()
    for item in manifest["assets"]:
        if not isinstance(item, dict):
            raise DoomAssetError("DOOM runtime manifest contains an invalid entry.")
        relative = str(item.get("path", "")).replace("\\", "/")
        untrusted_candidate = asset_root / relative
        candidate = untrusted_candidate.resolve()
        try:
            candidate.relative_to(asset_root)
        except ValueError as exc:
            raise DoomAssetError("DOOM runtime manifest contains an unsafe path.") from exc
        if untrusted_candidate.is_symlink() or not candidate.is_file():
            raise DoomAssetError(f"DOOM runtime asset is missing: {relative}")
        try:
            expected_size = int(item["size"])
            expected_hash = str(item["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise DoomAssetError("DOOM runtime manifest contains invalid metadata.") from exc
        if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
            raise DoomAssetError("DOOM runtime manifest contains an invalid checksum.")
        if candidate.stat().st_size != expected_size or _sha256(candidate) != expected_hash:
            raise DoomAssetError(f"DOOM runtime asset failed verification: {relative}")
        verified.add(relative)

    executable_rel = "engine/chocolate-doom.exe"
    iwad_rel = "content/freedoom1.wad"
    if not {executable_rel, iwad_rel}.issubset(verified):
        raise DoomAssetError("DOOM runtime manifest is incomplete.")
    return DoomAssets(
        root=asset_root,
        executable=asset_root / executable_rel,
        iwad=asset_root / iwad_rel,
    )


def doom_user_directory() -> Path:
    return user_data_directory() / "games" / "doom"


def build_doom_arguments(
    assets: DoomAssets,
    user_root: Path,
    *,
    width: int = 960,
    height: int = 600,
) -> list[str]:
    width = max(640, int(width))
    height = max(400, int(height))
    return [
        "-iwad",
        str(assets.iwad),
        "-window",
        "-geometry",
        f"{width}x{height}",
        "-config",
        str(user_root / "default.cfg"),
        "-extraconfig",
        str(user_root / "chocolate-doom.cfg"),
        "-savedir",
        str(user_root / "savegames"),
        "-nogui",
    ]


class _Win32WindowBridge:
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    GW_OWNER = 4
    SW_HIDE = 0
    SW_SHOW = 5
    SW_RESTORE = 9
    SWP_FRAMECHANGED = 0x0020
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    WM_CLOSE = 0x0010
    WS_CAPTION = 0x00C00000
    WS_CHILD = 0x40000000
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000
    WS_POPUP = 0x80000000
    WS_SYSMENU = 0x00080000
    WS_THICKFRAME = 0x00040000
    WS_VISIBLE = 0x10000000
    WS_EX_APPWINDOW = 0x00040000

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise DoomAssetError("The embedded DOOM runtime is currently available on Windows only.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        pointer_type = ctypes.c_ssize_t
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongPtrW.restype = pointer_type
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, pointer_type]
        self.user32.SetWindowLongPtrW.restype = pointer_type
        self.user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        self.user32.SetParent.restype = wintypes.HWND
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.hwnd = 0
        self.original_style = 0
        self.original_exstyle = 0
        self.original_rect = wintypes.RECT(100, 100, 1060, 700)

    def find_window(self, process_id: int) -> int:
        matches: list[tuple[int, str]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            window_pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value != process_id or not self.user32.IsWindowVisible(hwnd):
                return True
            if self.user32.GetWindow(hwnd, self.GW_OWNER):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            title_buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
            self.user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            matches.append((int(hwnd), title_buffer.value))
            return True

        self.user32.EnumWindows(callback, 0)
        if not matches:
            return 0
        preferred = next(
            (handle for handle, title in matches if "doom" in title.lower() or "freedoom" in title.lower()),
            matches[0][0],
        )
        return preferred

    def embed(self, hwnd: int, parent_hwnd: int, width: int, height: int) -> None:
        if not self.hwnd:
            self.hwnd = hwnd
            self.original_style = int(self.user32.GetWindowLongPtrW(hwnd, self.GWL_STYLE))
            self.original_exstyle = int(self.user32.GetWindowLongPtrW(hwnd, self.GWL_EXSTYLE))
            self.user32.GetWindowRect(hwnd, ctypes.byref(self.original_rect))
        self.user32.ShowWindow(hwnd, self.SW_HIDE)
        self.user32.SetParent(hwnd, parent_hwnd)
        remove = (
            self.WS_CAPTION
            | self.WS_THICKFRAME
            | self.WS_MINIMIZEBOX
            | self.WS_MAXIMIZEBOX
            | self.WS_SYSMENU
            | self.WS_POPUP
        )
        child_style = (self.original_style & ~remove) | self.WS_CHILD | self.WS_VISIBLE
        self.user32.SetWindowLongPtrW(hwnd, self.GWL_STYLE, child_style)
        self.user32.SetWindowLongPtrW(hwnd, self.GWL_EXSTYLE, self.original_exstyle & ~self.WS_EX_APPWINDOW)
        self.resize(width, height)
        self.user32.ShowWindow(hwnd, self.SW_SHOW)

    def resize(self, width: int, height: int) -> None:
        if not self.hwnd:
            return
        self.user32.SetWindowPos(
            self.hwnd,
            0,
            0,
            0,
            max(width, 1),
            max(height, 1),
            self.SWP_FRAMECHANGED | self.SWP_NOACTIVATE | self.SWP_SHOWWINDOW,
        )

    def pop_out(self) -> None:
        if not self.hwnd:
            return
        self.user32.ShowWindow(self.hwnd, self.SW_HIDE)
        self.user32.SetParent(self.hwnd, 0)
        self.user32.SetWindowLongPtrW(self.hwnd, self.GWL_STYLE, self.original_style)
        self.user32.SetWindowLongPtrW(self.hwnd, self.GWL_EXSTYLE, self.original_exstyle)
        width = max(self.original_rect.right - self.original_rect.left, 960)
        height = max(self.original_rect.bottom - self.original_rect.top, 600)
        self.user32.SetWindowPos(
            self.hwnd,
            0,
            self.original_rect.left,
            self.original_rect.top,
            width,
            height,
            self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW,
        )
        self.user32.ShowWindow(self.hwnd, self.SW_RESTORE)
        self.user32.SetForegroundWindow(self.hwnd)

    def focus(self) -> None:
        if self.hwnd:
            self.user32.SetForegroundWindow(self.hwnd)
            self.user32.SetFocus(self.hwnd)

    def close(self) -> None:
        if self.hwnd:
            self.user32.ShowWindow(self.hwnd, self.SW_HIDE)
            self.user32.SetParent(self.hwnd, 0)
            self.user32.SetWindowLongPtrW(self.hwnd, self.GWL_STYLE, self.original_style)
            self.user32.SetWindowLongPtrW(self.hwnd, self.GWL_EXSTYLE, self.original_exstyle)
            self.user32.SetWindowPos(
                self.hwnd,
                0,
                self.original_rect.left,
                self.original_rect.top,
                max(self.original_rect.right - self.original_rect.left, 960),
                max(self.original_rect.bottom - self.original_rect.top, 600),
                self.SWP_FRAMECHANGED | self.SWP_NOACTIVATE,
            )
            self.user32.PostMessageW(self.hwnd, self.WM_CLOSE, 0, 0)


class DoomWorkspace(QFrame):
    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, auto_start: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("terminalPanel")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._process: QProcess | None = None
        self._bridge: _Win32WindowBridge | None = None
        self._attach_timer = QTimer(self)
        self._attach_timer.setInterval(75)
        self._attach_timer.timeout.connect(self._try_attach)
        self._attach_elapsed_ms = 0
        self._popped_out = False
        self._closing = False
        self._last_shutdown_graceful: bool | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("controlStrip")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(9, 4, 7, 4)
        header_layout.setSpacing(5)
        title = QLabel("DOOM  |  FREEDOOM: PHASE 1")
        title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        self._engine_label = QLabel("CHOCOLATE DOOM 3.1.1")
        self._engine_label.setStyleSheet(f"color:{AJAX_MUTED}")
        header_layout.addWidget(self._engine_label)
        self._dock_button = self._button("POP OUT", self.toggle_pop_out)
        self._dock_button.setEnabled(False)
        header_layout.addWidget(self._dock_button)
        header_layout.addWidget(self._button("RESTART", self.restart_game))
        header_layout.addWidget(self._button("STOP", self.shutdown))
        outer.addWidget(header)

        self._host = QFrame()
        self._host.setObjectName("doomViewport")
        self._host.setStyleSheet("QFrame#doomViewport{background:#000000;border:1px solid #252a2e}")
        self._host.setMinimumSize(640, 400)
        host_layout = QVBoxLayout(self._host)
        host_layout.setContentsMargins(24, 24, 24, 24)
        host_layout.addStretch(1)
        self._status = QLabel("VERIFYING RUNTIME ...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color:{AJAX_AMBER};font-size:18px;font-weight:bold")
        host_layout.addWidget(self._status)
        self._detail = QLabel("CHOCOLATE DOOM / FREEDOOM PHASE 1")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setStyleSheet(f"color:{AJAX_TEXT};font-size:13px")
        host_layout.addWidget(self._detail)
        host_layout.addStretch(1)
        outer.addWidget(self._host, 1)

        legal = QLabel("FREE CONTENT  |  FREEDOOM 0.13.0 BSD-3-CLAUSE  |  ENGINE SOURCE AND LICENSES INCLUDED")
        legal.setObjectName("footerBar")
        legal.setStyleSheet(f"color:{AJAX_MUTED};padding:3px 8px")
        outer.addWidget(legal)

        if auto_start:
            QTimer.singleShot(0, self.start_game)

    @staticmethod
    def _button(label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("menuButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    @property
    def can_pop_out(self) -> bool:
        return bool(
            self._bridge
            and self._bridge.hwnd
            and self._process
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def start_game(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            return
        self._closing = False
        self._popped_out = False
        self._dock_button.setText("POP OUT")
        self._dock_button.setEnabled(False)
        self._status.setText("VERIFYING RUNTIME ...")
        self._status.setStyleSheet(f"color:{AJAX_AMBER};font-size:18px;font-weight:bold")
        self._status.show()
        self._detail.show()
        try:
            assets = validate_doom_assets()
            user_root = doom_user_directory()
            (user_root / "savegames").mkdir(parents=True, exist_ok=True)
            for config_name in ("default.cfg", "chocolate-doom.cfg"):
                (user_root / config_name).touch(exist_ok=True)
            bridge = _Win32WindowBridge()
        except (DoomAssetError, OSError) as exc:
            self._show_error(str(exc))
            return

        process = QProcess(self)
        process.setProgram(str(assets.executable))
        process.setArguments(
            build_doom_arguments(
                assets,
                user_root,
                width=max(self._host.width(), 640),
                height=max(self._host.height(), 400),
            )
        )
        process.setWorkingDirectory(str(assets.executable.parent))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.started.connect(self._process_started)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self._bridge = bridge
        self._process = process
        self._status.setText("STARTING FREEDOOM ...")
        process.start()

    def restart_game(self) -> None:
        self.shutdown()
        QTimer.singleShot(150, self.start_game)

    def toggle_pop_out(self) -> bool:
        if not self.can_pop_out or self._bridge is None:
            return False
        if self._popped_out:
            self._bridge.embed(
                self._bridge.hwnd,
                int(self._host.winId()),
                self._host.width(),
                self._host.height(),
            )
            self._popped_out = False
            self._dock_button.setText("POP OUT")
            self.status_changed.emit("DOOM DOCKED IN TERMINAL")
        else:
            self._bridge.pop_out()
            self._popped_out = True
            self._dock_button.setText("DOCK")
            self.status_changed.emit("DOOM POPPED OUT")
        return True

    def pop_out(self) -> bool:
        if self._popped_out:
            return True
        return self.toggle_pop_out()

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._last_shutdown_graceful = None
        self._attach_timer.stop()
        process = self._process
        bridge = self._bridge
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            if bridge is not None:
                bridge.close()
            self._last_shutdown_graceful = process.waitForFinished(350)
            if not self._last_shutdown_graceful:
                process.terminate()
                self._last_shutdown_graceful = process.waitForFinished(450)
            if not self._last_shutdown_graceful:
                process.kill()
                process.waitForFinished(500)
        self._process = None
        self._bridge = None
        self._popped_out = False
        self._dock_button.setEnabled(False)
        self._dock_button.setText("POP OUT")
        self._status.setText("DOOM STOPPED")
        self._status.show()
        self._detail.show()
        self._closing = False

    def _process_started(self) -> None:
        self._attach_elapsed_ms = 0
        self._status.setText("ATTACHING GAME WINDOW ...")
        self._attach_timer.start()

    def _try_attach(self) -> None:
        process = self._process
        bridge = self._bridge
        if process is None or bridge is None or process.state() == QProcess.ProcessState.NotRunning:
            self._attach_timer.stop()
            return
        self._attach_elapsed_ms += self._attach_timer.interval()
        hwnd = bridge.find_window(int(process.processId()))
        if hwnd:
            bridge.embed(hwnd, int(self._host.winId()), self._host.width(), self._host.height())
            self._attach_timer.stop()
            self._status.hide()
            self._detail.hide()
            self._dock_button.setEnabled(True)
            self.status_changed.emit("DOOM READY / FREEDOOM PHASE 1")
            return
        if self._attach_elapsed_ms >= DOOM_WINDOW_TIMEOUT_MS:
            self._attach_timer.stop()
            message = "The DOOM process started, but its game window could not be attached."
            self.shutdown()
            self._show_error(message)

    def _process_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._attach_timer.stop()
        self._dock_button.setEnabled(False)
        self._dock_button.setText("POP OUT")
        self._popped_out = False
        if not self._closing:
            output = ""
            if self._process is not None:
                output = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            if exit_code == 0:
                self._status.setText("DOOM SESSION ENDED")
                self._status.setStyleSheet(f"color:{AJAX_AMBER};font-size:18px;font-weight:bold")
                self._status.show()
                self._detail.show()
            else:
                tail = output.splitlines()[-1] if output else f"EXIT CODE {exit_code}"
                self._show_error(tail[:180])
        self.status_changed.emit("DOOM SESSION ENDED")

    def _process_error(self, _error: QProcess.ProcessError) -> None:
        if self._process is not None:
            self._show_error(self._process.errorString())

    def _show_error(self, message: str) -> None:
        self._status.setText("DOOM RUNTIME ERROR")
        self._status.setStyleSheet(f"color:{AJAX_RED};font-size:18px;font-weight:bold")
        self._detail.setText(message)
        self._status.show()
        self._detail.show()
        self.status_changed.emit(f"DOOM ERROR: {message}")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt callback
        super().resizeEvent(event)
        if self.can_pop_out and not self._popped_out and self._bridge is not None:
            self._bridge.resize(self._host.width(), self._host.height())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt callback
        super().showEvent(event)
        if self.can_pop_out and not self._popped_out and self._bridge is not None:
            QTimer.singleShot(0, lambda: self._bridge and self._bridge.resize(self._host.width(), self._host.height()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt callback
        if self._bridge is not None:
            self._bridge.focus()
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt callback
        self.shutdown()
        super().closeEvent(event)
