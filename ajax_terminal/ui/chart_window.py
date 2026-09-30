from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _configure_matplotlib_cache() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    path = base / "AJAX Financial Terminal" / "matplotlib"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(tempfile.gettempdir()) / "ajax-financial-terminal-matplotlib"
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(path))
    return path


_configure_matplotlib_cache()

import matplotlib

matplotlib.use("Agg")

import mplfinance as mpf
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PIL import Image as PILImage, ImageDraw

from ajax_terminal.models.quote import DataQuality, PriceHistory
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.utils.periods import (
    HISTORY_PERIODS,
    chart_intervals_for_period,
    normalize_history_interval,
    normalize_history_period,
)


CHART_RANGES = tuple(HISTORY_PERIODS)
CHART_TYPES = ("candle", "line", "ohlc")


@dataclass(frozen=True, slots=True)
class ChartStudySpec:
    key: str
    label: str
    placement: str
    implemented: bool


CHART_STUDIES = {
    study.key: study
    for study in (
        ChartStudySpec("sma", "SMA", "overlay", True),
        ChartStudySpec("ema", "EMA", "overlay", True),
        ChartStudySpec("vwap", "VWAP", "overlay", True),
        ChartStudySpec("bollinger", "BOLL", "overlay", False),
        ChartStudySpec("rsi", "RSI", "lower_panel", False),
        ChartStudySpec("macd", "MACD", "lower_panel", False),
        ChartStudySpec("volume_profile", "VOL PROFILE", "side_panel", False),
    )
}
INTERVAL_LABELS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1h",
    "1d": "1D",
    "1wk": "1W",
}


def history_to_frame(history: PriceHistory) -> pd.DataFrame:
    rows = [
        {
            "Date": bar.timestamp.replace(tzinfo=None),
            "Open": bar.open,
            "High": bar.high,
            "Low": bar.low,
            "Close": bar.close,
            "Volume": bar.volume or 0.0,
        }
        for bar in history.bars
    ]
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    frame = pd.DataFrame(rows).set_index("Date")
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def build_chart_figure(
    history: PriceHistory,
    *,
    chart_type: str = "candle",
    show_volume: bool = True,
    show_sma: bool = True,
    show_ema: bool = True,
    show_vwap: bool = False,
) -> Figure:
    frame = history_to_frame(history)
    if frame.empty:
        raise ValueError(f"No price history available for {history.symbol}")
    selected_type = chart_type.lower()
    if selected_type not in CHART_TYPES:
        raise ValueError(f"Unsupported chart type: {chart_type}")

    market_colors = mpf.make_marketcolors(
        up="#22c55e",
        down="#ef4444",
        edge="inherit",
        wick="inherit",
        volume={"up": "#15803d", "down": "#b91c1c"},
    )
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=market_colors,
        facecolor="#080a0c",
        figcolor="#050607",
        gridcolor="#343a40",
        gridstyle="--",
        y_on_right=True,
        rc={
            "axes.labelcolor": "#aeb6bf",
            "axes.titlecolor": "#ffb000",
            "font.family": "DejaVu Sans",
            "text.color": "#d7dce2",
            "xtick.color": "#9aa3ad",
            "ytick.color": "#9aa3ad",
            "axes.edgecolor": "#59616a",
            "axes.linewidth": 0.7,
            "grid.alpha": 0.28,
            "grid.linewidth": 0.55,
            "legend.fontsize": 8,
        },
    )

    overlays = []
    if show_sma and len(frame) >= 20:
        overlays.append(
            mpf.make_addplot(
                frame["Close"].rolling(20).mean(),
                color="#ffb000",
                width=1.1,
                label="SMA 20",
            )
        )
    if show_ema and len(frame) >= 2:
        overlays.append(
            mpf.make_addplot(
                frame["Close"].ewm(span=50, adjust=False).mean(),
                color="#38bdf8",
                width=1.1,
                label="EMA 50",
            )
        )
    if show_vwap and frame["Volume"].sum() > 0:
        typical_price = (frame["High"] + frame["Low"] + frame["Close"]) / 3.0
        cumulative_volume = frame["Volume"].cumsum().replace(0, float("nan"))
        vwap = (typical_price * frame["Volume"]).cumsum() / cumulative_volume
        overlays.append(
            mpf.make_addplot(
                vwap,
                color="#f8fafc",
                width=0.9,
                label="VWAP",
            )
        )

    options: dict[str, Any] = {
        "type": selected_type,
        "style": style,
        "volume": show_volume,
        "returnfig": True,
        "figratio": (16, 9),
        "figscale": 1.0,
        "panel_ratios": (4, 1) if show_volume else None,
        "ylabel": _history_axis_label(history),
        "ylabel_lower": "Volume",
        "datetime_format": "%H:%M" if history.interval.endswith("m") else "%d %b %Y",
        "xrotation": 0,
        "tight_layout": False,
        "scale_padding": {
            "left": 0.35,
            "right": 0.85,
            "top": 0.18,
            "bottom": 0.30,
        },
        "warn_too_much_data": 1000,
        "linecolor": "#38bdf8",
        "update_width_config": {
            "candle_width": 0.55,
            "candle_linewidth": 0.55,
            "ohlc_ticksize": 0.42,
            "ohlc_linewidth": 0.75,
            "volume_width": 0.62,
            "volume_linewidth": 0.2,
            "line_width": 1.0,
        },
        "hlines": {
            "hlines": [float(frame["Close"].iloc[-1])],
            "colors": ["#7b848d"],
            "linestyle": ":",
            "linewidths": [0.7],
        },
    }
    if overlays:
        options["addplot"] = overlays
    if not show_volume:
        options.pop("panel_ratios")
        options.pop("ylabel_lower")

    figure, axes = mpf.plot(frame, **options)
    if overlays and axes:
        axes[0].legend(loc="upper left", facecolor="#101214", edgecolor="#3b424a", labelcolor="#d7dce2")
    return figure


