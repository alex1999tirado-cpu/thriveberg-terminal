from __future__ import annotations

import time

from rich.markup import escape
from rich.table import Table
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, Key, Resize
from textual.message import Message
from textual.widgets import Button, Static

from ajax_terminal.analytics.live_bars import TradeTick, merge_history_trade_ticks
from ajax_terminal.analytics.market_stats import calculate_market_statistics
from ajax_terminal.config import setting
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import DataQuality, PriceHistory, Quote
from ajax_terminal.providers.finnhub_stream import FinnhubThreadStream
from ajax_terminal.ui.image_widget import Image
from ajax_terminal.ui.chart_data import (
    ChartSupplement,
    average_true_range,
    build_chart_metrics,
    format_quote_value,
    normalized_asset_class,
    quote_decimals,
    trend_label,
    volume_weighted_average_price,
)
from ajax_terminal.ui.chart_window import CHART_RANGES, CHART_TYPES, INTERVAL_LABELS, build_chart_image
from ajax_terminal.utils.formatting import fmt_bp, fmt_money, fmt_number, fmt_percent
from ajax_terminal.utils.periods import chart_intervals_for_period, normalize_history_interval


ALL_INTERVALS = ("1m", "5m", "15m", "30m", "60m", "1d", "1wk")
RANGE_KEYS = dict(zip("12345678", CHART_RANGES))
TYPE_KEYS = {"c": "candle", "l": "line", "o": "ohlc"}


