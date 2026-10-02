from __future__ import annotations

from datetime import datetime, timezone


HISTORY_PERIODS: dict[str, tuple[str, str, int]] = {
    "1D": ("1d", "5m", 78),
    "5D": ("5d", "15m", 130),
    "1M": ("1mo", "1d", 23),
    "3M": ("3mo", "1d", 66),
    "6M": ("6mo", "1d", 132),
    "YTD": ("ytd", "1d", 180),
    "1Y": ("1y", "1d", 252),
    "2Y": ("2y", "1d", 504),
    "5Y": ("5y", "1wk", 260),
}

CHART_INTERVALS: dict[str, tuple[str, ...]] = {
    "1D": ("1m", "5m", "15m", "30m", "60m"),
    "5D": ("5m", "15m", "30m", "60m"),
    "1M": ("30m", "60m", "1d"),
    "3M": ("60m", "1d"),
    "6M": ("60m", "1d"),
    "YTD": ("1d", "1wk"),
    "1Y": ("1d", "1wk"),
    "2Y": ("1d", "1wk"),
    "5Y": ("1d", "1wk"),
}

INTERVAL_ALIASES = {
    "1M": "1m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "60M": "60m",
    "1H": "60m",
    "1D": "1d",
    "1W": "1wk",
    "1WK": "1wk",
}


def normalize_history_period(value: str | None, default: str = "1Y") -> str:
    candidate = (value or default).upper()
    return candidate if candidate in HISTORY_PERIODS else default


def history_period_config(period: str) -> tuple[str, str, int]:
    return HISTORY_PERIODS[normalize_history_period(period)]


def chart_intervals_for_period(period: str) -> tuple[str, ...]:
    return CHART_INTERVALS[normalize_history_period(period)]


def normalize_history_interval(period: str, value: str | None = None) -> str:
    normalized_period = normalize_history_period(period)
    default_interval = HISTORY_PERIODS[normalized_period][1]
    if value is None or value.upper() == "AUTO":
        return default_interval
    candidate = INTERVAL_ALIASES.get(value.upper())
    if candidate in CHART_INTERVALS[normalized_period]:
        return candidate
    return default_interval


def mock_point_count(period: str, interval: str | None = None) -> int:
    normalized = normalize_history_period(period)
    selected_interval = normalize_history_interval(normalized, interval)
    if selected_interval.endswith("m"):
        trading_days = {
            "1D": 1,
            "5D": 5,
            "1M": 23,
            "3M": 66,
            "6M": 132,
        }.get(normalized)
        if trading_days is not None:
            minutes = int(selected_interval[:-1])
            return min(500, max(2, trading_days * 390 // minutes))
    if normalized == "YTD":
        day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
        return max(23, int(day_of_year * 5 / 7))
    return HISTORY_PERIODS[normalized][2]


def annualization_factor(interval: str) -> int:
    if interval.endswith("m"):
        return 252 * 78
    if interval.endswith("h"):
        return 252 * 7
    if interval.endswith("wk"):
        return 52
    return 252
