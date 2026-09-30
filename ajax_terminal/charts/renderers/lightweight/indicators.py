from __future__ import annotations

from ajax_terminal.analytics.chart_indicators import price_indicators
from ajax_terminal.charts.models.ohlcv import OHLCVChart


def attach_default_indicators(chart: OHLCVChart) -> OHLCVChart:
    chart.indicators = price_indicators(chart)
    return chart
