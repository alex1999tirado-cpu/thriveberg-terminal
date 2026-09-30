from __future__ import annotations

import asyncio
import html
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.models.social import FriendConnection, FriendshipStatus, SocialUser
from ajax_terminal.services.social_service import SocialService


class AsyncOperation(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            result = self.operation()
            if hasattr(result, "__await__"):
                result = asyncio.run(result)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class SocialDesktopWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, service: SocialService, command_provider: Callable[[], str]) -> None:
        super().__init__()
        self.service = service
        self.command_provider = command_provider
        self.connections: list[FriendConnection] = []
        self.search_results: list[SocialUser] = []
        self.selected_connection: FriendConnection | None = None
        self._worker: AsyncOperation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(3)
        header = QLabel("SOCIAL  |  PRIVATE MESSAGING  |  CONTACTS")
        header.setObjectName("functionBar")
        root.addWidget(header)
        self.identity = QLabel("AUTHENTICATION REQUIRED")
        self.identity.setObjectName("instrumentBar")
        root.addWidget(self.identity)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._directory_panel())
        splitter.addWidget(self._conversation_panel())
        splitter.setSizes([560, 1260])
        root.addWidget(splitter, 1)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(10_000)
        self.poll_timer.timeout.connect(self.refresh_connections)

    def _directory_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("terminalPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(3)

        title = QLabel("CONTACTS / REQUESTS")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("SEARCH USERNAME")
        self.search.returnPressed.connect(self.search_users)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(_command_button("SEARCH", self.search_users))
        search_row.addWidget(_command_button("REFRESH", self.refresh_connections))
        layout.addLayout(search_row)

        self.people = QTableWidget(0, 3)
        self.people.setHorizontalHeaderLabels(["USERNAME", "NAME", "STATUS"])
        self.people.horizontalHeader().setStretchLastSection(True)
        self.people.verticalHeader().hide()
        self.people.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.people.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.people.itemSelectionChanged.connect(self._selection_changed)
        self.people.itemDoubleClicked.connect(lambda _item: self._open_selected())
        layout.addWidget(self.people, 1)

        actions = QHBoxLayout()
        self.add_button = _command_button("ADD", self.add_selected)
        self.accept_button = _command_button("ACCEPT", lambda: self.respond_selected(True))
        self.reject_button = _command_button("REJECT", lambda: self.respond_selected(False))
        self.open_button = _command_button("OPEN CHAT", self._open_selected)
        actions.addWidget(self.add_button)
        actions.addWidget(self.accept_button)
        actions.addWidget(self.reject_button)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        return panel

    def _conversation_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("terminalPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(3)

        self.chat_title = QLabel("DIRECT MESSAGE  |  SELECT A CONTACT")
        self.chat_title.setObjectName("sectionTitle")
        layout.addWidget(self.chat_title)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("socialTranscript")
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self._command_link_clicked)
        layout.addWidget(self.transcript, 1)

        compose = QHBoxLayout()
        self.message = QLineEdit()
        self.message.setPlaceholderText("MESSAGE")
        self.message.returnPressed.connect(self.send_message)
        self.attach_command = QCheckBox("ATTACH ACTIVE COMMAND")
        compose.addWidget(self.message, 1)
        compose.addWidget(self.attach_command)
        compose.addWidget(_command_button("SEND", self.send_message))
        layout.addLayout(compose)
        self.status = QLabel("READY")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        return panel

    def activate(self) -> None:
        session = self.service.session
        if session is None:
            self.identity.setText("AUTHENTICATION REQUIRED")
            self.poll_timer.stop()
            return
        self.identity.setText(
            f"@{session.username.upper()}   |   {session.display_name.upper()}   |   {session.email}   |   CONNECTED"
        )
        self.poll_timer.start()
        self.refresh_connections()

    def refresh_connections(self) -> None:
        if not self.service.signed_in or self._worker is not None:
            return
        self._run(self.service.connections, self._connections_loaded, "UPDATING CONTACTS")

    def search_users(self) -> None:
        query = self.search.text().strip()
        if not query or self._worker is not None:
            return
        self._run(lambda: self.service.search_users(query), self._search_loaded, "SEARCHING DIRECTORY")

    def add_selected(self) -> None:
        user = self._selected_search_user()
        if user is None or self._worker is not None:
            return
        self._run(
            lambda: self.service.send_friend_request(user),
            lambda _result: self.refresh_connections(),
            f"SENDING REQUEST TO @{user.username.upper()}",
        )

    def respond_selected(self, accept: bool) -> None:
        connection = self._selected_connection_row()
        if connection is None or connection.friendship != FriendshipStatus.INCOMING or self._worker is not None:
            return
        self._run(
            lambda: self.service.respond_to_request(connection.request_id, accept),
            lambda _result: self.refresh_connections(),
            "UPDATING REQUEST",
        )

    def send_message(self) -> None:
        connection = self.selected_connection
        if connection is None or connection.friendship != FriendshipStatus.FRIENDS or self._worker is not None:
            self.status.setText("SELECT AN ACCEPTED CONTACT")
            return
        body = self.message.text().strip()
        shared = self.command_provider().strip() if self.attach_command.isChecked() else ""
        if not body and not shared:
            return
        self._run(
            lambda: self.service.send_message(connection.user, body, shared),
            lambda _result: self._message_sent(),
            "SENDING MESSAGE",
        )

    def _open_selected(self) -> None:
        connection = self._selected_connection_row()
        if connection is None or connection.friendship != FriendshipStatus.FRIENDS:
            return
        self.selected_connection = connection
        self.chat_title.setText(
            f"DIRECT MESSAGE  |  @{connection.user.username.upper()}  |  {connection.user.display_name.upper()}"
        )
        self._load_messages()

    def _load_messages(self) -> None:
        connection = self.selected_connection
        if connection is None or self._worker is not None:
            return
        self._run(
            lambda: self.service.messages(connection.user),
            self._messages_loaded,
            f"LOADING @{connection.user.username.upper()}",
        )

    def _connections_loaded(self, result: object) -> None:
        self.connections = list(result)
        self.search_results = []
        self._populate_people(
            [
                (item.user, item.friendship.value)
                for item in self.connections
            ]
        )
        self.status.setText(f"{len(self.connections)} CONTACTS / REQUESTS")
        if self.selected_connection is not None:
            QTimer.singleShot(0, self._load_messages)

    def _search_loaded(self, result: object) -> None:
        self.search_results = list(result)
        self._populate_people([(user, user.friendship.value) for user in self.search_results])
        self.status.setText(f"{len(self.search_results)} DIRECTORY RESULTS")

    def _populate_people(self, rows: list[tuple[SocialUser, str]]) -> None:
        self.people.setRowCount(len(rows))
        for row, (user, status) in enumerate(rows):
            self.people.setItem(row, 0, QTableWidgetItem(f"@{user.username}"))
            self.people.setItem(row, 1, QTableWidgetItem(user.display_name))
            self.people.setItem(row, 2, QTableWidgetItem(status))
        self.people.resizeColumnsToContents()
        self._selection_changed()

    def _messages_loaded(self, result: object) -> None:
        connection = self.selected_connection
        if connection is None:
            return
        session = self.service.session
        parts = ["<html><body style='background:#030404;color:#d7d7d7;font-family:monospace'>"]
        for message in list(result):
            mine = session is not None and message.sender_id == session.user_id
            author = "YOU" if mine else f"@{connection.user.username.upper()}"
            color = "#d7d7d7" if mine else "#ffb000"
            stamp = message.created_at.astimezone().strftime("%d %b %H:%M") if isinstance(message.created_at, datetime) else ""
            parts.append(f"<p><span style='color:#8f99a3'>{stamp}</span> <b style='color:{color}'>{author}</b><br>")
            if message.body:
                parts.append(f"{html.escape(message.body)}<br>")
            if message.shared_command:
                encoded = quote(message.shared_command)
                parts.append(
                    f"<a style='color:#ffb000' href='ajax-command:{encoded}'>OPEN {html.escape(message.shared_command)}</a>"
                )
            parts.append("</p>")
        parts.append("</body></html>")
        self.transcript.setHtml("".join(parts))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())
        self.status.setText("CONNECTED")

    def _message_sent(self) -> None:
        self.message.clear()
        self.attach_command.setChecked(False)
        QTimer.singleShot(0, self._load_messages)

    def _selection_changed(self) -> None:
        connection = self._selected_connection_row()
        user = self._selected_search_user()
        self.add_button.setEnabled(user is not None and user.friendship == FriendshipStatus.NONE)
        self.accept_button.setEnabled(connection is not None and connection.friendship == FriendshipStatus.INCOMING)
        self.reject_button.setEnabled(connection is not None and connection.friendship == FriendshipStatus.INCOMING)
        self.open_button.setEnabled(connection is not None and connection.friendship == FriendshipStatus.FRIENDS)

    def _selected_connection_row(self) -> FriendConnection | None:
        row = self.people.currentRow()
        if self.search_results or row < 0 or row >= len(self.connections):
            return None
        return self.connections[row]

    def _selected_search_user(self) -> SocialUser | None:
        row = self.people.currentRow()
        if not self.search_results or row < 0 or row >= len(self.search_results):
            return None
        return self.search_results[row]

    def _command_link_clicked(self, url: QUrl) -> None:
        value = url.toString()
        if value.startswith("ajax-command:"):
            self.command_requested.emit(unquote(value.removeprefix("ajax-command:")))

    def _run(self, operation: Callable[[], Any], callback: Callable[[object], None], status: str) -> None:
        if self._worker is not None:
            return
        self.status.setText(status)
        worker = AsyncOperation(operation)
        self._worker = worker
        worker.succeeded.connect(callback, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._operation_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._operation_finished, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @Slot()
    def _operation_finished(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._worker = None

    @Slot(str)
    def _operation_failed(self, message: str) -> None:
        self.status.setText(message.upper())


def _command_button(label: str, callback: Callable[[], None]) -> QPushButton:
    button = QPushButton(label)
    button.clicked.connect(callback)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button