class ChartInstrumentHeader(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("", id="chart-header-identity")
        yield Static("", id="chart-header-quote")
        yield Static("", id="chart-header-session")

    def show_loading(self, symbol: str, period: str, interval: str) -> None:
        self.query_one("#chart-header-identity", Static).update(
            f"[bold bright_yellow]{escape(symbol)}[/]  |  LOADING INSTRUMENT"
        )
        self.query_one("#chart-header-quote", Static).update(
            f"[bold white]--[/]  [dim]-- / --[/]  |  DATA: LOADING  |  RANGE: {period}  |  INTERVAL: {_interval(interval)}"
        )
        self.query_one("#chart-header-session", Static).update("[dim]O --  H --  L --  PREV --  VOL --  AVG VOL --  VWAP --[/]")

    def update_market(
        self,
        quote: Quote,
        history: PriceHistory,
        supplement: ChartSupplement,
        period: str,
        interval: str,
    ) -> None:
        instrument = supplement.instrument
        profile = supplement.profile
        name = profile.name if profile and profile.name else quote.name or instrument.name or quote.symbol
        exchange = (
            profile.exchange
            if profile and profile.exchange
            else instrument.exchange or instrument.country or instrument.region or quote.market_status or "--"
        )
        asset_class = normalized_asset_class(quote)
        quality_style = "yellow" if quote.quality == DataQuality.MOCK else "bright_white"
        change_style = "green" if (quote.change_percent or quote.change or 0) > 0 else "red" if (quote.change_percent or quote.change or 0) < 0 else "white"
        if asset_class == "RATE":
            change = fmt_bp(quote.change * 100.0 if quote.change is not None else None)
        else:
            change = fmt_number(quote.change, quote_decimals(quote), na="--")
        self.query_one("#chart-header-identity", Static).update(
            f"[bold bright_yellow]{escape(quote.symbol)}[/]  |  [bold white]{escape(name.upper())}[/]  |  "
            f"[cyan]{asset_class}[/]  |  {escape(exchange)}  |  {escape(quote.currency or '--')}"
        )
        self.query_one("#chart-header-quote", Static).update(
            f"[bold white]{format_quote_value(quote)}[/]  "
            f"[{change_style}]{change}  {fmt_percent(quote.change_percent, signed=True)}[/]  |  "
            f"DATA: [{quality_style}]{quote.quality}[/]  |  RANGE: [bold]{period}[/]  |  INTERVAL: [bold]{_interval(interval)}[/]"
        )
        self.query_one("#chart-header-session", Static).update(_session_line(quote, history))


class ChartControlBar(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="chart-range-row"):
            yield Static("RANGE", classes="chart-control-label")
            for period in CHART_RANGES:
                yield Button(period, name=period, classes="chart-range chart-segment")
            yield Button("NEWS", id="chart-news", classes="chart-tool")
            yield Button("REFRESH", id="chart-refresh", classes="chart-tool")
            yield Button("RESET", id="chart-reset", classes="chart-tool")
            yield Button("POP OUT", id="chart-popout", classes="chart-tool")
        with Horizontal(id="chart-tools-row"):
            yield Static("BAR", classes="chart-control-label")
            for interval in ALL_INTERVALS:
                yield Button(INTERVAL_LABELS[interval], name=interval, classes="chart-interval chart-segment")
            for chart_type, label in (("candle", "CNDL"), ("line", "LINE"), ("ohlc", "OHLC")):
                yield Button(label, name=chart_type, id=f"chart-type-{chart_type}", classes="chart-type chart-segment")
            yield Button("VOL", id="chart-volume", classes="chart-toggle selected")
            yield Button("SMA", id="chart-sma", classes="chart-toggle selected")
            yield Button("EMA", id="chart-ema", classes="chart-toggle selected")
            yield Button("VWAP", id="chart-vwap", classes="chart-toggle")
            yield Button("TREND", id="chart-trend", classes="chart-tool")
            yield Button("H-LINE", id="chart-hline", classes="chart-tool")
            yield Button("CLEAR", id="chart-clear", classes="chart-tool")


class ChartAnalytics(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("ANALYTICS", id="chart-analytics-title")
        yield Static("Waiting for market history...", id="chart-analytics-grid")

    def update_market(self, quote: Quote, history: PriceHistory, supplement: ChartSupplement) -> None:
        asset_class = normalized_asset_class(quote)
        self.query_one("#chart-analytics-title", Static).update(
            f"[bold cyan]QUICK ANALYTICS / {asset_class}[/]  [dim]DERIVED FROM {history.quality} HISTORY[/]"
        )
        metrics = build_chart_metrics(quote, history, supplement)
        table = Table.grid(expand=False, padding=(0, 0))
        for index in range(4):
            table.add_column("label", style="cyan", width=13, no_wrap=True)
            table.add_column("value", justify="right", min_width=8, no_wrap=True)
            if index < 3:
                table.add_column("separator", style="grey35", width=3, justify="center", no_wrap=True)
        for offset in range(0, min(len(metrics), 12), 4):
            cells: list[str] = []
            row_metrics = metrics[offset : offset + 4]
            for index in range(4):
                label, value = row_metrics[index] if index < len(row_metrics) else ("", "")
                cells.extend((label, f"[{_value_style(value)}]{value}[/]"))
                if index < 3:
                    cells.append("|")
            table.add_row(*cells)
        self.query_one("#chart-analytics-grid", Static).update(table)


class ChartFooter(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("Waiting for market history...", id="chart-status")
        yield Static(
            "1-8 RANGE  C/L/O TYPE  V VOL  S SMA  E EMA  W VWAP  T TREND  H H-LINE  N NEWS  R REFRESH  P POP OUT  X CLEAR  0 RESET",
            id="chart-shortcuts",
        )


class EmbeddedChart(Vertical):
    """Keyboard-first professional chart workspace embedded in the terminal."""

    can_focus = True

    class SelectionChanged(Message):
        def __init__(self, symbol: str, period: str, interval: str) -> None:
            super().__init__()
            self.symbol = symbol
            self.period = period
            self.interval = interval

    class RefreshRequested(Message):
        def __init__(self, symbol: str, period: str, interval: str) -> None:
            super().__init__()
            self.symbol = symbol
            self.period = period
            self.interval = interval

    class NewsRequested(Message):
        def __init__(self, symbol: str) -> None:
            super().__init__()
            self.symbol = symbol

    class PopOutRequested(Message):
        def __init__(self, symbol: str, period: str, interval: str) -> None:
            super().__init__()
            self.symbol = symbol
            self.period = period
            self.interval = interval

    class QuoteChanged(Message):
        def __init__(self, quote: Quote) -> None:
            super().__init__()
            self.quote = quote

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.symbol = "AAPL"
        self.period = "1Y"
        self.interval = "1d"
        self.history: PriceHistory | None = None
        self.quote: Quote | None = None
        self.supplement = ChartSupplement(INSTRUMENT_REGISTRY.resolve("AAPL"))
        self.chart_type = "candle"
        self.draw_mode: str | None = None
        self.pending_point: tuple[float, float] | None = None
        self.drawings: list[tuple[str, float, float, float, float]] = []
        self.show_volume = True
        self.show_sma = True
        self.show_ema = True
        self.show_vwap = False
        self.streaming_enabled = True
        self._stream: FinnhubThreadStream | None = None
        self._pending_ticks: list[TradeTick] = []
        self._stream_status = "AUTO REFRESH / 30S"
        self._last_refresh_at = time.monotonic()

    def compose(self) -> ComposeResult:
        yield ChartControlBar(id="chart-controls")
        yield Image(id="chart-image")
        yield ChartAnalytics(id="chart-analytics")
        yield ChartFooter(id="chart-footer")

    def on_mount(self) -> None:
        self._sync_controls()
        self._sync_responsive_controls(self.size.width)
        self.query_one("#chart-trend", Button).tooltip = "Draw a two-point trend line"
        self.query_one("#chart-hline", Button).tooltip = "Draw a horizontal reference line"
        self.query_one("#chart-clear", Button).tooltip = "Remove chart annotations"
        self.query_one("#chart-news", Button).tooltip = "Open related headlines"
        self.query_one("#chart-refresh", Button).tooltip = "Refresh market history"
        self.query_one("#chart-reset", Button).tooltip = "Restore the default chart view"
        self.query_one("#chart-popout", Button).tooltip = "Open the interactive chart in a separate window"
        self.set_interval(0.5, self._flush_stream_ticks)
        self.set_interval(5.0, self._check_periodic_refresh)

    def on_unmount(self) -> None:
        self.deactivate_stream()

    def on_resize(self, event: Resize) -> None:
        if self.is_mounted:
            self._sync_responsive_controls(event.size.width)

    def prepare(self, symbol: str, period: str, interval: str) -> None:
        self.deactivate_stream()
        self.symbol = symbol.upper().strip()
        self.period = period
        self.interval = normalize_history_interval(period, interval)
        self.history = None
        self.quote = None
        self.supplement = ChartSupplement(INSTRUMENT_REGISTRY.resolve(self.symbol))
        self.draw_mode = None
        self.pending_point = None
        self.drawings = []
        self._pending_ticks.clear()
        self._stream_status = "AUTO REFRESH / 30S"
        self._last_refresh_at = time.monotonic()
        self._sync_controls()
        self.query_one("#chart-analytics-title", Static).update("[bold cyan]QUICK ANALYTICS[/]")
        self.query_one("#chart-analytics-grid", Static).update("[dim]Waiting for market history...[/]")
        self.query_one("#chart-status", Static).update("Loading market history...")
        self.query_one("#chart-image", Image).image = None
        self.loading = True

    def set_market_data(self, quote: Quote, supplement: ChartSupplement | None = None) -> None:
        self.quote = quote
        if supplement is not None:
            self.supplement = supplement
        self._refresh_market_components()

    def set_history(self, history: PriceHistory) -> None:
        self.history = history
        self.symbol = history.symbol
        self.period = history.period
        self.interval = history.interval
        self.loading = False
        self._last_refresh_at = time.monotonic()
        self._sync_controls()
        self._refresh_market_components()
        self._draw()
        self.activate_stream()

    def set_streaming_enabled(self, enabled: bool) -> None:
        self.streaming_enabled = enabled
        if not enabled:
            self.deactivate_stream("AUTO REFRESH / 30S")

    def activate_stream(self) -> None:
        self.deactivate_stream()
        if not self.streaming_enabled or self.history is None:
            return
        if self.supplement.instrument.asset_class != AssetClass.EQUITY:
            self._stream_status = "AUTO REFRESH / 30S"
            return
        api_key = setting("FINNHUB_KEY")
        if not api_key:
            self._stream_status = "FINNHUB NOT CONFIGURED / AUTO 30S"
            return

        def on_trade(tick: TradeTick) -> None:
            try:
                self.app.call_from_thread(self._queue_stream_tick, tick)
            except RuntimeError:
                return

        def on_status(status: str) -> None:
            try:
                self.app.call_from_thread(self._set_stream_status, status)
            except RuntimeError:
                return

        self._stream = FinnhubThreadStream(api_key, self.symbol, on_trade, on_status)
        self._stream.start()

    def deactivate_stream(self, status: str | None = None) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
        self._pending_ticks.clear()
        if status is not None:
            self._stream_status = status

    def _queue_stream_tick(self, tick: TradeTick) -> None:
        if self.history is not None and tick.symbol.upper() == self.symbol:
            self._pending_ticks.append(tick)

    def _set_stream_status(self, status: str) -> None:
        self._stream_status = status
        self._refresh_status()

    def _flush_stream_ticks(self) -> None:
        if self.history is None or not self._pending_ticks:
            return
        ticks, self._pending_ticks = self._pending_ticks, []
        updated = merge_history_trade_ticks(self.history, ticks)
        if updated is self.history:
            return
        self.history = updated
        latest = updated.bars[-1]
        if self.quote is not None:
            previous = self.quote.previous_close
            self.quote.price = latest.close
            self.quote.day_high = max(value for value in (self.quote.day_high, latest.high) if value is not None)
            self.quote.day_low = min(value for value in (self.quote.day_low, latest.low) if value is not None)
            if latest.volume is not None:
                self.quote.volume = latest.volume
            if previous:
                self.quote.change = latest.close - previous
                self.quote.change_percent = self.quote.change / previous * 100.0
            self.quote.provider = "Finnhub WebSocket"
            self.quote.quality = DataQuality.REALTIME
            self.quote.timestamp = updated.timestamp
        self._refresh_market_components()
        if self.quote is not None:
            self.post_message(self.QuoteChanged(self.quote))
        self._draw()

    def _check_periodic_refresh(self) -> None:
        if not self.streaming_enabled or self.history is None or not self.display:
            return
        refresh_seconds = 300.0 if self._stream is not None else 30.0
        if time.monotonic() - self._last_refresh_at < refresh_seconds:
            return
        self._last_refresh_at = time.monotonic()
        self.post_message(self.RefreshRequested(self.symbol, self.period, self.interval))

    def set_error(self, message: str) -> None:
        self.loading = False
        status = self.query_one("#chart-status", Static)
        status.update(message)
        status.add_class("error")

    @on(Button.Pressed, ".chart-range")
    def range_selected(self, event: Button.Pressed) -> None:
        if event.button.name:
            self._select_range(event.button.name)

    @on(Button.Pressed, ".chart-interval")
    def interval_selected(self, event: Button.Pressed) -> None:
        if event.button.name:
            self._select_interval(event.button.name)

    @on(Button.Pressed, ".chart-type")
    def type_selected(self, event: Button.Pressed) -> None:
        if event.button.name in CHART_TYPES:
            self.chart_type = event.button.name
            self._sync_controls()
            self._draw()

    @on(Button.Pressed, "#chart-refresh")
    def refresh_selected(self) -> None:
        self.post_message(self.RefreshRequested(self.symbol, self.period, self.interval))

    @on(Button.Pressed, "#chart-news")
    def news_selected(self) -> None:
        self.post_message(self.NewsRequested(self.symbol))

    @on(Button.Pressed, "#chart-reset")
    def reset_selected(self) -> None:
        self.reset_view()

    @on(Button.Pressed, "#chart-popout")
    def popout_selected(self) -> None:
        self.post_message(self.PopOutRequested(self.symbol, self.period, self.interval))

    @on(Button.Pressed, "#chart-trend")
    def trend_selected(self) -> None:
        self._set_draw_mode("TREND")

    @on(Button.Pressed, "#chart-hline")
    def hline_selected(self) -> None:
        self._set_draw_mode("HLINE")

    @on(Button.Pressed, ".chart-toggle")
    def overlay_selected(self, event: Button.Pressed) -> None:
        attributes = {
            "chart-volume": "show_volume",
            "chart-sma": "show_sma",
            "chart-ema": "show_ema",
            "chart-vwap": "show_vwap",
        }
        attribute = attributes.get(event.button.id or "")
        if attribute:
            self._toggle(attribute)

    @on(Button.Pressed, "#chart-clear")
    def clear_selected(self) -> None:
        self.clear_drawings()

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        if key in RANGE_KEYS:
            self._select_range(RANGE_KEYS[key])
        elif key in TYPE_KEYS:
            self.chart_type = TYPE_KEYS[key]
            self._sync_controls()
            self._draw()
        elif key in {"v", "s", "e", "w"}:
            attribute = {"v": "show_volume", "s": "show_sma", "e": "show_ema", "w": "show_vwap"}[key]
            self._toggle(attribute)
        elif key == "t":
            self._set_draw_mode("TREND")
        elif key == "h":
            self._set_draw_mode("HLINE")
        elif key == "n":
            self.post_message(self.NewsRequested(self.symbol))
        elif key == "r":
            self.post_message(self.RefreshRequested(self.symbol, self.period, self.interval))
        elif key == "p":
            self.post_message(self.PopOutRequested(self.symbol, self.period, self.interval))
        elif key == "x":
            self.clear_drawings()
        elif key == "0":
            self.reset_view()
        else:
            return
        event.stop()

    @on(Click, "#chart-image")
    def chart_point_selected(self, event: Click) -> None:
        image_widget = self.query_one("#chart-image", Image)
        if event.button != 1 or image_widget.size.width <= 0 or image_widget.size.height <= 0:
            return
        screen_x = event.screen_x if event.screen_x is not None else event.x
        screen_y = event.screen_y if event.screen_y is not None else event.y
        x = min(max((screen_x - image_widget.region.x) / image_widget.size.width, 0.0), 1.0)
        y = min(max((screen_y - image_widget.region.y) / image_widget.size.height, 0.0), 1.0)
        if self.draw_mode == "HLINE":
            self.drawings.append(("HLINE", 0.07, y, 0.94, y))
            self._draw()
            return
        if self.draw_mode != "TREND":
            return
        if self.pending_point is None:
            self.pending_point = (x, y)
            self.query_one("#chart-status", Static).update("TREND: select the second point")
            return
        x1, y1 = self.pending_point
        self.drawings.append(("TREND", x1, y1, x, y))
        self.pending_point = None
        self._draw()

    def reset_view(self) -> None:
        self.chart_type = "candle"
        self.show_volume = True
        self.show_sma = True
        self.show_ema = True
        self.show_vwap = False
        self.drawings.clear()
        self.pending_point = None
        self.draw_mode = None
        self._sync_controls()
        self._draw()

    def clear_drawings(self) -> None:
        self.drawings.clear()
        self.pending_point = None
        self._set_draw_mode(None)
        self._draw()

    def _select_range(self, period: str) -> None:
        self.period = period
        self.interval = normalize_history_interval(period, self.interval)
        self._sync_controls()
        self.post_message(self.SelectionChanged(self.symbol, self.period, self.interval))

    def _select_interval(self, interval: str) -> None:
        self.interval = normalize_history_interval(self.period, interval)
        self._sync_controls()
        self.post_message(self.SelectionChanged(self.symbol, self.period, self.interval))

    def _toggle(self, attribute: str) -> None:
        setattr(self, attribute, not getattr(self, attribute))
        self._sync_controls()
        self._draw()

    def _sync_controls(self) -> None:
        if not self.is_mounted:
            return
        allowed = chart_intervals_for_period(self.period)
        for button in self.query(".chart-range").nodes:
            button.set_class(button.name == self.period, "selected")
        for button in self.query(".chart-interval").nodes:
            button.display = button.name in allowed
            button.set_class(button.name == self.interval, "selected")
        for button in self.query(".chart-type").nodes:
            button.set_class(button.name == self.chart_type, "selected")
        for widget_id, enabled in (
            ("#chart-volume", self.show_volume),
            ("#chart-sma", self.show_sma),
            ("#chart-ema", self.show_ema),
            ("#chart-vwap", self.show_vwap),
        ):
            self.query_one(widget_id, Button).set_class(enabled, "selected")
        self.query_one("#chart-trend", Button).set_class(self.draw_mode == "TREND", "selected")
        self.query_one("#chart-hline", Button).set_class(self.draw_mode == "HLINE", "selected")

    def _sync_responsive_controls(self, width: int) -> None:
        compact = width < 105
        for widget_id in ("#chart-vwap", "#chart-trend", "#chart-hline"):
            self.query_one(widget_id, Button).display = not compact

    def _set_draw_mode(self, mode: str | None) -> None:
        self.draw_mode = mode
        self.pending_point = None
        self._sync_controls()
        if mode:
            instruction = "select two points" if mode == "TREND" else "select a price level"
            self.query_one("#chart-status", Static).update(f"{mode}: {instruction}")

    def _refresh_market_components(self) -> None:
        if self.quote is None or self.history is None or not self.is_mounted:
            return
        self.query_one("#chart-analytics", ChartAnalytics).update_market(
            self.quote,
            self.history,
            self.supplement,
        )

    def _draw(self) -> None:
        if self.history is None or not self.is_mounted:
            return
        try:
            image = build_chart_image(
                self.history,
                chart_type=self.chart_type,
                show_volume=self.show_volume,
                show_sma=self.show_sma,
                show_ema=self.show_ema,
                show_vwap=self.show_vwap,
                drawings=self.drawings,
            )
        except Exception as exc:
            self.set_error(f"Unable to render chart: {exc}")
            return

        self.query_one("#chart-image", Image).image = image
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self.history is None or not self.is_mounted:
            return
        quality = str(self.history.quality)
        status = self.query_one("#chart-status", Static)
        status.remove_class("error", "mock")
        if self.history.quality == DataQuality.MOCK:
            status.add_class("mock")
        studies = [
            name
            for name, enabled in (
                ("VOL", self.show_volume),
                ("SMA", self.show_sma),
                ("EMA", self.show_ema),
                ("VWAP", self.show_vwap),
            )
            if enabled
        ]
        status.update(
            f"{self.chart_type.upper()} | {len(self.history.bars)} BARS | {'+'.join(studies) or 'NO STUDIES'} | "
            f"{self.history.provider} | {quality} | {self._stream_status} | UTC | DRAWINGS {len(self.drawings)}"
        )


def _session_line(quote: Quote, history: PriceHistory) -> str:
    decimals = quote_decimals(quote)
    asset_class = normalized_asset_class(quote)
    stats = calculate_market_statistics(history)
    atr = average_true_range(history)
    vwap = volume_weighted_average_price(history)
    if asset_class == "FX":
        return (
            f"[cyan]SPOT[/] {fmt_number(quote.price, decimals)}   [cyan]DAY H[/] {fmt_number(quote.day_high, decimals)}   "
            f"[cyan]DAY L[/] {fmt_number(quote.day_low, decimals)}   [cyan]52W H[/] {fmt_number(quote.week_52_high, decimals)}   "
            f"[cyan]52W L[/] {fmt_number(quote.week_52_low, decimals)}   "
            f"[cyan]VOLATILITY[/] {fmt_percent(stats.annualized_volatility * 100 if stats.annualized_volatility is not None else None)}"
        )
    if asset_class == "RATE":
        average = sum(bar.close for bar in history.bars) / len(history.bars) if history.bars else None
        return (
            f"[cyan]YIELD[/] {fmt_number(quote.price, 3)}%   [cyan]CHG[/] {fmt_bp(quote.change * 100 if quote.change is not None else None)}   "
            f"[cyan]HIGH[/] {fmt_number(quote.day_high, 3)}   [cyan]LOW[/] {fmt_number(quote.day_low, 3)}   "
            f"[cyan]PREV[/] {fmt_number(quote.previous_close, 3)}   [cyan]AVG[/] {fmt_number(average, 3)}   "
            f"[cyan]ATR[/] {fmt_bp(atr * 100 if atr is not None else None, signed=False)}   [cyan]TREND[/] {trend_label(history)}"
        )
    return (
        f"[cyan]O[/] {fmt_number(quote.open_price, decimals)}   [cyan]H[/] {fmt_number(quote.day_high, decimals)}   "
        f"[cyan]L[/] {fmt_number(quote.day_low, decimals)}   [cyan]PREV[/] {fmt_number(quote.previous_close, decimals)}   "
        f"[cyan]VOL[/] {fmt_money(quote.volume)}   [cyan]AVG VOL[/] {fmt_money(stats.average_volume_20)}   "
        f"[cyan]VWAP[/] {fmt_number(vwap, decimals)}"
    )


def _interval(interval: str) -> str:
    return INTERVAL_LABELS.get(interval, interval)


def _value_style(value: str) -> str:
    if value.startswith("+") or value == "UP":
        return "green"
    if value.startswith("-") or value == "DOWN":
        return "red"
    if value == "--":
        return "dim"
    return "white"