def _history_axis_label(history: PriceHistory) -> str:
    instrument = INSTRUMENT_REGISTRY.get(history.symbol)
    if instrument is not None and instrument.asset_class == AssetClass.RATE:
        return "Yield (%)"
    return f"Price ({history.currency or '--'})"


def build_chart_image(
    history: PriceHistory,
    *,
    chart_type: str = "candle",
    show_volume: bool = True,
    show_sma: bool = True,
    show_ema: bool = True,
    show_vwap: bool = False,
    drawings: list[tuple[str, float, float, float, float]] | None = None,
) -> PILImage.Image:
    """Render a chart to a bitmap suitable for an embedded terminal image widget."""
    figure = build_chart_figure(
        history,
        chart_type=chart_type,
        show_volume=show_volume,
        show_sma=show_sma,
        show_ema=show_ema,
        show_vwap=show_vwap,
    )
    try:
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        width, height = canvas.get_width_height()
        image = PILImage.frombuffer(
            "RGBA",
            (width, height),
            canvas.buffer_rgba(),
            "raw",
            "RGBA",
            0,
            1,
        ).convert("RGB")
        if drawings:
            _apply_drawings(image, drawings)
        return image
    finally:
        figure.clear()
        plt.close(figure)


def _apply_drawings(image: PILImage.Image, drawings: list[tuple[str, float, float, float, float]]) -> None:
    canvas = ImageDraw.Draw(image)
    width, height = image.size
    line_width = 1
    for kind, x1, y1, x2, y2 in drawings:
        start = (round(x1 * width), round(y1 * height))
        end = (round(x2 * width), round(y2 * height))
        color = "#ffffff"
        canvas.line((start, end), fill=color, width=line_width)
        radius = 2
        for x, y in (start, end):
            canvas.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=line_width)


def launch_chart_process(symbol: str, period: str = "1Y", interval: str | None = None) -> subprocess.Popen:
    clean_symbol = symbol.upper().strip()
    clean_period = normalize_history_period(period)
    clean_interval = normalize_history_interval(clean_period, interval)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--chart", clean_symbol, clean_period, clean_interval]
    else:
        command = [sys.executable, "-m", "ajax_terminal", "--chart", clean_symbol, clean_period, clean_interval]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=Path.cwd(),
        env=os.environ.copy(),
        creationflags=creation_flags,
    )


