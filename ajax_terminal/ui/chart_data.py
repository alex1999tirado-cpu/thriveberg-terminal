from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ajax_terminal.analytics.forwards import ForwardPoint
from ajax_terminal.analytics.market_stats import calculate_market_statistics
from ajax_terminal.models.equity import CompanyProfile, EstimateSet
from ajax_terminal.models.instrument import AssetClass, Instrument
from ajax_terminal.models.quote import DataQuality, EquityFundamentals, PriceHistory, Quote
from ajax_terminal.utils.formatting import fmt_bp, fmt_money, fmt_number, fmt_percent


RATE_CLASSES = {"RATE", "RATES", "YIELD"}


@dataclass(frozen=True, slots=True)
class ChartEvent:
    when: str
    label: str
    detail: str = ""
    quality: DataQuality = DataQuality.UNAVAILABLE


@dataclass(slots=True)
class ChartSupplement:
    instrument: Instrument
    profile: CompanyProfile | None = None
    fundamentals: EquityFundamentals | None = None
    estimates: EstimateSet | None = None
    forwards: list[ForwardPoint] = field(default_factory=list)
    events: list[ChartEvent] = field(default_factory=list)


def normalized_asset_class(quote: Quote) -> str:
    value = quote.asset_class.upper()
    return "RATE" if value in RATE_CLASSES else value


def quote_decimals(quote: Quote) -> int:
    asset_class = normalized_asset_class(quote)
    return 5 if asset_class == "FX" else 3 if asset_class == "RATE" else 2


def quote_unit(quote: Quote) -> str:
    return "%" if normalized_asset_class(quote) == "RATE" else quote.currency or "--"


def format_quote_value(quote: Quote, value: float | None = None, *, include_unit: bool = True) -> str:
    rendered = fmt_number(quote.price if value is None else value, quote_decimals(quote))
    return f"{rendered} {quote_unit(quote)}" if include_unit else rendered


def average_true_range(history: PriceHistory, length: int = 14) -> float | None:
    if not history.bars:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in history.bars[-length:]:
        candidates = [bar.high - bar.low]
        if previous_close is not None:
            candidates.extend((abs(bar.high - previous_close), abs(bar.low - previous_close)))
        ranges.append(max(candidates))
        previous_close = bar.close
    return sum(ranges) / len(ranges) if ranges else None


def volume_weighted_average_price(history: PriceHistory) -> float | None:
    weighted = 0.0
    volume = 0.0
    for bar in history.bars:
        if bar.volume is None or bar.volume <= 0:
            continue
        weighted += ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
        volume += bar.volume
    return weighted / volume if volume else None


def trend_label(history: PriceHistory, length: int = 20) -> str:
    closes = [bar.close for bar in history.bars[-length:] if bar.close > 0]
    if len(closes) < 2:
        return "--"
    average = sum(closes) / len(closes)
    threshold = abs(average) * 0.001
    if closes[-1] > average + threshold:
        return "UP"
    if closes[-1] < average - threshold:
        return "DOWN"
    return "FLAT"


