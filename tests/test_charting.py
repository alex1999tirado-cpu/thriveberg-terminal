from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache
from ajax_terminal.ui.chart_window import CHART_STUDIES, CHART_TYPES, build_chart_figure, build_chart_image, history_to_frame
from ajax_terminal.utils.periods import chart_intervals_for_period, normalize_history_interval


def _history(symbol: str = "AAPL", period: str = "5D", interval: str = "15m") -> PriceHistory:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        PriceBar(
            timestamp=start + timedelta(minutes=15 * index),
            open=100.0 + index * 0.2,
            high=101.0 + index * 0.2,
            low=99.5 + index * 0.2,
            close=100.5 + index * 0.2,
            volume=1_000_000 + index * 10_000,
        )
        for index in range(60)
    ]
    return PriceHistory(symbol, period, interval, bars, "USD", "TEST PROVIDER", DataQuality.MOCK)


def test_chart_interval_selection_respects_provider_ranges() -> None:
    assert chart_intervals_for_period("1D") == ("1m", "5m", "15m", "30m", "60m")
    assert normalize_history_interval("5D", "15M") == "15m"
    assert normalize_history_interval("1Y", "1H") == "1d"
    assert normalize_history_interval("5Y", "1W") == "1wk"
    assert CHART_STUDIES["vwap"].implemented
    assert CHART_STUDIES["rsi"].placement == "lower_panel"
    assert not CHART_STUDIES["macd"].implemented


def test_candlestick_figure_keeps_metadata_outside_the_plot() -> None:
    history = _history()
    frame = history_to_frame(history)
    figure = build_chart_figure(history)

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(figure.axes) >= 2
    assert figure._suptitle is None
    assert not figure.texts
    positions = [axis.get_position() for axis in figure.axes]
    assert min(position.x0 for position in positions) <= 0.07
    assert max(position.x1 for position in positions) >= 0.91
    assert min(position.y0 for position in positions) <= 0.06
    assert max(position.y1 for position in positions) >= 0.97
    figure.clear()


def test_sovereign_yield_chart_uses_percent_axis_instead_of_currency() -> None:
    history = _history(symbol="US10Y", period="1Y", interval="1d")
    figure = build_chart_figure(history)

    assert figure.axes[0].get_ylabel() == "Yield (%)"
    assert "USD" not in figure.axes[0].get_ylabel()
    figure.clear()


def test_candlestick_chart_can_be_rendered_as_embedded_bitmap() -> None:
    image = build_chart_image(_history())
    sampled_colors = image.resize((100, 50)).getcolors(maxcolors=5_000)

    assert image.mode == "RGB"
    assert image.width >= 1000
    assert image.height >= 500
    assert sampled_colors is not None
    assert len(sampled_colors) > 20


def test_chart_engine_supports_candles_line_ohlc_and_vwap() -> None:
    images = {
        chart_type: build_chart_image(
            _history(),
            chart_type=chart_type,
            show_volume=False,
            show_vwap=True,
        )
        for chart_type in CHART_TYPES
    }

    assert set(images) == {"candle", "line", "ohlc"}
    assert len({image.tobytes() for image in images.values()}) == 3


def test_chart_annotations_are_drawn_on_embedded_bitmap() -> None:
    history = _history(period="1Y", interval="1d")
    plain = build_chart_image(history, show_volume=False, show_sma=False, show_ema=False)
    annotated = build_chart_image(
        history,
        show_volume=False,
        show_sma=False,
        show_ema=False,
        drawings=[("TREND", 0.2, 0.7, 0.8, 0.3), ("HLINE", 0.1, 0.5, 0.9, 0.5)],
    )

    assert plain.size == annotated.size
    assert plain.tobytes() != annotated.tobytes()
    midpoint = (round(annotated.width * 0.5), round(annotated.height * 0.5))
    assert annotated.getpixel(midpoint) == (255, 255, 255)


def test_market_service_passes_selected_interval_to_provider(tmp_path) -> None:
    calls: list[tuple[str, str, str]] = []

    class RecordingProvider:
        name = "Recording"

        async def historical(self, symbol: str, period: str, interval: str) -> PriceHistory:
            calls.append((symbol, period, interval))
            return _history(symbol, period, interval)

    service = MarketService(
        cache=SQLiteCache(tmp_path / "chart-cache.sqlite3"),
        market_providers=[RecordingProvider()],
    )
    history = asyncio.run(service.history("AAPL", "5D", "15M"))

    assert calls == [("AAPL", "5D", "15m")]
    assert history.interval == "15m"
