from __future__ import annotations

from datetime import datetime
from math import isfinite
from numbers import Real


def fmt_number(value: float | None, decimals: int = 2, na: str = "--") -> str:
    value = _number(value)
    if value is None:
        return na
    return f"{value:,.{decimals}f}"


def fmt_percent(value: float | None, decimals: int = 2, signed: bool = False, na: str = "--") -> str:
    value = _number(value)
    if value is None:
        return na
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def fmt_bp(value: float | None, decimals: int = 1, signed: bool = True, na: str = "--") -> str:
    value = _number(value)
    if value is None:
        return na
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{decimals}f}bp"


def fmt_money(value: float | None, decimals: int = 2, na: str = "--") -> str:
    value = _number(value)
    if value is None:
        return na
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.{decimals}f}T"
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    return fmt_number(value, decimals)


def signed_style(value: float | None) -> str:
    value = _number(value)
    if value is None:
        return "muted"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def fmt_timestamp(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "--"
    return timestamp.strftime("%H:%M:%S UTC")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    normalized = float(value)
    return normalized if isfinite(normalized) else None
