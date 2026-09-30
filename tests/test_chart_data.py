from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory, Quote
from ajax_terminal.ui.chart_data import (
    ChartSupplement,
    build_chart_metrics,
    chart_returns,
    format_quote_value,
    volume_weighted_average_price,
)


def _daily_history(symbol: str, days: int = 400) -> PriceHistory:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100.0 + index * 0.1,
            high=101.0 + index * 0.1,
            low=99.0 + index * 0.1,
            close=100.5 + index * 0.1,
            volume=1_000_000 + index * 1_000,
        )
        for index in range(days)
    ]
    return PriceHistory(symbol, "5Y", "1d", bars, "USD", "TEST", DataQuality.CACHED)


def test_chart_returns_and_vwap_are_derived_from_history() -> None:
    history = _daily_history("AAPL")
    returns = chart_returns(history)

    assert all(returns[label] is not None for label in ("1D", "MTD", "QTD", "YTD", "1Y"))
    assert volume_weighted_average_price(history) is not None


def test_rate_chart_metrics_use_yield_and_basis_point_units() -> None:
    quote = Quote(
        symbol="US10Y",
        name="US Treasury 10Y Yield",
        price=4.321,
        change=0.012,
        change_percent=0.28,
        currency="USD",
        asset_class="RATE",
        previous_close=4.309,
        quality=DataQuality.CACHED,
    )
    history = _daily_history("US10Y")
    supplement = ChartSupplement(INSTRUMENT_REGISTRY.resolve("US10Y"))
    metrics = dict(build_chart_metrics(quote, history, supplement))

    assert format_quote_value(quote) == "4.321 %"
    assert metrics["YIELD"] == "4.321 %"
    assert metrics["D1"] == "+1.2bp"
    assert metrics["ATR 14"].endswith("bp")
