from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from ajax_terminal.desktop_app import AjaxDesktopWindow, resolve_desktop_command
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.news_desktop import NewsDesktopWorkspace, NewsLoad


def _story() -> NewsItem:
    return NewsItem(
        timestamp=datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc),
        source="TEST WIRE",
        headline="Corteva announces quarterly results",
        link="https://example.com/ctva-results",
        tags=["CTVA", "EARNINGS"],
        summary="Revenue and guidance were published.",
        provider="TEST",
        quality=DataQuality.DELAYED,
        category="EQUITIES",
    )


def test_news_routes_to_native_workspace() -> None:
    route = resolve_desktop_command("NEWS CTVA", "CTVA")
    assert route.kind == "news"
    assert route.target == "CTVA"


def test_clicking_amber_headline_opens_source(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(
        "ajax_terminal.news_desktop.open_external_url",
        lambda url: opened.append(str(url)) or True,
    )
    workspace = NewsDesktopWorkspace(NewsLoad("CTVA", [_story()]))
    workspace.resize(1200, 700)
    workspace.show()
    app.processEvents()
    try:
        headline = workspace.table.item(0, 4)
        rect = workspace.table.visualItemRect(headline)
        assert rect.isValid()
        QTest.mouseClick(
            workspace.table.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            rect.center(),
        )
        app.processEvents()
        assert opened == ["https://example.com/ctva-results"]
        assert "SOURCE OPENED" in workspace.status.text()
    finally:
        workspace.close()


def test_repeated_click_signal_does_not_open_duplicate_tabs(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(
        "ajax_terminal.news_desktop.open_external_url",
        lambda url: opened.append(str(url)) or True,
    )
    workspace = NewsDesktopWorkspace(NewsLoad("CTVA", [_story()]))
    try:
        workspace._open_story(0, 4)
        workspace._open_story(0, 4)
        assert opened == ["https://example.com/ctva-results"]
    finally:
        workspace.close()


def test_news_topic_buttons_emit_real_commands() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = NewsDesktopWorkspace(NewsLoad("CTVA", [_story()]))
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    workspace.show()
    app.processEvents()
    try:
        markets = next(
            button
            for button in workspace.findChildren(QPushButton)
            if button.text() == "MARKETS"
        )
        QTest.mouseClick(markets, Qt.MouseButton.LeftButton)
        assert commands == ["NEWS MARKETS"]
    finally:
        workspace.close()


def test_desktop_mounts_news_as_interactive_qt(monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "news.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    monkeypatch.setattr(window, "_load_workspace", lambda _engine, _loader, mount: mount(NewsLoad("CTVA", [_story()])))
    try:
        window.execute_text("NEWS CTVA")
        app.processEvents()
        assert isinstance(window.stack.currentWidget(), NewsDesktopWorkspace)
        assert "NATIVE QT" in window.engine_label.text()
    finally:
        window.close()
