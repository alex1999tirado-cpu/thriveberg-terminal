from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from ajax_terminal.analytics.portfolio_risk import (
    FactorReturnSeries,
    PortfolioRiskReport,
    PositionReturnSeries,
    analyze_portfolio_risk,
    returns_from_levels,
    spread_returns,
)
from ajax_terminal.models.quote import DataQuality, PriceHistory
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.utils.periods import normalize_history_period


@dataclass(frozen=True, slots=True)
class PortfolioRiskPosition:
    symbol: str
    market_value: float
    currency: str


_FACTOR_PROXIES = {
    "SIZE": ("IWM", "BENCHMARK"),
    "VALUE": ("IWD", "IWF"),
    "MOMENTUM": ("MTUM", "BENCHMARK"),
    "QUALITY": ("QUAL", "BENCHMARK"),
}


def load_portfolio_risk(
    positions: Sequence[PortfolioRiskPosition],
    *,
    net_asset_value: float,
    base_currency: str,
    benchmark: str = "SPY",
    period: str = "1Y",
    market: MarketService | None = None,
) -> PortfolioRiskReport:
    clean_benchmark = benchmark.strip().upper() or "SPY"
    clean_period = normalize_history_period(period)
    service = market or MarketService()

    async def load() -> PortfolioRiskReport:
        requested = list(dict.fromkeys(
            [item.symbol.strip().upper() for item in positions]
            + [clean_benchmark, "IWM", "IWD", "IWF", "MTUM", "QUAL"]
        ))
        histories = await asyncio.gather(
            *(service.history(symbol, clean_period, "1d", allow_mock=False) for symbol in requested)
        )
        history_by_symbol = dict(zip(requested, histories))
        currencies = {
            (history.currency or item.currency or base_currency).strip().upper()
            for item in positions
            for history in [history_by_symbol.get(item.symbol.strip().upper(), PriceHistory("", "", "", []))]
        }
        currencies.update(
            (history.currency or "USD").strip().upper()
            for symbol, history in history_by_symbol.items()
            if symbol in {clean_benchmark, "IWM", "IWD", "IWF", "MTUM", "QUAL"}
        )
        fx_histories = await asyncio.gather(
            *(
                _load_fx_history(service, currency, base_currency, clean_period)
                for currency in sorted(currencies)
                if currency and currency != base_currency.upper()
            )
        )
        fx_by_currency = {
            currency: fx
            for currency, fx in zip(
                [item for item in sorted(currencies) if item and item != base_currency.upper()],
                fx_histories,
            )
        }

        total_market = sum(max(item.market_value, 0.0) for item in positions)
        risk_positions: list[PositionReturnSeries] = []
        foreign_value = 0.0
        for item in positions:
            symbol = item.symbol.strip().upper()
            history = history_by_symbol[symbol]
            currency = (history.currency or item.currency or base_currency).strip().upper()
            if currency != base_currency.upper():
                foreign_value += max(item.market_value, 0.0)
            levels, status = _base_levels(history, currency, base_currency, fx_by_currency)
            returns = returns_from_levels(levels)
            if history.quality == DataQuality.MOCK:
                returns = {}
                status = "MOCK HISTORY REJECTED"
            elif not history.bars:
                status = "NO OBSERVED HISTORY"
            elif not returns and status == "OK":
                status = "INSUFFICIENT RETURNS"
            risk_positions.append(
                PositionReturnSeries(
                    symbol,
                    returns,
                    item.market_value / net_asset_value if net_asset_value > 0 else 0.0,
                    item.market_value,
                    currency,
                    history.provider,
                    str(history.quality),
                    status,
                )
            )

        factor_returns: dict[str, tuple[dict[date, float], str]] = {}
        for symbol in {clean_benchmark, "IWM", "IWD", "IWF", "MTUM", "QUAL"}:
            history = history_by_symbol[symbol]
            currency = (history.currency or "USD").strip().upper()
            levels, _status = _base_levels(history, currency, base_currency, fx_by_currency)
            factor_returns[symbol] = (returns_from_levels(levels), history.provider)
        benchmark_values, benchmark_provider = factor_returns.get(clean_benchmark, ({}, "UNAVAILABLE"))
        factors = [
            FactorReturnSeries("MARKET", benchmark_values, clean_benchmark, benchmark_provider)
        ]
        for name, (long_symbol, short_symbol) in _FACTOR_PROXIES.items():
            short = clean_benchmark if short_symbol == "BENCHMARK" else short_symbol
            long_values, long_provider = factor_returns.get(long_symbol, ({}, "UNAVAILABLE"))
            short_values, short_provider = factor_returns.get(short, ({}, "UNAVAILABLE"))
            factors.append(
                FactorReturnSeries(
                    name,
                    spread_returns(long_values, short_values),
                    f"{long_symbol}-{short}",
                    _providers(long_provider, short_provider),
                )
            )
        return analyze_portfolio_risk(
            risk_positions,
            net_asset_value=net_asset_value,
            benchmark=clean_benchmark,
            period=clean_period,
            benchmark_returns=benchmark_values,
            factor_series=factors,
            foreign_weight=foreign_value / net_asset_value if net_asset_value > 0 else 0.0,
        )

    return asyncio.run(load())


async def _load_fx_history(
    market: MarketService,
    currency: str,
    base_currency: str,
    period: str,
) -> tuple[PriceHistory | None, bool]:
    source = currency.strip().upper()
    target = base_currency.strip().upper()
    direct = await market.history(f"{source}{target}", period, "1d", allow_mock=False)
    if direct.bars and direct.quality != DataQuality.MOCK:
        return direct, False
    inverse = await market.history(f"{target}{source}", period, "1d", allow_mock=False)
    if inverse.bars and inverse.quality != DataQuality.MOCK:
        return inverse, True
    return None, False


def _base_levels(
    history: PriceHistory,
    currency: str,
    base_currency: str,
    fx_by_currency: Mapping[str, tuple[PriceHistory | None, bool]],
) -> tuple[dict[date, float], str]:
    levels = {
        bar.timestamp.date(): float(bar.close)
        for bar in history.bars
        if bar.close > 0
    }
    if not levels or currency == base_currency.strip().upper():
        return levels, "OK"
    fx_history, inverse = fx_by_currency.get(currency, (None, False))
    if fx_history is None:
        return {}, f"NO {currency}/{base_currency.upper()} FX HISTORY"
    fx_levels = {
        bar.timestamp.date(): float(bar.close)
        for bar in fx_history.bars
        if bar.close > 0
    }
    converted: dict[date, float] = {}
    ordered_fx = sorted(fx_levels.items())
    fx_index = 0
    latest_date: date | None = None
    latest_value: float | None = None
    for observed, level in sorted(levels.items()):
        while fx_index < len(ordered_fx) and ordered_fx[fx_index][0] <= observed:
            latest_date, latest_value = ordered_fx[fx_index]
            fx_index += 1
        if latest_date is None or latest_value is None or (observed - latest_date).days > 7:
            continue
        converted[observed] = level / latest_value if inverse else level * latest_value
    return converted, "OK" if converted else f"NO ALIGNED {currency}/{base_currency.upper()} FX HISTORY"


def _providers(*values: str) -> str:
    return " / ".join(dict.fromkeys(value for value in values if value)) or "UNAVAILABLE"
