from __future__ import annotations

from enum import StrEnum


class ChartType(StrEnum):
    PRICE = "PRICE"
    CANDLE = "CANDLE"
    OHLC = "OHLC"
    INTRADAY = "INTRADAY"
    LINE_ANALYTICS = "LINE_ANALYTICS"
    CURVE = "CURVE"
    MACRO = "MACRO"
    HISTOGRAM = "HISTOGRAM"
    HEATMAP = "HEATMAP"
    SKEW = "SKEW"
    VOL_TERM_STRUCTURE = "VOL_TERM_STRUCTURE"
    DRAWDOWN = "DRAWDOWN"
    VOL_SURFACE_3D = "VOL_SURFACE_3D"


class RendererKind(StrEnum):
    LIGHTWEIGHT = "LIGHTWEIGHT_CHARTS"
    ECHARTS = "APACHE_ECHARTS"
    PYVISTA = "PYVISTA_VTK"


_LIGHTWEIGHT_TYPES = {
    ChartType.PRICE,
    ChartType.CANDLE,
    ChartType.OHLC,
    ChartType.INTRADAY,
}
_ECHARTS_TYPES = {
    ChartType.LINE_ANALYTICS,
    ChartType.CURVE,
    ChartType.MACRO,
    ChartType.HISTOGRAM,
    ChartType.HEATMAP,
    ChartType.SKEW,
    ChartType.VOL_TERM_STRUCTURE,
    ChartType.DRAWDOWN,
}


def renderer_for(chart_type: ChartType | str) -> RendererKind:
    kind = chart_type if isinstance(chart_type, ChartType) else ChartType(str(chart_type).upper())
    if kind in _LIGHTWEIGHT_TYPES:
        return RendererKind.LIGHTWEIGHT
    if kind in _ECHARTS_TYPES:
        return RendererKind.ECHARTS
    if kind == ChartType.VOL_SURFACE_3D:
        return RendererKind.PYVISTA
    raise ValueError(f"No renderer is registered for {kind}")
