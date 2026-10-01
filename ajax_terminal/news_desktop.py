from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from datetime import timezone
from time import monotonic

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_CYAN, AJAX_MUTED, AJAX_TEXT
from ajax_terminal.desktop_security import open_external_url
from ajax_terminal.models.news import NewsItem
from ajax_terminal.services.news_service import NewsService


TOPICS: tuple[tuple[str, str | None], ...] = (
    ("TOP", None),
    ("MARKETS", "MARKETS"),
    ("ECONOMY", "ECONOMY"),
    ("CBANK", "CENTRAL BANKS"),
    ("COMPANIES", "COMPANIES"),
    ("TECH", "TECH"),
    ("POLITICS", "POLITICS"),
)


@dataclass(slots=True)
class NewsLoad:
    topic: str
    items: list[NewsItem]


def load_news(topic: str = "") -> NewsLoad:
    service = NewsService()
    return NewsLoad(topic, asyncio.run(service.headlines(topic or None, limit=50)))


class NewsDesktopWorkspace(QWidget):
    command_requested = Signal(str)

    def __init__(self, loaded: NewsLoad) -> None:
        super().__init__()
        self.loaded = loaded
        self.items = loaded.items
        self._selected_row = 0
        self._last_open_url = ""
        self._last_opened_at = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(self._controls())

        heading = QLabel(self._heading())
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.table = self._table()
        splitter.addWidget(self.table)
        splitter.addWidget(self._detail_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([1120, 620])
        root.addWidget(splitter, 1)

        self.status = QLabel(self._status_text())
        self.status.setObjectName("metricsStrip")
        root.addWidget(self.status)

        if self.items:
            self.table.setCurrentCell(0, 0)
            self._show_story(0)
        else:
            self.open_button.setEnabled(False)
            self.detail.setText("NO VERIFIED HEADLINES AVAILABLE FOR THIS SEARCH.")

    def _controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("viewStrip")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        selected = (self.loaded.topic or "TOP").upper()
        for label, topic in TOPICS:
            button = QPushButton(label)
            button.setObjectName("functionTab")
            button.setCheckable(True)
            button.setChecked((topic or "TOP").upper() == selected)
            command = "NEWS" if topic is None else f"NEWS {topic}"
            button.clicked.connect(
                lambda _checked=False, value=command: self.command_requested.emit(value)
            )
            row.addWidget(button)
        row.addStretch(1)
        refresh = QPushButton("REFRESH")
        refresh.clicked.connect(lambda: self.command_requested.emit(self._command()))
        row.addWidget(refresh)
        self.open_button = QPushButton("OPEN STORY")
        self.open_button.setObjectName("amberField")
        self.open_button.clicked.connect(self._open_selected)
        row.addWidget(self.open_button)
        return frame

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(("#", "TIME", "SECTION", "SOURCE", "HEADLINE"))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(28)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.setRowCount(len(self.items))
        for row, story in enumerate(self.items):
            timestamp = story.timestamp.astimezone(timezone.utc)
            values = (
                f"{row + 1:02d}",
                timestamp.strftime("%H:%M"),
                story.category,
                story.source,
                story.headline,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor(AJAX_AMBER if column == 4 else AJAX_TEXT))
                if column == 4 and story.link:
                    font = QFont(item.font())
                    font.setUnderline(True)
                    item.setFont(font)
                    item.setToolTip("Open source article")
                table.setItem(row, column, item)
        table.cellClicked.connect(self._story_clicked)
        table.cellDoubleClicked.connect(self._open_story)
        table.itemActivated.connect(lambda item: self._open_story(item.row(), item.column()))
        return table

    def _detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("terminalPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title = QLabel("STORY DETAIL")
        title.setStyleSheet(f"color:{AJAX_CYAN};font-weight:bold")
        layout.addWidget(title)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setStyleSheet(
            "QTextBrowser { background:#030404; border:0px; padding:4px; }"
        )
        layout.addWidget(self.detail, 1)
        source = QPushButton("OPEN SOURCE")
        source.clicked.connect(self._open_selected)
        layout.addWidget(source)
        return panel

    def _heading(self) -> str:
        label = self.loaded.topic or "TOP STORIES"
        return f"NEWS  /  {label.upper()}  /  {len(self.items)} HEADLINES"

    def _command(self) -> str:
        return "NEWS" if not self.loaded.topic else f"NEWS {self.loaded.topic}"

    def _status_text(self) -> str:
        sources = len({item.source for item in self.items})
        quality = " / ".join(sorted({str(item.quality) for item in self.items})) or "UNAVAILABLE"
        return f"{len(self.items)} STORIES  |  {sources} SOURCES  |  {quality}  |  CLICK A ROW, USE OPEN STORY, OR PRESS ENTER"

    @Slot(int, int)
    def _story_clicked(self, row: int, column: int) -> None:
        self._show_story(row)
        self._open_story(row, column)

    def _show_story(self, row: int) -> None:
        if not 0 <= row < len(self.items):
            return
        self._selected_row = row
        story = self.items[row]
        timestamp = story.timestamp.astimezone(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
        summary = story.summary or "No synopsis supplied by the news provider."
        tags = " / ".join(story.tags) or "--"
        self.detail.setHtml(
            f"<p style='color:{AJAX_CYAN};font-weight:bold'>{_escape(story.category)} | {_escape(story.source)}</p>"
            f"<p style='color:{AJAX_MUTED}'>{timestamp} | {_escape(story.quality)}</p>"
            f"<p style='color:{AJAX_TEXT};font-weight:bold;font-size:15px'>{_escape(story.headline)}</p>"
            f"<p style='color:{AJAX_TEXT}'>{_escape(summary)}</p>"
            f"<p style='color:{AJAX_AMBER}'>TAGS&nbsp;&nbsp;{_escape(tags)}</p>"
        )
        self.open_button.setEnabled(bool(story.link.strip()))

    @Slot()
    def _open_selected(self) -> None:
        self._open_story(self._selected_row, 4)

    @Slot(int, int)
    def _open_story(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self.items):
            return
        self._show_story(row)
        story = self.items[row]
        link = story.link.strip()
        if not link:
            self.status.setText("SOURCE LINK UNAVAILABLE FOR THE SELECTED STORY")
            return
        now = monotonic()
        if link == self._last_open_url and now - self._last_opened_at < 0.75:
            return
        self._last_open_url = link
        self._last_opened_at = now
        try:
            opened = open_external_url(link)
        except (TypeError, ValueError) as exc:
            self.status.setText(f"SOURCE LINK REJECTED  |  {exc}")
            return
        self.status.setText(
            "SOURCE OPENED IN DEFAULT BROWSER" if opened else "WINDOWS COULD NOT OPEN THE SOURCE LINK"
        )


def _escape(value: object) -> str:
    return html.escape(str(value)).replace("\n", "<br>")