def run_chart_window(symbol: str, period: str = "1Y", interval: str | None = None) -> int:
    import tkinter as tk
    from tkinter import ttk

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

    from ajax_terminal.services.market_service import MarketService

    class ChartWindow:
        BG = "#090b0d"
        PANEL = "#13171b"
        BORDER = "#30363d"
        TEXT = "#d7dce2"
        MUTED = "#8f99a3"
        ACCENT = "#ffb000"

        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title(f"THRIVEBERG Chart | {symbol.upper()}")
            self.root.geometry("1280x820")
            self.root.minsize(900, 620)
            self.root.configure(bg=self.BG)
            self.root.protocol("WM_DELETE_WINDOW", self.close)

            self.symbol = tk.StringVar(value=symbol.upper())
            self.period = tk.StringVar(value=normalize_history_period(period))
            self.interval = tk.StringVar(value=normalize_history_interval(self.period.get(), interval))
            self.show_volume = tk.BooleanVar(value=True)
            self.show_sma = tk.BooleanVar(value=True)
            self.show_ema = tk.BooleanVar(value=True)
            self.status = tk.StringVar(value="Loading market history...")
            self.results: queue.Queue = queue.Queue()
            self.request_id = 0
            self.history: PriceHistory | None = None
            self.figure: Figure | None = None
            self.canvas = None
            self.toolbar = None
            self.closed = False

            self._configure_styles(ttk)
            self._build_controls(tk, ttk)
            self._build_chart_area(tk)
            self.root.after(100, self._poll_results)
            self.reload()

        def _configure_styles(self, ttk_module) -> None:
            style = ttk_module.Style(self.root)
            style.theme_use("clam")
            style.configure("Ajax.TButton", background=self.PANEL, foreground=self.TEXT, padding=(12, 7), borderwidth=1)
            style.map("Ajax.TButton", background=[("active", "#262c32")])
            style.configure("Ajax.TCheckbutton", background=self.PANEL, foreground=self.TEXT)
            style.map("Ajax.TCheckbutton", background=[("active", self.PANEL)])

        def _build_controls(self, tk_module, ttk_module) -> None:
            header = tk_module.Frame(self.root, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
            header.pack(fill="x")

            top = tk_module.Frame(header, bg=self.PANEL)
            top.pack(fill="x", padx=14, pady=(12, 8))
            tk_module.Label(top, text="THRIVEBERG CHART", bg=self.PANEL, fg=self.ACCENT, font=("Segoe UI", 12, "bold")).pack(side="left")
            self.symbol_entry = tk_module.Entry(
                top,
                textvariable=self.symbol,
                bg="#0d1013",
                fg=self.TEXT,
                insertbackground=self.TEXT,
                relief="flat",
                width=16,
                font=("Consolas", 11, "bold"),
            )
            self.symbol_entry.pack(side="left", padx=(18, 8), ipady=6)
            self.symbol_entry.bind("<Return>", lambda _event: self.reload())
            self.reload_button = ttk_module.Button(top, text="REFRESH", style="Ajax.TButton", command=self.reload)
            self.reload_button.pack(side="left")

            for label, variable in (
                ("Volume", self.show_volume),
                ("SMA 20", self.show_sma),
                ("EMA 50", self.show_ema),
            ):
                ttk_module.Checkbutton(
                    top,
                    text=label,
                    variable=variable,
                    style="Ajax.TCheckbutton",
                    command=self.redraw,
                ).pack(side="right", padx=(10, 0))

            selector = tk_module.Frame(header, bg=self.PANEL)
            selector.pack(fill="x", padx=14, pady=(0, 12))
            tk_module.Label(selector, text="RANGE", bg=self.PANEL, fg=self.MUTED, width=9, anchor="w").pack(side="left")
            for value in CHART_RANGES:
                self._segment(tk_module, selector, value, self.period, value, self._range_changed).pack(side="left", padx=(0, 2))
            tk_module.Label(selector, text="INTERVAL", bg=self.PANEL, fg=self.MUTED, width=10, anchor="e").pack(side="left", padx=(18, 8))
            self.interval_frame = tk_module.Frame(selector, bg=self.PANEL)
            self.interval_frame.pack(side="left")
            self._rebuild_interval_segments(tk_module)

        def _segment(self, tk_module, parent, text: str, variable, value: str, command):
            return tk_module.Radiobutton(
                parent,
                text=text,
                variable=variable,
                value=value,
                indicatoron=False,
                command=command,
                bg="#171c21",
                fg=self.TEXT,
                activebackground="#30363d",
                activeforeground="#ffffff",
                selectcolor="#7c6514",
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=6,
                font=("Segoe UI", 9, "bold"),
            )

        def _rebuild_interval_segments(self, tk_module) -> None:
            for child in self.interval_frame.winfo_children():
                child.destroy()
            allowed = chart_intervals_for_period(self.period.get())
            if self.interval.get() not in allowed:
                self.interval.set(normalize_history_interval(self.period.get()))
            for value in allowed:
                self._segment(
                    tk_module,
                    self.interval_frame,
                    INTERVAL_LABELS[value],
                    self.interval,
                    value,
                    self.reload,
                ).pack(side="left", padx=(0, 2))

        def _build_chart_area(self, tk_module) -> None:
            self.chart_frame = tk_module.Frame(self.root, bg=self.BG)
            self.chart_frame.pack(fill="both", expand=True)
            self.status_label = tk_module.Label(
                self.root,
                textvariable=self.status,
                bg=self.PANEL,
                fg=self.MUTED,
                anchor="w",
                padx=14,
                pady=7,
                font=("Consolas", 9),
            )
            self.status_label.pack(fill="x", side="bottom")

        def _range_changed(self) -> None:
            import tkinter as tk_module

            self._rebuild_interval_segments(tk_module)
            self.reload()

        def reload(self) -> None:
            clean_symbol = self.symbol.get().upper().strip()
            if not clean_symbol:
                return
            self.symbol.set(clean_symbol)
            selected_period = normalize_history_period(self.period.get())
            selected_interval = normalize_history_interval(selected_period, self.interval.get())
            self.period.set(selected_period)
            self.interval.set(selected_interval)
            self.request_id += 1
            request_id = self.request_id
            self.reload_button.state(["disabled"])
            self.status.set(f"Loading {clean_symbol} | {selected_period} / {INTERVAL_LABELS[selected_interval]}...")
            self.status_label.configure(fg=self.ACCENT)

            def fetch() -> None:
                try:
                    service = MarketService()
                    history = asyncio.run(
                        service.history(clean_symbol, selected_period, selected_interval, allow_mock=False)
                    )
                    self.results.put((request_id, history, None))
                except Exception as exc:
                    self.results.put((request_id, None, str(exc)))

            threading.Thread(target=fetch, name="ajax-chart-data", daemon=True).start()

        def _poll_results(self) -> None:
            if self.closed:
                return
            try:
                while True:
                    request_id, history, error = self.results.get_nowait()
                    if request_id != self.request_id:
                        continue
                    self.reload_button.state(["!disabled"])
                    if error:
                        self.status.set(f"Data error: {error}")
                        self.status_label.configure(fg="#ef4444")
                        continue
                    self.history = history
                    self.redraw()
            except queue.Empty:
                pass
            self.root.after(100, self._poll_results)

        def redraw(self) -> None:
            if self.history is None:
                return
            try:
                figure = build_chart_figure(
                    self.history,
                    show_volume=self.show_volume.get(),
                    show_sma=self.show_sma.get(),
                    show_ema=self.show_ema.get(),
                )
            except Exception as exc:
                self.status.set(f"Chart error: {exc}")
                self.status_label.configure(fg="#ef4444")
                return
            if self.figure is not None:
                self.figure.clear()
            for child in self.chart_frame.winfo_children():
                child.destroy()
            self.figure = figure
            self.canvas = FigureCanvasTkAgg(figure, master=self.chart_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.chart_frame, pack_toolbar=False)
            self.toolbar.configure(background=self.PANEL)
            self.toolbar.update()
            self.toolbar.pack(fill="x", side="bottom")
            quality = str(self.history.quality)
            self.status.set(
                f"{self.history.symbol} | {self.history.period} / {INTERVAL_LABELS.get(self.history.interval, self.history.interval)}"
                f" | {len(self.history.bars)} bars | {self.history.provider} | {quality}"
            )
            self.status_label.configure(fg=self.ACCENT if self.history.quality == DataQuality.MOCK else self.MUTED)
            self.root.title(f"THRIVEBERG Chart | {self.history.symbol} | {quality}")

        def close(self) -> None:
            self.closed = True
            self.root.destroy()

        def run(self) -> None:
            self.root.mainloop()

    try:
        ChartWindow().run()
    except KeyboardInterrupt:
        return 0
    return 0
