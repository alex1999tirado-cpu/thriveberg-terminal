from __future__ import annotations

from ajax_terminal.charts.theme import (
    AJAX_AMBER,
    AJAX_BACKGROUND,
    AJAX_BORDER,
    AJAX_CYAN,
    AJAX_GREEN,
    AJAX_GRID,
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
)


def base_option(title: str = "") -> dict[str, object]:
    return {
        "backgroundColor": AJAX_BACKGROUND,
        "animation": False,
        "textStyle": {"fontFamily": "Consolas, monospace", "fontSize": 13, "color": AJAX_TEXT},
        "title": {"text": title, "left": 8, "top": 5, "textStyle": {"color": AJAX_AMBER, "fontSize": 15}},
        "color": [AJAX_AMBER, AJAX_TEXT, AJAX_CYAN, AJAX_GREEN, AJAX_RED],
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "#111417",
            "borderColor": AJAX_BORDER,
            "textStyle": {"color": AJAX_TEXT, "fontFamily": "Consolas, monospace", "fontSize": 13},
            "axisPointer": {"type": "cross", "lineStyle": {"color": AJAX_MUTED}},
        },
        "legend": {"top": 6, "right": 8, "textStyle": {"color": AJAX_TEXT}},
        "grid": {"left": 58, "right": 22, "top": 48, "bottom": 42, "containLabel": False},
        "xAxis": {
            "type": "category",
            "axisLine": {"lineStyle": {"color": AJAX_BORDER}},
            "axisTick": {"lineStyle": {"color": AJAX_BORDER}},
            "axisLabel": {"color": AJAX_TEXT},
            "splitLine": {"show": True, "lineStyle": {"color": AJAX_GRID, "type": "dashed", "width": 1}},
        },
        "yAxis": {
            "type": "value",
            "scale": True,
            "axisLine": {"show": True, "lineStyle": {"color": AJAX_BORDER}},
            "axisLabel": {"color": AJAX_TEXT},
            "splitLine": {"show": True, "lineStyle": {"color": AJAX_GRID, "type": "dashed", "width": 1}},
        },
    }
