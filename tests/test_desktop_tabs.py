from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFrame

from ajax_terminal.desktop_app import AjaxDesktopWindow, _SecurityFunctionMenu


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_terminal_tabs_keep_independent_security_contexts(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "tabs.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        first_stack = window.stack
        first_page = first_stack.currentWidget()

        window._create_terminal_tab("MSFT")
        second_stack = window.stack
        second_page = second_stack.currentWidget()

        assert window.document_tabs.count() == 2
        assert window.current_symbol == "MSFT"
        assert isinstance(second_page, _SecurityFunctionMenu)
        assert "MSFT" in window.document_tabs.tabText(1)

        window.document_tabs.setCurrentIndex(0)
        app.processEvents()

        assert window.current_symbol == "AAPL"
        assert window.stack is first_stack
        assert window.stack.currentWidget() is first_page
        assert isinstance(window.stack.currentWidget(), _SecurityFunctionMenu)
    finally:
        window.close()


def test_inactive_tab_actions_return_to_their_own_tab(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "tab-actions.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        first_page = window.stack.currentWidget()
        assert isinstance(first_page, _SecurityFunctionMenu)

        window._create_terminal_tab("MSFT")
        assert window.document_tabs.currentIndex() == 1

        first_page.command_requested.emit("NVDA")
        app.processEvents()

        assert window.document_tabs.currentIndex() == 0
        assert window.current_symbol == "NVDA"
        assert isinstance(window.stack.currentWidget(), _SecurityFunctionMenu)

        window.document_tabs.setCurrentIndex(1)
        assert window.current_symbol == "MSFT"
    finally:
        window.close()


def test_workspace_loaders_mount_in_the_tab_that_started_them(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "tab-loaders.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        first_stack = window.stack

        def mount(name: object) -> None:
            page = QFrame()
            page.setObjectName(str(name))
            window._replace_workspace(page)

        window._load_workspace("FIRST", lambda: "firstWorkspace", mount)
        window._create_terminal_tab("HOME", execute=False)
        second_stack = window.stack
        window._load_workspace("SECOND", lambda: "secondWorkspace", mount)

        deadline = time.monotonic() + 5.0
        while window._workspace_loaders and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert not window._workspace_loaders
        assert first_stack.currentWidget().objectName() == "firstWorkspace"
        assert second_stack.currentWidget().objectName() == "secondWorkspace"
    finally:
        window.close()


def test_tab_commands_and_session_persistence(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "tab-session.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=True, settings=settings)
    try:
        window.execute_text("AAPL")
        window.execute_text("TAB NEW MSFT")
        assert window.document_tabs.count() == 2
        assert window.current_symbol == "MSFT"

        window.execute_text("TAB CLOSE")
        assert window.document_tabs.count() == 1
        assert window.current_symbol == "AAPL"

        window.execute_text("TAB NEW NVDA")
        window.document_tabs.setCurrentIndex(0)
        window._persist_session_state()
        settings.sync()

        assert settings.value("session/open_tabs") == ["AAPL", "NVDA"]
        assert settings.value("session/active_tab", -1, type=int) == 0
    finally:
        window.close()
        app.processEvents()


def test_current_tab_opens_as_an_independent_workspace_window(tmp_path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "tab-window.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        window.open_current_tab_window()
        app.processEvents()

        assert len(window._secondary_windows) == 1
        child = window._secondary_windows[0]
        assert child.isVisible()
        assert not child._require_login
        assert child.current_symbol == "AAPL"
        assert "AAPL" in child.windowTitle()

        child.close()
        app.processEvents()
        assert not window._secondary_windows
    finally:
        window.close()
        app.processEvents()
