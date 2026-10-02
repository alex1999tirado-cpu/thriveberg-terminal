from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ajax_terminal.analytics.portfolio_risk import (
    FactorReturnSeries,
    PositionReturnSeries,
    analyze_portfolio_risk,
    returns_from_levels,
)
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory
from ajax_terminal.services.portfolio_risk_service import (
    PortfolioRiskPosition,
    load_portfolio_risk,
)
from ajax_terminal.utils.periods import history_period_config, normalize_history_period


def _dated(values: list[float]) -> dict[date, float]:
    start = date(2026, 1, 1)
    return {start + timedelta(days=index): value for index, value in enumerate(values)}


def _levels(returns: list[float], start: float = 100.0) -> dict[date, float]:
    values = [start]
    for item in returns:
        values.append(values[-1] * (1.0 + item))
    return _dated(values)


def test_portfolio_risk_calculates_metrics_factors_and_scenarios() -> None:
    market = [((index % 11) - 5) / 1000 for index in range(140)]
    size = [((index % 7) - 3) / 1500 for index in range(140)]
    value = [((index % 5) - 2) / 1200 for index in range(140)]
    momentum = [((index % 13) - 6) / 1800 for index in range(140)]
    quality = [((index % 17) - 8) / 2400 for index in range(140)]
    position_returns = [
        0.75 * market[index]
        + 0.25 * size[index]
        - 0.15 * value[index]
        + 0.10 * momentum[index]
        + 0.05 * quality[index]
        for index in range(140)
    ]
    position = PositionReturnSeries(
        "AAPL",
        _dated(position_returns),
        0.80,
        80_000,
        "USD",
        "TEST",
        "DELAYED",
    )
    factors = (
        FactorReturnSeries("MARKET", _dated(market), "SPY", "TEST"),
        FactorReturnSeries("SIZE", _dated(size), "IWM-SPY", "TEST"),
        FactorReturnSeries("VALUE", _dated(value), "IWD-IWF", "TEST"),
        FactorReturnSeries("MOMENTUM", _dated(momentum), "MTUM-SPY", "TEST"),
        FactorReturnSeries("QUALITY", _dated(quality), "QUAL-SPY", "TEST"),
    )

    report = analyze_portfolio_risk(
        (position,),
        net_asset_value=100_000,
        benchmark="SPY",
        period="1Y",
        benchmark_returns=_dated(market),
        factor_series=factors,
        foreign_weight=0.20,
    )

    assert report.available
    assert report.observations == 140
    assert report.coverage_percent == pytest.approx(100.0)
    assert report.annualized_volatility is not None
    assert report.historical_var_95 is not None
    assert report.expected_shortfall_95 is not None
    assert report.beta == pytest.approx(0.60, abs=0.08)
    assert report.factor_r_squared == pytest.approx(1.0)
    assert {item.name for item in report.factors} == {
        "MARKET", "SIZE", "VALUE", "MOMENTUM", "QUALITY"
    }
    assert report.contributions[0].variance_contribution_percent == pytest.approx(100.0)
    assert {item.basis for item in report.scenarios} == {"OBSERVED", "ESTIMATED*"}
    assert any(item.name == "FOREIGN FX -10%*" for item in report.scenarios)


def test_portfolio_risk_rejects_inadequate_real_history_coverage() -> None:
    observed = PositionReturnSeries(
        "AAPL", _dated([0.001] * 90), 0.40, 40_000, "USD", "TEST", "DELAYED"
    )
    missing = PositionReturnSeries(
        "PRIVATE", {}, 0.60, 60_000, "USD", "UNAVAILABLE", "UNAVAILABLE",
        "NO OBSERVED HISTORY",
    )

    report = analyze_portfolio_risk(
        (observed, missing),
        net_asset_value=100_000,
        benchmark="SPY",
        period="1Y",
    )

    assert not report.available
    assert report.coverage_percent == pytest.approx(40.0)
    assert "BELOW 80%" in report.message
    assert report.contributions[1].status == "NO OBSERVED HISTORY"


def test_returns_from_levels_uses_the_return_observation_date() -> None:
    levels = {
        date(2026, 1, 1): 100.0,
        date(2026, 1, 2): 110.0,
        date(2026, 1, 3): 99.0,
    }

    result = returns_from_levels(levels)

    assert result == {
        date(2026, 1, 2): pytest.approx(0.10),
        date(2026, 1, 3): pytest.approx(-0.10),
    }


def test_two_year_history_is_a_first_class_supported_period() -> None:
    assert normalize_history_period("2Y") == "2Y"
    assert history_period_config("2Y") == ("2y", "1d", 504)


class _HistoryMarket:
    def __init__(self, histories: dict[str, PriceHistory]) -> None:
        self.histories = histories
        self.requests: list[str] = []

    async def history(
        self,
        symbol: str,
        period: str = "1Y",
        interval: str | None = None,
        *,
        allow_mock: bool = False,
        refresh: bool = False,
    ) -> PriceHistory:
        self.requests.append(symbol)
        return self.histories.get(
            symbol,
            PriceHistory(symbol, period, interval or "1d", [], provider="UNAVAILABLE"),
        )


def _history(symbol: str, returns: list[float], currency: str) -> PriceHistory:
    levels = _levels(returns)
    bars = [
        PriceBar(
            datetime.combine(observed, datetime.min.time(), tzinfo=timezone.utc),
            value,
            value,
            value,
            value,
            1_000,
        )
        for observed, value in levels.items()
    ]
    return PriceHistory(
        symbol,
        "1Y",
        "1d",
        bars,
        currency=currency,
        provider="TEST",
        quality=DataQuality.DELAYED,
    )


def test_risk_service_converts_foreign_history_into_base_currency() -> None:
    asset_returns = [((index % 9) - 4) / 1200 for index in range(100)]
    market_returns = [((index % 11) - 5) / 1500 for index in range(100)]
    histories = {
        "ASML.AS": _history("ASML.AS", asset_returns, "EUR"),
        "EURUSD": _history("EURUSD", [0.0002] * 100, "USD"),
        "SPY": _history("SPY", market_returns, "USD"),
        "IWM": _history("IWM", [item * 1.1 for item in market_returns], "USD"),
        "IWD": _history("IWD", [item * 0.9 for item in market_returns], "USD"),
        "IWF": _history("IWF", [item * 1.05 for item in market_returns], "USD"),
        "MTUM": _history("MTUM", [item * 1.2 for item in market_returns], "USD"),
        "QUAL": _history("QUAL", [item * 0.8 for item in market_returns], "USD"),
    }
    market = _HistoryMarket(histories)

    report = load_portfolio_risk(
        (PortfolioRiskPosition("ASML.AS", 10_000, "EUR"),),
        net_asset_value=10_000,
        base_currency="USD",
        benchmark="SPY",
        period="1Y",
        market=market,  # type: ignore[arg-type]
    )

    assert report.available
    assert report.coverage_percent == pytest.approx(100.0)
    assert report.observations == 100
    assert report.contributions[0].status == "OK"
    assert "EURUSD" in market.requests


def test_risk_service_never_uses_mock_history() -> None:
    history = _history("AAPL", [0.001] * 100, "USD")
    history.quality = DataQuality.MOCK
    market = _HistoryMarket({"AAPL": history})

    report = load_portfolio_risk(
        (PortfolioRiskPosition("AAPL", 10_000, "USD"),),
        net_asset_value=10_000,
        base_currency="USD",
        market=market,  # type: ignore[arg-type]
    )

    assert not report.available
    assert report.contributions[0].status == "MOCK HISTORY REJECTED"
