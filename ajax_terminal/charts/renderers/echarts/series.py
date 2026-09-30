from __future__ import annotations

from ajax_terminal.analytics.volatility_surface import skew_for_tenor, term_structure
from ajax_terminal.charts.models.curve import CurveChart
from ajax_terminal.charts.models.volatility import VolSurface
from ajax_terminal.charts.renderers.echarts.theme import base_option
from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_CYAN, AJAX_GREEN, AJAX_RED


def curve_option(curve: CurveChart) -> dict[str, object]:
    option = base_option(curve.name.upper())
    option["xAxis"] = {
        **option["xAxis"],
        "name": "TENOR",
        "nameTextStyle": {"color": AJAX_AMBER},
        "data": [point.tenor for point in curve.points],
    }
    option["yAxis"] = {
        **option["yAxis"],
        "name": "YIELD %",
        "nameTextStyle": {"color": AJAX_AMBER},
        "axisLabel": {"color": "#e6e8ea", "formatter": "{value}%"},
    }
    option["series"] = [
        {
            "name": "YIELD",
            "type": "line",
            "data": [point.yield_pct for point in curve.points],
            "symbol": "diamond",
            "symbolSize": 7,
            "smooth": 0.18,
            "lineStyle": {"color": AJAX_AMBER, "width": 2},
            "itemStyle": {"color": AJAX_AMBER},
            "areaStyle": None,
        }
    ]
    return option


def term_structure_option(surface: VolSurface) -> dict[str, object]:
    values = term_structure(surface)
    option = base_option("VOLATILITY VS. TERM")
    option["title"] = {"show": False}
    option["legend"] = {"top": 3, "right": 8, "textStyle": {"color": "#d7d7d7", "fontSize": 9}}
    option["grid"] = {"left": 48, "right": 16, "top": 28, "bottom": 34}
    option["xAxis"] = {**option["xAxis"], "name": "DAYS", "data": [str(days) for days, _ in values]}
    option["yAxis"] = {**option["yAxis"], "name": "IV %"}
    option["series"] = [{
        "name": "ATM IV",
        "type": "line",
        "data": [iv for _, iv in values],
        "symbol": "diamond",
        "symbolSize": 6,
        "lineStyle": {"color": AJAX_RED, "width": 2},
        "itemStyle": {"color": AJAX_RED},
    }]
    return option


def skew_option(surface: VolSurface, tenor_days: int) -> dict[str, object]:
    values = skew_for_tenor(surface, tenor_days)
    option = base_option("MONEYNESS")
    option["title"] = {"show": False}
    option["legend"] = {"show": False}
    option["grid"] = {"left": 48, "right": 16, "top": 20, "bottom": 36}
    option["xAxis"] = {
        **option["xAxis"],
        "name": "STRIKE / SPOT %",
        "data": [f"{point.moneyness * 100:.1f}" for point in values],
    }
    option["yAxis"] = {**option["yAxis"], "name": "IV %"}
    option["series"] = [{
        "name": f"{tenor_days}D",
        "type": "line",
        "data": [point.iv * 100.0 for point in values],
        "symbol": "diamond",
        "symbolSize": 5,
        "smooth": 0.12,
        "lineStyle": {"color": AJAX_RED, "width": 2},
        "itemStyle": {"color": AJAX_RED},
        "markLine": {
            "silent": True,
            "symbol": "none",
            "lineStyle": {"color": AJAX_CYAN, "width": 1, "type": "dashed"},
            "data": [{"xAxis": "100.0"}],
        },
    }]
    return option
