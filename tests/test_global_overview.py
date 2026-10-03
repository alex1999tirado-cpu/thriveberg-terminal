from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ajax_terminal.desktop_app import (
    AjaxDesktopWindow,
    GlobalOverviewWindow,
    _GLOBAL_OVERVIEW_PANELS,
    _global_overview_commands,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_global_overview_defaults_and_rejects_recursive_commands(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "overview.ini"), QSettings.Format.IniFormat)
    defaults = tuple(command for _title, command in _GLOBAL_OVERVIEW_PANELS)

    assert _global_overview_commands(settings) == defaults

    settings.setValue("overview/commands", ["WALL", "wei", "govt", "news economy"])
    assert _global_overview_commands(settings) == (
        defaults[0],
        "WEI",
        "GOVT",
        "NEWS ECONOMY",
    )


def test_global_overview_builds_four_compact_quadrants(monkeypatch) -> None:
    app = _app()
    commands = tuple(command for _title, command in _GLOBAL_OVERVIEW_PANELS)
    started: list[str] = []
    monkeypatch.setattr(
        AjaxDesktopWindow,
        "start",
        lambda _self, initial_command=None: started.append(str(initial_command)),
    )
    wall = GlobalOverviewWindow(commands, app.primaryScreen())
    try:
        wall.resize(1600, 900)
        wall.show()
        app.processEvents()

        assert started == list(commands)
        assert len(wall.panels) == 4
        assert all(panel._compact_mode for panel in wall.panels)
        assert all(panel.system_bar.isHidden() for panel in wall.panels)
        assert all(panel.document_tabs.tabBar().isHidden() for panel in wall.panels)

        selected = wall.panels[2]
        wall._toggle_panel(selected)
        app.processEvents()
        assert wall._expanded_panel is selected
        assert selected.isVisible()
        assert sum(panel.isVisible() for panel in wall.panels) == 1

        wall._toggle_panel(selected)
        app.processEvents()
        assert wall._expanded_panel is None
        assert all(panel.isVisible() for panel in wall.panels)
    finally:
        wall.close()
        app.processEvents()


def test_wall_commands_persist_auto_open_preference(tmp_path, monkeypatch) -> None:
    _app()
    settings = QSettings(str(tmp_path / "wall-commands.ini"), QSettings.Format.IniFormat)
    window = AjaxDesktopWindow(require_login=False, settings=settings)
    opened: list[bool] = []
    monkeypatch.setattr(
        window,
        "open_global_overview",
        lambda *, force=False: opened.append(force),
    )
    try:
        window.execute_text("WALL OFF")
        assert not settings.value("overview/enabled", True, type=bool)

        window.execute_text("WALL ON")
        assert settings.value("overview/enabled", False, type=bool)
        assert opened == [True]

        settings.setValue("overview/commands", ["FX", "MARKETS", "CURVE USD", "NEWS ECONOMY"])
        window.execute_text("WALL RESET")
        assert settings.value("overview/commands") == [
            command for _title, command in _GLOBAL_OVERVIEW_PANELS
        ]
        assert opened == [True, True]
    finally:
        window.close()

