from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from ajax_terminal.desktop_app import AjaxDesktopWindow, _SecurityFunctionMenu, resolve_desktop_command
from ajax_terminal.ui.commands.parser import parse_command
from ajax_terminal.ui.suggestions import SecuritySuggestion


def test_desktop_security_finder_supports_keyboard_selection(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.command.setText("apple")
        window._suggestion_timer.stop()
        window._render_suggestions(
            [
                SecuritySuggestion("AAPL", "AAPL", "Apple Inc.", "EQUITY"),
                SecuritySuggestion("MSFT", "MSFT", "Microsoft Corporation", "EQUITY"),
            ],
            "SECURITY SEARCH",
        )
        window.command.setFocus()
        app.processEvents()

        QTest.keyClick(window.command, Qt.Key.Key_Down)
        assert window.suggestion_table.currentRow() == 1

        QTest.keyClick(window.command, Qt.Key.Key_Return)
        app.processEvents()
        assert window.current_symbol == "MSFT"
        assert window.suggestion_panel.isHidden()
    finally:
        window.close()


def test_selected_security_opens_a_clickable_function_directory(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "directory.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        page = window.stack.currentWidget()
        assert isinstance(page, _SecurityFunctionMenu)
        assert page.objectName() == "securityFunctionMenu"

        commands: list[str] = []
        standalone = _SecurityFunctionMenu("AAPL", "Apple Inc.", "EQUITY")
        standalone.command_requested.connect(commands.append)
        standalone.show()
        app.processEvents()
        row = standalone.findChild(QFrame, "functionMenuRow_DES")
        assert row is not None
        code = row.findChild(QLabel, "functionMenuCode")
        description = row.findChild(QLabel, "functionMenuDescription")
        assert code is not None and "DES" in code.text()
        assert description is not None and description.text() == "Security Description"

        QTest.mouseClick(row, Qt.MouseButton.LeftButton)
        assert commands == ["AAPL DES"]
        standalone.close()
    finally:
        window.close()


def test_news_topic_does_not_replace_active_security(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "news-topic.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        route = resolve_desktop_command("NEWS JAPAN", window.current_symbol)
        parsed = parse_command(route.raw)

        assert not window._is_security_context(route, parsed)
        window._set_route_labels(route)
        assert "JAPAN Equity" not in window.function_bar.text()
        assert window.function_bar.text() == "NEWS  |  JAPAN"

        monkeypatch.setattr(window, "_load_workspace", lambda *args, **kwargs: None)
        window.execute_text("NEWS JAPAN")
        assert window.current_symbol == "AAPL"
    finally:
        window.close()


def test_desktop_has_no_default_security_and_prompts_before_gp(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "empty-context.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        assert window.current_symbol == ""
        assert "NO ACTIVE SECURITY" in window.instrument_bar.text()

        window.execute_text("GP")
        app.processEvents()

        assert window.current_symbol == ""
        assert window.current_route.kind == "security-required"
        assert "SELECT SECURITY" in window.function_bar.text()
        assert window.stack.currentWidget().objectName() == "emptyWorkspace"
    finally:
        window.close()


def test_function_bar_links_open_real_security_views(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "function-links.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    try:
        window.execute_text("AAPL")
        route = resolve_desktop_command("NEWS AAPL", window.current_symbol)
        assert window._is_security_context(route, parse_command(route.raw))
        window._set_route_labels(route)
        assert "href='asset:AAPL'" in window.function_bar.text()
        assert "href='actions:AAPL'" in window.function_bar.text()
        assert "href='settings:AAPL'" in window.function_bar.text()

        window._function_bar_link("actions:AAPL")
        assert isinstance(window.stack.currentWidget(), _SecurityFunctionMenu)

        window._function_bar_link("settings:AAPL")
        assert window.stack.currentWidget().objectName() == "securitySettings"
    finally:
        window.close()
