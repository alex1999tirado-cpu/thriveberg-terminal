from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ajax_terminal.analytics.market_stats import calculate_market_statistics, horizon_returns
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory


def _history() -> PriceHistory:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100.0 + index,
            high=102.0 + index,
            low=99.0 + index,
            close=101.0 + index,
            volume=1_000_000 + index * 10_000,
        )
        for index in range(40)
    ]
    return PriceHistory("TEST", "3M", "1d", bars, "USD", "TEST", DataQuality.MOCK)


def test_market_statistics_and_horizon_returns() -> None:
    history = _history()
    stats = calculate_market_statistics(history)
    returns = horizon_returns(history)

    assert stats.period_return is not None and stats.period_return > 0
    assert stats.annualized_volatility is not None
    assert stats.average_volume_20 is not None
    assert returns["1W"] is not None and returns["1W"] > 0
    assert returns["1M"] is not None and returns["1M"] > 0
    assert returns["1Y"] is None


def test_market_return_statistics_use_adjusted_close_across_a_split() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    history = PriceHistory(
        "TEST",
        "1Y",
        "1d",
        [
            PriceBar(start, 1_000, 1_010, 990, 1_000, adjusted_close=100),
            PriceBar(
                start + timedelta(days=8),
                101, 102, 100, 101,
                adjusted_close=101,
            ),
        ],
        "USD",
        "TEST",
        DataQuality.DELAYED,
    )

    stats = calculate_market_statistics(history)
    horizons = horizon_returns(history)

    assert stats.period_return == pytest.approx(0.01)
    assert horizons["1W"] == pytest.approx(0.01)
