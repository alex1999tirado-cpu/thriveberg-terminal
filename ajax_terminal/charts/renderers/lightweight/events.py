from __future__ import annotations

from datetime import datetime, timezone

from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_RED


def event_marker(timestamp: datetime, label: str, *, positive: bool = True) -> dict[str, object]:
    value = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    return {
        "time": int(value.timestamp()),
        "position": "belowBar" if positive else "aboveBar",
        "color": AJAX_AMBER if positive else AJAX_RED,
        "shape": "arrowUp" if positive else "arrowDown",
        "text": label[:16],
    }
