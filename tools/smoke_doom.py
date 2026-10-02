from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import QApplication

from ajax_terminal.desktop_app import AjaxDesktopWindow
from ajax_terminal.games.doom import DoomWorkspace


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = AjaxDesktopWindow(require_login=False)
    window.resize(1440, 900)
    window.show()
    result = {"code": 1, "message": "DOOM smoke test timed out."}

    def fail(message: str) -> None:
        result.update(code=1, message=message)
        window.close()
        app.quit()

    def verify_docked_again(workspace: DoomWorkspace, process_id: int) -> None:
        bridge = workspace._bridge
        if bridge is None:
            fail("Native bridge disappeared while docking.")
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if int(user32.GetParent(bridge.hwnd)) != int(workspace._host.winId()):
            fail("Native game window did not dock back into THRIVEBERG.")
            return
        window.execute_text("HOME")
        if workspace._process is not None:
            fail("DOOM process was not released after leaving the workspace.")
            return
        shutdown_mode = "graceful" if workspace._last_shutdown_graceful else "bounded fallback"
        result.update(
            code=0,
            message=(
                f"DOOM embedded, popped out, docked and stopped without a residual process "
                f"(PID {process_id}, {shutdown_mode})."
            ),
        )
        window.close()
        app.quit()

    def verify_popped_out(workspace: DoomWorkspace, process_id: int) -> None:
        bridge = workspace._bridge
        if bridge is None:
            fail("Native bridge disappeared while popping out.")
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if int(user32.GetParent(bridge.hwnd)) != 0:
            fail("Native game window remained parented after POP OUT.")
            return
        if not workspace.toggle_pop_out():
            fail("DOCK action failed.")
            return
        QTimer.singleShot(350, lambda: verify_docked_again(workspace, process_id))

    def workspace_ready() -> None:
        if window.current_route.kind != "doom":
            return
        workspace = window.stack.currentWidget()
        if not isinstance(workspace, DoomWorkspace) or not workspace.can_pop_out:
            fail("DOOM workspace reported ready without an attached game window.")
            return
        process = workspace._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            fail("DOOM process stopped before the workspace became ready.")
            return
        process_id = int(process.processId())
        bridge = workspace._bridge
        if bridge is None:
            fail("DOOM native bridge is unavailable.")
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if int(user32.GetParent(bridge.hwnd)) != int(workspace._host.winId()):
            fail("DOOM native window is not embedded in the terminal viewport.")
            return
        if not workspace.toggle_pop_out():
            fail("POP OUT action failed.")
            return
        QTimer.singleShot(350, lambda: verify_popped_out(workspace, process_id))

    window.workspace_ready.connect(workspace_ready)
    QTimer.singleShot(20_000, lambda: fail(result["message"]))
    window.start("DOOM")
    app.exec()
    print(result["message"])
    return int(result["code"])


if __name__ == "__main__":
    raise SystemExit(main())
