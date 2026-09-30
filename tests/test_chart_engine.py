from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from ajax_terminal.analytics.chart_indicators import price_indicators
from ajax_terminal.analytics.volatility_surface import (
    black_scholes_delta,
    build_surface_grid,
    clean_vol_points,
    term_structure,
    volatility_snapshot,
)
from ajax_terminal.charts.models.curve import normalize_curve
from ajax_terminal.charts.models.ohlcv import normalize_ohlcv
from ajax_terminal.charts.models.volatility import VolPoint, VolSurface
from ajax_terminal.charts.renderers.echarts.renderer import EChartsRenderer
from ajax_terminal.charts.renderers.echarts.series import curve_option
from ajax_terminal.charts.renderers.lightweight.renderer import LightweightChartsRenderer
from ajax_terminal.charts.router import ChartType, RendererKind, renderer_for
from ajax_terminal.models.quote import (
    Curve,
    CurvePoint,
    DataQuality,
    PriceBar,
    PriceHistory,
)


def test_renderer_routing_uses_specialized_engines() -> None:
    assert renderer_for(ChartType.CANDLE) == RendererKind.LIGHTWEIGHT
    assert renderer_for(ChartType.CURVE) == RendererKind.ECHARTS
    assert renderer_for(ChartType.SKEW) == RendererKind.ECHARTS
    assert renderer_for(ChartType.VOL_SURFACE_3D) == RendererKind.PYVISTA


def test_ohlcv_normalization_sorts_deduplicates_and_calculates_indicators() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        PriceBar(now + timedelta(days=index), 100 + index, 102 + index, 99 + index, 101 + index, 1_000 + index)
        for index in range(60)
    ]
    history = PriceHistory("aapl", "1Y", "1d", [bars[2], *bars, bars[2]], "USD", "TEST", DataQuality.DELAYED)
    chart = normalize_ohlcv(history)
    assert chart.symbol == "AAPL"
    assert len(chart.points) == 60
    assert chart.points == sorted(chart.points, key=lambda item: item.timestamp)
    indicators = price_indicators(chart)
    assert len(indicators["sma20"]) == 41
    assert len(indicators["ema50"]) == 60
    assert len(indicators["vwap"]) == 60


def test_curve_normalization_sorts_by_years_and_builds_echarts_spec() -> None:
    curve = Curve(
        "usd",
        "USD curve",
        [CurvePoint("10Y", 10.0, 4.2), CurvePoint("2Y", 2.0, 3.9)],
        "TEST",
        DataQuality.DELAYED,
    )
    model = normalize_curve(curve)
    assert [point.tenor for point in model.points] == ["2Y", "10Y"]
    option = curve_option(model)
    assert option["xAxis"]["data"] == ["2Y", "10Y"]
    assert option["series"][0]["data"] == [3.9, 4.2]


def test_web_renderers_use_local_assets_and_required_attribution() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = PriceHistory(
        "AAPL",
        "1Y",
        "1d",
        [PriceBar(now, 100.0, 102.0, 99.0, 101.0, 10_000.0)],
        "USD",
        "TEST",
        DataQuality.DELAYED,
    )
    html = LightweightChartsRenderer().render(normalize_ohlcv(history))
    assert "lightweight-charts-5.2.1.min.js" in html
    assert "Charts by" in html and "tradingview.com" in html
    echart_html = EChartsRenderer().render({"series": []})
    assert "echarts-6.1.0.min.js" in echart_html
    assert "setOption" in echart_html


def test_vol_points_cleaning_grid_and_analytics_do_not_extrapolate() -> None:
    pytest.importorskip("scipy")
    today = date(2026, 1, 1)
    points: list[VolPoint] = []
    for tenor in (30, 90, 180):
        for moneyness in (0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2):
            option_type = "put" if moneyness < 1.0 else "call"
            delta = -(0.5 - (moneyness - 0.8)) if option_type == "put" else 0.5 - (moneyness - 1.0)
            points.append(
                VolPoint(
                    expiry=today + timedelta(days=tenor),
                    tenor_days=tenor,
                    strike=100.0 * moneyness,
                    moneyness=moneyness,
                    delta=delta,
                    iv=0.22 + (moneyness - 1.0) ** 2 + tenor / 10_000,
                    option_type=option_type,
                    volume=50,
                    open_interest=100,
                )
            )
    points.append(
        VolPoint(today + timedelta(days=90), 90, 100.0, 1.0, 0.5, 2.8, "call")
    )
    surface = VolSurface("TEST", 100.0, datetime.now(timezone.utc), "USD", "TEST", "DELAYED", points)
    cleaned = clean_vol_points(points)
    assert len(cleaned) < len(points)
    grid = build_surface_grid(surface, method="linear", moneyness_steps=19)
    assert grid.iv.shape == (3, 19)
    assert np.isfinite(grid.iv[:, 1:-1]).any()
    assert len(term_structure(surface)) == 3
    snapshot = volatility_snapshot(surface, 90)
    assert snapshot.atm_iv is not None


def test_black_scholes_delta_has_correct_sign() -> None:
    call = black_scholes_delta(100, 100, 1.0, 0.04, 0.01, 0.2, "call")
    put = black_scholes_delta(100, 100, 1.0, 0.04, 0.01, 0.2, "put")
    assert call is not None and 0 < call < 1
    assert put is not None and -1 < put < 0
    assert call - put == pytest.approx(np.exp(-0.01))
