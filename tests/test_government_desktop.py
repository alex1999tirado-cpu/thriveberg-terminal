from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ajax_terminal.government_desktop import (
    _resolve_universe,
    build_government_chart_option,
    build_government_load,
)
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory, Quote
from ajax_terminal.providers.fred_yields import SERIES


def _quote(symbol: str, value: float, change: float) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        price=value,
        change=change,
        previous_close=value - change,
        currency="%",
        asset_class="RATE",
        provider="OFFICIAL TEST",
        quality=DataQuality.DELAYED,
        timestamp=datetime(2026, 10, 2, tzinfo=timezone.utc),
    )


def _history(symbol: str, values: tuple[float, ...]) -> PriceHistory:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return PriceHistory(
        symbol=symbol,
        period="1Y",
        interval="1d",
        bars=[
            PriceBar(start + timedelta(days=index), value, value, value, value)
            for index, value in enumerate(values)
        ],
        provider="OFFICIAL TEST",
        quality=DataQuality.DELAYED,
    )


def test_global_universe_is_grouped_like_world_bond_markets() -> None:
    scope, title, mode, instruments = _resolve_universe((), INSTRUMENT_REGISTRY)

    assert (scope, mode) == ("WORLD", "world")
    assert "WORLD BOND MARKETS" in title
    assert all(item.symbol.endswith("10Y") for item in instruments)
    assert {"US10Y", "DE10Y", "JP10Y", "AU10Y", "CA10Y"}.issubset(
        {item.symbol for item in instruments}
    )


def test_provider_backed_sovereign_series_are_registered() -> None:
    registered = {item.symbol for item in INSTRUMENT_REGISTRY.government_benchmarks()}

    assert set(SERIES).issubset(registered)


def test_world_bond_model_calculates_bp_spreads_and_historical_range() -> None:
    instruments = [INSTRUMENT_REGISTRY.get("US10Y"), INSTRUMENT_REGISTRY.get("DE10Y")]
    model = build_government_load(
        "WORLD",
        "WORLD BOND MARKETS / GLOBAL 10Y",
        "world",
        [item for item in instruments if item is not None],
        [_quote("US10Y", 4.10, 0.02), _quote("DE10Y", 2.70, -0.01)],
        [_history("US10Y", (3.8, 4.0, 4.1)), _history("DE10Y", (2.4, 2.9, 2.7))],
    )
    by_symbol = {item.symbol: item for item in model.observations}

    assert by_symbol["US10Y"].change_bp == 2.0
    assert round(by_symbol["DE10Y"].spread_to_ust_bp or 0.0, 6) == -140.0
    assert by_symbol["DE10Y"].range_low == 2.4
    assert by_symbol["DE10Y"].range_high == 2.9
    assert round(by_symbol["DE10Y"].range_position or 0.0, 6) == 0.6


def test_global_chart_is_horizontal_yield_comparison_with_movement_colors() -> None:
    instruments = [INSTRUMENT_REGISTRY.get("US10Y"), INSTRUMENT_REGISTRY.get("DE10Y")]
    model = build_government_load(
        "WORLD",
        "WORLD BOND MARKETS / GLOBAL 10Y",
        "world",
        [item for item in instruments if item is not None],
        [_quote("US10Y", 4.10, 0.02), _quote("DE10Y", 2.70, -0.01)],
        [_history("US10Y", (3.8, 4.1)), _history("DE10Y", (2.4, 2.7))],
    )
    option = build_government_chart_option(model)

    assert option["xAxis"]["type"] == "value"
    assert option["yAxis"]["type"] == "category"
    assert option["series"][0]["type"] == "bar"
    assert {item["name"] for item in option["series"][0]["data"]} == {"US10Y", "DE10Y"}


def test_country_scope_uses_all_registered_tenors_and_curve_chart() -> None:
    scope, _title, mode, instruments = _resolve_universe(("ES",), INSTRUMENT_REGISTRY)
    quotes = [_quote(item.symbol, 2.0 + index * 0.2, 0.01) for index, item in enumerate(instruments)]
    histories = [_history(item.symbol, (1.8, quote.price or 0.0)) for item, quote in zip(instruments, quotes, strict=True)]
    model = build_government_load(scope, "SPAIN GOVERNMENT CURVE", mode, instruments, quotes, histories)
    option = build_government_chart_option(model)

    assert scope == "ES"
    assert [item.tenor for item in model.observations] == ["2Y", "5Y", "10Y", "15Y", "30Y"]
    assert option["series"][0]["type"] == "line"
    assert option["xAxis"]["data"] == ["2Y", "5Y", "10Y", "15Y", "30Y"]
