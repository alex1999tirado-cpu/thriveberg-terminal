from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ajax_terminal.desktop_app import AjaxDesktopWindow
from ajax_terminal.models.social import SocialSession


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qt_app: QApplication, tmp_path) -> AjaxDesktopWindow:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    terminal = AjaxDesktopWindow(require_login=True, settings=settings)
    yield terminal
    terminal.close()


def _session() -> SocialSession:
    return SocialSession(
        user_id="user-1",
        email="analyst@example.com",
        username="analyst",
        display_name="Analyst",
        access_token="token",
    )


def test_login_opens_as_a_compact_centered_window(
    window: AjaxDesktopWindow,
    qt_app: QApplication,
) -> None:
    window.show()
    window._show_login()
    qt_app.processEvents()

    available = window.screen().availableGeometry()
    assert window.size().width() == 1000
    assert window.size().height() == 660
    assert not window.isMaximized()
    assert abs(window.frameGeometry().center().x() - available.center().x()) <= 1
    assert abs(window.frameGeometry().center().y() - available.center().y()) <= 1


def test_login_accepts_at_sign_from_altgr_layouts(
    window: AjaxDesktopWindow,
    qt_app: QApplication,
) -> None:
    window.show()
    window._show_login()
    window.auth_email.clear()
    window.auth_email.setFocus()
    qt_app.processEvents()

    modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_2, modifiers, "@")
    QApplication.sendEvent(window.auth_email, event)

    assert window.auth_email.text() == "@"
    assert all(
        shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        and shortcut.parent() is window.workspace_tabs
        for shortcut in window._workspace_shortcuts
    )


def test_login_rejects_empty_credentials(window: AjaxDesktopWindow) -> None:
    window._submit_auth()

    assert window.auth_status.text() == "EMAIL AND PASSWORD ARE REQUIRED"
    assert window._auth_worker is None


def test_registration_rejects_mismatched_passwords(window: AjaxDesktopWindow) -> None:
    window._set_auth_mode("register")
    window.auth_email.setText("analyst@example.com")
    window.auth_username.setText("analyst")
    window.auth_password.setText("password-one")
    window.auth_confirm.setText("password-two")

    window._submit_auth()

    assert window.auth_status.text() == "PASSWORDS DO NOT MATCH"
    assert window._auth_worker is None


def test_successful_login_starts_terminal_boot_sequence(window: AjaxDesktopWindow) -> None:
    window.auth_email.setText("analyst@example.com")
    window._auth_succeeded(_session())

    assert window._authenticated is True
    assert window.lifecycle.currentWidget() is window.splash_page
    assert window.user_label.text() == "@ANALYST"
    assert window.settings.value("login/name") == "analyst@example.com"


def test_logout_returns_to_login(window: AjaxDesktopWindow) -> None:
    window._authenticated = True
    window.social_service.provider = None
    window.social_service.session = _session()

    window.logout()

    assert window._authenticated is False
    assert window.social_service.session is None
    assert window.lifecycle.currentWidget() is window.auth_page
    assert window.user_label.text() == "SIGNED OUT"


def test_login_worker_is_retained_until_qthread_finishes(
    window: AjaxDesktopWindow,
    qt_app: QApplication,
) -> None:
    window.social_service.sign_in = lambda _email, _password: _session()  # type: ignore[method-assign]
    window.auth_email.setText("analyst@example.com")
    window.auth_password.setText("password")

    window._submit_auth()
    worker = window._auth_worker

    assert worker is not None
    assert worker.wait(2_000)
    qt_app.processEvents()
    assert window._auth_worker is None
    assert window._authenticated is True


def test_language_selection_is_persisted(window: AjaxDesktopWindow) -> None:
    window._select_language("Español")

    assert window.settings.value("login/language") == "Español"
    assert window._language_buttons["Español"].isChecked()
    assert window._language_buttons["Español"].text().startswith("✓")
