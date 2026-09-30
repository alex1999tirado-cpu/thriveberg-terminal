from __future__ import annotations

from ajax_terminal.charts.theme import (
    AJAX_AMBER,
    AJAX_BACKGROUND,
    AJAX_GRID,
    AJAX_GREEN,
    AJAX_MUTED,
    AJAX_RED,
    AJAX_TEXT,
)


def chart_options() -> dict[str, object]:
    return {
        "autoSize": True,
        "layout": {
            "background": {"type": "solid", "color": AJAX_BACKGROUND},
            "textColor": "#b9bec3",
            "fontFamily": "Consolas, monospace",
            "fontSize": 13,
            "attributionLogo": True,
        },
        "grid": {
            "vertLines": {"color": "#202428", "style": 1},
            "horzLines": {"color": "#202428", "style": 1},
        },
        "crosshair": {
            "mode": 0,
            "vertLine": {"color": AJAX_MUTED, "width": 1, "labelBackgroundColor": "#31363b"},
            "horzLine": {"color": AJAX_MUTED, "width": 1, "labelBackgroundColor": "#31363b"},
        },
        "rightPriceScale": {
            "borderColor": "#4a5158",
            "scaleMargins": {"top": 0.08, "bottom": 0.24},
        },
        "timeScale": {
            "borderColor": "#4a5158",
            "timeVisible": True,
            "secondsVisible": False,
            "rightOffset": 4,
            "barSpacing": 7,
        },
        "handleScroll": True,
        "handleScale": True,
    }


SERIES_COLORS = {
    "up": AJAX_GREEN,
    "down": AJAX_RED,
    "sma20": AJAX_AMBER,
    "ema50": "#27b8e6",
    "vwap": "#e6e8ea",
}
