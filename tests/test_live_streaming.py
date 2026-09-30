from __future__ import annotations

from datetime import datetime, timezone

from ajax_terminal.analytics.live_bars import TradeTick, merge_history_trade_ticks, merge_trade_ticks
from ajax_terminal.charts.models.ohlcv import OHLCVChart, OHLCVPoint
from ajax_terminal.config import setting
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory
from ajax_terminal.providers.finnhub_stream import parse_trade_message


def _chart(interval: str = "1m") -> OHLCVChart:
    return OHLCVChart(
        symbol="AAPL",
        period="1D",
        interval=interval,
        currency="USD",
        provider="Yahoo Finance",
        quality="DELAYED",
        points=[
            OHLCVPoint(
                timestamp=datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1_000.0,
            )
        ],
    )


def test_trade_stream_updates_active_bar_and_volume() -> None:
    tick = TradeTick("AAPL", 102.0, int(datetime(2026, 9, 28, 14, 0, 30, tzinfo=timezone.utc).timestamp() * 1000), 25)

    result = merge_trade_ticks(_chart(), [tick])

    assert len(result.points) == 1
    assert result.points[-1].open == 100.0
    assert result.points[-1].high == 102.0
    assert result.points[-1].low == 99.0
    assert result.points[-1].close == 102.0
    assert result.points[-1].volume == 1_025.0
    assert result.provider == "Finnhub WebSocket"
    assert result.quality == "STREAM"


def test_trade_stream_starts_next_interval_without_fabricated_ohlc() -> None:
    tick = TradeTick("AAPL", 103.0, int(datetime(2026, 9, 28, 14, 1, 5, tzinfo=timezone.utc).timestamp() * 1000), 10)

    result = merge_trade_ticks(_chart(), [tick])

    assert len(result.points) == 2
    assert result.points[-1].timestamp == datetime(2026, 9, 28, 14, 1, tzinfo=timezone.utc)
    assert (result.points[-1].open, result.points[-1].high, result.points[-1].low, result.points[-1].close) == (
        103.0,
        103.0,
        103.0,
        103.0,
    )


def test_trade_stream_ignores_other_symbols_and_invalid_prices() -> None:
    original = _chart()
    ticks = [
        TradeTick("MSFT", 200.0, 1_800_000_000_000, 1),
        TradeTick("AAPL", -1.0, 1_800_000_000_000, 1),
    ]

    result = merge_trade_ticks(original, ticks)

    assert result.points == original.points
    assert result.provider == original.provider


def test_trade_stream_updates_embedded_price_history() -> None:
    history = PriceHistory(
        symbol="AAPL",
        period="1D",
        interval="1m",
        bars=[
            PriceBar(
                timestamp=datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1_000.0,
            )
        ],
        provider="Yahoo Finance",
        quality=DataQuality.DELAYED,
    )
    tick = TradeTick(
        "AAPL",
        102.0,
        int(datetime(2026, 9, 28, 14, 0, 30, tzinfo=timezone.utc).timestamp() * 1000),
        25,
    )

    result = merge_history_trade_ticks(history, [tick])

    assert result.bars[-1].close == 102.0
    assert result.bars[-1].high == 102.0
    assert result.bars[-1].volume == 1_025.0
    assert result.quality == DataQuality.REALTIME
    assert result.provider == "Finnhub WebSocket + Yahoo history"


def test_finnhub_trade_frame_is_normalized() -> None:
    ticks = parse_trade_message(
        '{"data":[{"p":202.5,"s":"AAPL","t":1790604030000,"v":12}],"type":"trade"}'
    )

    assert ticks == [TradeTick("AAPL", 202.5, 1_790_604_030_000, 12.0)]


def test_setting_reads_repository_env_without_overriding_process(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FINNHUB_KEY", "process-key")
    assert setting("FINNHUB_KEY") == "process-key"


def test_setting_reads_env_from_runtime_working_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AJAX_RUNTIME_TEST", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AJAX_RUNTIME_TEST=frozen-runtime\n", encoding="utf-8")

    assert setting("AJAX_RUNTIME_TEST") == "frozen-runtime"
