from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Static

from ajax_terminal.models.news import NewsItem


TOPICS: tuple[tuple[str, str | None], ...] = (
    ("TOP", None),
    ("MARKETS", "MARKETS"),
    ("ECONOMY", "ECONOMY"),
    ("CBANK", "CENTRAL BANKS"),
    ("COMPANIES", "COMPANIES"),
    ("TECH", "TECH"),
    ("POLITICS", "POLITICS"),
)


class NewsWorkspace(Vertical):
    can_focus = True

    BINDINGS = [
        ("r", "refresh_news", "Refresh"),
        ("o", "open_story", "Open story"),
        Binding("j", "next_story", "Next story", priority=True),
        Binding("k", "previous_story", "Previous story", priority=True),
    ]

    class TopicRequested(Message):
        def __init__(self, topic: str | None) -> None:
            self.topic = topic
            super().__init__()

    class RefreshRequested(Message):
        pass

    class OpenRequested(Message):
        def __init__(self, item: NewsItem) -> None:
            self.item = item
            super().__init__()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.items: list[NewsItem] = []
        self.topic: str | None = None
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="news-topic-row"):
            for label, _topic in TOPICS:
                yield Button(label, id=f"news-topic-{label.lower()}", classes="news-topic")
            yield Button("OPEN", id="news-open", classes="news-action")
            yield Button("REFRESH", id="news-refresh", classes="news-action")
        yield Static("WAITING FOR NEWS WIRE", id="news-wire")
        with Horizontal(id="news-body"):
            yield DataTable(id="news-table")
            yield Static("Select a headline", id="news-detail")

    def on_mount(self) -> None:
        table = self.query_one("#news-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_column("#", width=2, key="number")
        table.add_column("TIME", width=5, key="time")
        table.add_column("SECTION", width=8, key="section")
        table.add_column("SOURCE", width=12, key="source")
        table.add_column("HEADLINE", width=38, key="headline")
        self._select_topic_button()
        self.call_after_refresh(self.sync_responsive_layout)

    def on_resize(self, event: events.Resize) -> None:
        self.sync_responsive_layout(event.size.width)

    def on_show(self, _event: events.Show) -> None:
        self.call_after_refresh(self.sync_responsive_layout)

    def sync_responsive_layout(self, width: int | None = None) -> None:
        available_width = self.size.width if width is None else width
        detail = self.query_one("#news-detail", Static)
        detail.display = available_width >= 105
        for label in ("companies", "tech", "politics"):
            self.query_one(f"#news-topic-{label}", Button).display = available_width >= 92

    def set_loading(self, topic: str | None) -> None:
        self.topic = topic
        label = (topic or "TOP STORIES").upper()
        self.query_one("#news-wire", Static).update(
            f"NEWS | {label} | CONNECTING TO NEWS PROVIDERS"
        )
        self._select_topic_button()

    def set_items(self, items: list[NewsItem], topic: str | None = None) -> None:
        self.items = list(items)
        self.topic = topic
        self.selected_index = 0
        table = self.query_one("#news-table", DataTable)
        table.clear()
        now = datetime.now(timezone.utc)
        for index, item in enumerate(self.items):
            time_text = item.timestamp.astimezone(timezone.utc).strftime("%H:%M")
            if item.timestamp.astimezone(timezone.utc).date() != now.date():
                time_text = item.timestamp.astimezone(timezone.utc).strftime("%d %b")
            table.add_row(
                f"{index + 1:02d}",
                time_text,
                _short_category(item.category),
                item.source[:12],
                item.headline,
                key=f"story-{index}",
            )
        if self.items:
            table.move_cursor(row=0, column=0, animate=False)
            self._update_detail(0)
        else:
            self.query_one("#news-detail", Static).update("No stories available")

        topic_label = (topic or "TOP STORIES").upper()
        qualities = sorted({str(item.quality) for item in self.items}) or ["UNAVAILABLE"]
        sources = {item.source for item in self.items}
        categories = Counter(item.category for item in self.items)
        leading = categories.most_common(1)[0][0] if categories else "--"
        quality_label = qualities[0] if len(qualities) == 1 else "MIXED"
        self.query_one("#news-wire", Static).update(
            f"NEWS | {topic_label} | {len(self.items)} STORIES | {len(sources)} SOURCES | "
            f"LEAD {leading} | {quality_label} | UPDATED {now:%H:%M:%S} UTC"
        )
        self._select_topic_button()
        self.call_after_refresh(self.sync_responsive_layout)

    def focus_table(self) -> None:
        self.query_one("#news-table", DataTable).focus()

    @on(DataTable.RowHighlighted, "#news-table")
    def story_highlighted(self, event: DataTable.RowHighlighted) -> None:
        index = _row_index(event.row_key.value)
        if index is not None:
            self._update_detail(index)

    @on(DataTable.RowSelected, "#news-table")
    def story_selected(self, event: DataTable.RowSelected) -> None:
        index = _row_index(event.row_key.value)
        if index is not None:
            self._request_open(index)

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "news-refresh":
            self.post_message(self.RefreshRequested())
            return
        if button_id == "news-open":
            self._request_open(self.selected_index)
            return
        if not button_id.startswith("news-topic-"):
            return
        selected = button_id.removeprefix("news-topic-").upper()
        topic_by_label = dict(TOPICS)
        self.post_message(self.TopicRequested(topic_by_label.get(selected)))

    def action_refresh_news(self) -> None:
        self.post_message(self.RefreshRequested())

    def action_open_story(self) -> None:
        self._request_open(self.selected_index)

    def action_next_story(self) -> None:
        self._move_selection(1)

    def action_previous_story(self) -> None:
        self._move_selection(-1)

    def _move_selection(self, amount: int) -> None:
        if not self.items:
            return
        next_index = max(0, min(self.selected_index + amount, len(self.items) - 1))
        self.query_one("#news-table", DataTable).move_cursor(row=next_index, column=0, animate=False)
        self._update_detail(next_index)

    def _update_detail(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        self.selected_index = index
        item = self.items[index]
        timestamp = item.timestamp.astimezone(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
        detail = Text()
        detail.append(f"STORY {index + 1:02d} / {len(self.items):02d}\n", style="bold bright_white")
        detail.append(f"{item.category}  |  {item.source}\n", style="bold cyan")
        detail.append(f"{timestamp}  |  {item.quality}\n\n", style="dim")
        detail.append(item.headline, style="bold white")
        detail.append("\n\n")
        detail.append(item.summary or "No synopsis supplied by the news provider.", style="white")
        if item.tags:
            detail.append("\n\nTAGS  ", style="bold yellow")
            detail.append(" / ".join(item.tags), style="cyan")
        if item.link:
            detail.append("\n\nSOURCE LINK AVAILABLE", style="bold green")
        self.query_one("#news-detail", Static).update(detail)

    def _request_open(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.post_message(self.OpenRequested(self.items[index]))

    def _select_topic_button(self) -> None:
        selected_topic = (self.topic or "TOP").upper()
        for label, topic in TOPICS:
            button = self.query_one(f"#news-topic-{label.lower()}", Button)
            button.set_class((topic or "TOP").upper() == selected_topic, "selected")


def _row_index(value: object) -> int | None:
    text = str(value)
    if not text.startswith("story-"):
        return None
    try:
        return int(text.removeprefix("story-"))
    except ValueError:
        return None


def _short_category(category: str) -> str:
    return {
        "CENTRAL BANKS": "CBANK",
        "COMMODITIES": "CMDTY",
        "EQUITIES": "EQUITY",
        "POLITICS": "POLITICS",
    }.get(category.upper(), category.upper())[:9]