def chart_returns(history: PriceHistory) -> dict[str, float | None]:
    if len(history.bars) < 2:
        return {label: None for label in ("1D", "MTD", "QTD", "YTD", "1Y")}
    latest = history.bars[-1].timestamp
    month_start = latest.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    quarter_month = ((latest.month - 1) // 3) * 3 + 1
    quarter_start = latest.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = latest.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return {
        "1D": _return_since(history, latest - timedelta(days=1), allow_session_start=True),
        "MTD": _return_since(history, month_start),
        "QTD": _return_since(history, quarter_start),
        "YTD": _return_since(history, year_start),
        "1Y": _return_since(history, latest - timedelta(days=365)),
    }


def absolute_change_since(history: PriceHistory, days: int) -> float | None:
    base = _base_close(history, history.bars[-1].timestamp - timedelta(days=days)) if history.bars else None
    return history.bars[-1].close - base if base is not None and history.bars else None


def build_chart_metrics(
    quote: Quote,
    history: PriceHistory,
    supplement: ChartSupplement,
) -> list[tuple[str, str]]:
    asset_class = normalized_asset_class(quote)
    returns = chart_returns(history)
    stats = calculate_market_statistics(history)
    atr = average_true_range(history)
    vwap = volume_weighted_average_price(history)
    vol = fmt_percent(stats.annualized_volatility * 100.0 if stats.annualized_volatility is not None else None)
    period_high = fmt_number(stats.high, quote_decimals(quote))
    period_low = fmt_number(stats.low, quote_decimals(quote))

    if asset_class == "EQUITY":
        fundamentals = supplement.fundamentals
        estimates = supplement.estimates
        usable_fundamentals = fundamentals is not None and fundamentals.quality not in {
            DataQuality.MOCK,
            DataQuality.UNAVAILABLE,
        }
        usable_estimates = estimates is not None and estimates.quality not in {
            DataQuality.MOCK,
            DataQuality.UNAVAILABLE,
        }
        earnings = (
            estimates.earnings_date.astimezone(timezone.utc).strftime("%d %b %Y")
            if usable_estimates and estimates and estimates.earnings_date
            else "--"
        )
        return [
            ("1D", _return_text(returns["1D"])),
            ("MTD", _return_text(returns["MTD"])),
            ("QTD", _return_text(returns["QTD"])),
            ("YTD", _return_text(returns["YTD"])),
            ("1Y", _return_text(returns["1Y"])),
            ("ANN VOL", vol),
            ("ATR 14", fmt_number(atr, quote_decimals(quote))),
            ("AVG VOL", fmt_money(stats.average_volume_20)),
            ("BETA", fmt_number(fundamentals.beta if usable_fundamentals and fundamentals else None)),
            ("MKT CAP", fmt_money(fundamentals.market_cap if usable_fundamentals and fundamentals else None)),
            ("NEXT EARN", earnings),
            ("VWAP", fmt_number(vwap, quote_decimals(quote))),
        ]

    if asset_class == "FX":
        one_month = _forward(supplement.forwards, "1M")
        three_month = _forward(supplement.forwards, "3M")
        return [
            ("SPOT", format_quote_value(quote, include_unit=False)),
            ("1D", _return_text(returns["1D"])),
            ("1M", _return_text(returns["MTD"])),
            ("1Y", _return_text(returns["1Y"])),
            ("ANN VOL", vol),
            ("ATR 14", fmt_number(atr, quote_decimals(quote))),
            ("PERIOD HI", period_high),
            ("PERIOD LO", period_low),
            ("1M FWD", fmt_number(one_month.outright if one_month else None, 5)),
            ("3M FWD", fmt_number(three_month.outright if three_month else None, 5)),
            ("3M CARRY", fmt_percent(three_month.annualized_carry * 100.0 if three_month else None, signed=True)),
            ("TREND", trend_label(history)),
        ]

    if asset_class == "RATE":
        daily_change = quote.change * 100.0 if quote.change is not None else absolute_change_since(history, 1)
        weekly_change = absolute_change_since(history, 7)
        monthly_change = absolute_change_since(history, 30)
        return [
            ("YIELD", format_quote_value(quote)),
            ("D1", fmt_bp(daily_change)),
            ("W1", fmt_bp(weekly_change * 100.0 if weekly_change is not None else None)),
            ("M1", fmt_bp(monthly_change * 100.0 if monthly_change is not None else None)),
            ("ANN VOL", vol),
            ("ATR 14", fmt_bp(atr * 100.0 if atr is not None else None, signed=False)),
            ("PERIOD HI", f"{period_high}%" if period_high != "--" else "--"),
            ("PERIOD LO", f"{period_low}%" if period_low != "--" else "--"),
            ("TREND", trend_label(history)),
            ("PREV", fmt_number(quote.previous_close, 3)),
            ("52W HIGH", fmt_number(quote.week_52_high, 3)),
            ("52W LOW", fmt_number(quote.week_52_low, 3)),
        ]

    if asset_class == "COMMODITY":
        return [
            ("LAST", format_quote_value(quote)),
            ("1D", _return_text(returns["1D"])),
            ("MTD", _return_text(returns["MTD"])),
            ("YTD", _return_text(returns["YTD"])),
            ("1Y", _return_text(returns["1Y"])),
            ("ANN VOL", vol),
            ("ATR 14", fmt_number(atr, quote_decimals(quote))),
            ("AVG VOL", fmt_money(stats.average_volume_20)),
            ("52W HIGH", fmt_number(quote.week_52_high, quote_decimals(quote))),
            ("52W LOW", fmt_number(quote.week_52_low, quote_decimals(quote))),
            ("VWAP", fmt_number(vwap, quote_decimals(quote))),
            ("OPEN INT", "--"),
        ]

    return [
        ("LAST", format_quote_value(quote)),
        ("1D", _return_text(returns["1D"])),
        ("MTD", _return_text(returns["MTD"])),
        ("QTD", _return_text(returns["QTD"])),
        ("YTD", _return_text(returns["YTD"])),
        ("1Y", _return_text(returns["1Y"])),
        ("ANN VOL", vol),
        ("ATR 14", fmt_number(atr, quote_decimals(quote))),
        ("PERIOD HI", period_high),
        ("PERIOD LO", period_low),
        ("AVG VOL", fmt_money(stats.average_volume_20)),
        ("TREND", trend_label(history)),
    ]


def _return_since(history: PriceHistory, boundary: datetime, allow_session_start: bool = False) -> float | None:
    base = _base_close(history, boundary, allow_session_start)
    latest = history.bars[-1].close if history.bars else None
    return latest / base - 1.0 if base not in {None, 0} and latest is not None else None


def _base_close(history: PriceHistory, boundary: datetime, allow_session_start: bool = False) -> float | None:
    if not history.bars:
        return None
    bars = history.bars
    candidates = [bar for bar in bars if bar.timestamp <= boundary]
    if candidates:
        return candidates[-1].close
    tolerance = timedelta(days=7)
    if allow_session_start or bars[0].timestamp <= boundary + tolerance:
        return bars[0].close
    return None


def _return_text(value: float | None) -> str:
    return fmt_percent(value * 100.0 if value is not None else None, signed=True)


def _forward(forwards: list[ForwardPoint], tenor: str) -> ForwardPoint | None:
    return next((point for point in forwards if point.tenor == tenor), None)
