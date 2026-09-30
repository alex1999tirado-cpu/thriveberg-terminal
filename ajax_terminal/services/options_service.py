from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Protocol

from ajax_terminal.analytics.options import greeks, implied_volatility
from ajax_terminal.models.options import (
    OptionChain,
    OptionContract,
    OptionMarketContext,
    VolatilityPoint,
    VolatilitySlice,
    VolatilitySurface,
)
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.providers.yahoo_options import YahooOptionsProvider
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache


LOGGER = logging.getLogger(__name__)
MONEYNESS_GRID = (0.80, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20)


class OptionsProvider(Protocol):
    name: str

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        ...


class OptionsService:
    CHAIN_TTL = 120

    def __init__(
        self,
        market_service: MarketService | None = None,
        provider: OptionsProvider | None = None,
        cache: SQLiteCache | None = None,
    ) -> None:
        self.market_service = market_service or MarketService()
        self.provider = provider or YahooOptionsProvider()
        self.cache = cache or self.market_service.cache

    async def chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        requested = symbol.strip().upper()
        clean = resolve_option_underlying_symbol(requested)
        cache_key = f"options:chain:v1:{clean}:{expiry.isoformat() if expiry else 'FRONT'}"
        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            chain = _chain_from_dict(cached)
            await self._resolve_underlying_spot(chain)
            return chain
        failure_message = ""
        try:
            chain = await self.provider.option_chain(clean, expiry)
            await self._resolve_underlying_spot(chain)
            self.cache.set_json(cache_key, _chain_to_dict(chain), self.CHAIN_TTL)
            return chain
        except Exception as exc:
            LOGGER.warning("options chain provider=%s symbol=%s error=%s", self.provider.name, clean, exc)
            failure_message = str(exc)
        stale = self.cache.get_stale_json(cache_key)
        if isinstance(stale, dict):
            chain = _chain_from_dict(stale)
            chain.quality = DataQuality.CACHED
            chain.message = "Live refresh failed; displaying the last real cached chain."
            return chain
        return OptionChain(
            symbol=clean,
            name=clean,
            spot=None,
            currency="",
            expirations=[],
            selected_expiry=expiry,
            calls=[],
            puts=[],
            provider=self.provider.name,
            quality=DataQuality.UNAVAILABLE,
            message=failure_message or "The configured provider did not return a real option chain.",
        )

    async def _resolve_underlying_spot(self, chain: OptionChain) -> None:
        """Fill a missing options quote only from real quote/history observations."""
        if chain.spot is not None and chain.spot > 0:
            return
        quote_method = getattr(self.market_service, "quote", None)
        if quote_method is not None:
            try:
                quote = await quote_method(chain.symbol, allow_mock=False)
                if quote.price is not None and quote.price > 0 and quote.quality not in {
                    DataQuality.MOCK,
                    DataQuality.UNAVAILABLE,
                }:
                    chain.spot = quote.price
                    chain.name = quote.name or chain.name
                    chain.currency = quote.currency or chain.currency
                    chain.underlying_change = quote.change
                    chain.underlying_change_percent = quote.change_percent
                    chain.market_status = quote.market_status
                    chain.timestamp = quote.timestamp
                    return
            except Exception as exc:
                LOGGER.warning("options spot quote symbol=%s error=%s", chain.symbol, exc)

        history_method = getattr(self.market_service, "history", None)
        if history_method is None:
            return
        try:
            history = await history_method(chain.symbol, "5D", "15m", allow_mock=False)
            if history.bars and history.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
                latest = history.bars[-1]
                chain.spot = latest.close
                chain.currency = history.currency or chain.currency
                chain.timestamp = latest.timestamp
        except Exception as exc:
            LOGGER.warning("options spot history symbol=%s error=%s", chain.symbol, exc)

    async def market_context(
        self,
        chain: OptionChain,
        expiry: date | None = None,
    ) -> OptionMarketContext:
        selected = expiry or chain.selected_expiry
        years = max(((selected - date.today()).days if selected else 365) / 365.0, 1 / 365.0)
        curve = await self.market_service.curve(chain.currency or "USD", allow_mock=False)
        valid_points = [
            point
            for point in curve.points
            if point.yield_pct is not None and curve.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        if valid_points:
            point = min(valid_points, key=lambda item: abs(item.years - years))
            rate = point.yield_pct / 100.0
            rate_source = f"{curve.provider} {point.tenor}"
            rate_available = True
        else:
            rate = 0.0
            rate_source = "UNAVAILABLE / MODEL RATE CALCULATIONS DISABLED"
            rate_available = False
        dividend_source = f"{chain.provider} UNDERLYING QUOTE" if chain.dividend_yield > 0 else "0.00% / NOT REPORTED"
        return OptionMarketContext(
            rate=rate,
            dividend_yield=chain.dividend_yield,
            rate_source=rate_source,
            dividend_source=dividend_source,
            rate_available=rate_available,
        )

    def enrich_chain(self, chain: OptionChain, context: OptionMarketContext) -> OptionChain:
        if chain.spot is None or chain.spot <= 0 or chain.selected_expiry is None:
            return chain
        time_years = max((chain.selected_expiry - date.today()).days / 365.0, 1 / 365.0)
        for contract in (*chain.calls, *chain.puts):
            market_price = contract.market_price
            volatility = None
            try:
                if market_price is not None and context.rate_available:
                    volatility = implied_volatility(
                        contract.option_type,
                        market_price,
                        chain.spot,
                        contract.strike,
                        context.rate,
                        time_years,
                        context.dividend_yield,
                    )
                    contract.calculated_implied_volatility = volatility
            except ValueError:
                volatility = None
            if volatility is None and contract.vendor_implied_volatility is not None:
                candidate = contract.vendor_implied_volatility
                volatility = candidate if 0.005 <= candidate <= 5.0 else None
            if volatility is None:
                continue
            if not context.rate_available:
                continue
            try:
                values = greeks(
                    contract.option_type,
                    chain.spot,
                    contract.strike,
                    context.rate,
                    volatility,
                    time_years,
                    context.dividend_yield,
                )
            except ValueError:
                continue
            contract.delta = values.delta
        return chain

    async def chain_with_context(
        self,
        symbol: str,
        expiry: date | None = None,
    ) -> tuple[OptionChain, OptionMarketContext]:
        chain = await self.chain(symbol, expiry)
        context = await self.market_context(chain, chain.selected_expiry)
        return self.enrich_chain(chain, context), context

    async def option_monitor(
        self,
        symbol: str,
        expiry: date | None = None,
        max_expiries: int = 3,
    ) -> tuple[list[OptionChain], OptionMarketContext]:
        """Load the compact set of real expiries shown together by OMON."""
        front = await self.chain(symbol, expiry)
        context = await self.market_context(front, front.selected_expiry)
        self.enrich_chain(front, context)
        if (
            not front.expirations
            or front.selected_expiry is None
            or front.selected_expiry not in front.expirations
        ):
            return [front], context

        selected_index = front.expirations.index(front.selected_expiry)
        expirations = front.expirations[selected_index : selected_index + max_expiries]
        if front.selected_expiry not in expirations:
            expirations.insert(0, front.selected_expiry)
        remaining = [item for item in expirations if item != front.selected_expiry]
        loaded = await asyncio.gather(*(self.chain(front.symbol, item) for item in remaining))
        chains = [front, *loaded]
        for chain in chains:
            self.enrich_chain(chain, context)
        return sorted(chains, key=lambda item: item.selected_expiry or date.max), context

    async def volatility_surface(self, symbol: str, max_expiries: int = 6) -> VolatilitySurface:
        front = await self.chain(symbol)
        if front.spot is None or front.spot <= 0 or not front.expirations:
            return VolatilitySurface(
                symbol=front.symbol,
                name=front.name,
                spot=front.spot,
                currency=front.currency,
                slices=[],
                moneyness_grid=MONEYNESS_GRID,
                rate=0.0,
                dividend_yield=front.dividend_yield,
                provider=front.provider,
                quality=front.quality,
                rate_available=False,
                message=front.message or "No real expirations were returned by the provider.",
            )
        available_expirations = [
            expiry
            for expiry in front.expirations
            if 0 < (expiry - date.today()).days <= 730
        ]
        expirations = _representative_expirations(available_expirations, max_expiries)
        chains = await asyncio.gather(*(self.chain(front.symbol, expiry) for expiry in expirations))
        context = await self.market_context(front, expirations[0] if expirations else None)
        slices: list[VolatilitySlice] = []
        for chain in chains:
            self.enrich_chain(chain, context)
            points = _volatility_points(chain)
            if len(points) < 3 or chain.selected_expiry is None:
                continue
            slices.append(
                VolatilitySlice(
                    expiry=chain.selected_expiry,
                    days_to_expiry=max((chain.selected_expiry - date.today()).days, 0),
                    points=points,
                    grid={target: _interpolate(points, target) for target in MONEYNESS_GRID},
                )
            )
        qualities = {chain.quality for chain in chains if chain.calls or chain.puts}
        quality = DataQuality.CACHED if DataQuality.CACHED in qualities else front.quality
        return VolatilitySurface(
            symbol=front.symbol,
            name=front.name,
            spot=front.spot,
            currency=front.currency,
            slices=slices,
            moneyness_grid=MONEYNESS_GRID,
            rate=context.rate,
            dividend_yield=context.dividend_yield,
            provider=front.provider,
            quality=quality,
            rate_available=context.rate_available,
            timestamp=front.timestamp,
            message=(
                "Mid-derived IV where usable; otherwise provider-reported IV for liquid listed contracts. "
                "Grid cells are interpolated only inside observed support."
                + (" Model-derived IV and Greeks are disabled because no real reference rate is available." if not context.rate_available else "")
            ),
        )


def resolve_option_underlying_symbol(symbol: str) -> str:
    """Return the listed-option underlying for a terminal security selection."""
    clean = symbol.strip().upper()
    instrument = INSTRUMENT_REGISTRY.get(clean)
    if instrument is None or instrument.asset_class in {AssetClass.EQUITY, AssetClass.INDEX}:
        return clean
    if instrument.instrument_type == "CORPORATE_BOND":
        match = re.match(r"^([A-Z][A-Z.]*)\d", instrument.symbol)
        if match:
            return match.group(1)
    raise ValueError(
        f"{instrument.symbol} is {instrument.asset_class.value}; OMON, OVME and OVDV require "
        "an optionable equity or index underlying."
    )


def _volatility_points(chain: OptionChain) -> list[VolatilityPoint]:
    if chain.spot is None or chain.selected_expiry is None:
        return []
    calls = {contract.strike: contract for contract in chain.calls}
    puts = {contract.strike: contract for contract in chain.puts}
    points: list[VolatilityPoint] = []
    days = max((chain.selected_expiry - date.today()).days, 0)
    for strike in sorted(set(calls) | set(puts)):
        moneyness = strike / chain.spot
        if not 0.75 <= moneyness <= 1.25:
            continue
        preferred = calls.get(strike) if strike >= chain.spot else puts.get(strike)
        alternate = puts.get(strike) if strike >= chain.spot else calls.get(strike)
        selected = _surface_observation(preferred) or _surface_observation(alternate)
        if selected is None:
            continue
        contract, market_price, volatility = selected
        points.append(
            VolatilityPoint(
                expiry=chain.selected_expiry,
                days_to_expiry=days,
                strike=strike,
                moneyness=moneyness,
                option_type=contract.option_type,
                market_price=market_price,
                implied_volatility=volatility,
                delta=contract.delta,
                volume=contract.volume,
                open_interest=contract.open_interest,
            )
        )
    return points


def _surface_eligible(contract: OptionContract | None) -> bool:
    if (
        contract is None
        or contract.calculated_implied_volatility is None
        or contract.bid is None
        or contract.ask is None
        or contract.bid <= 0
        or contract.ask < contract.bid
    ):
        return False
    midpoint = (contract.bid + contract.ask) / 2.0
    relative_spread = (contract.ask - contract.bid) / midpoint if midpoint > 0 else float("inf")
    liquidity = (contract.volume or 0) + (contract.open_interest or 0)
    return midpoint >= 0.05 and relative_spread <= 0.50 and liquidity > 0


def _surface_observation(contract: OptionContract | None) -> tuple[OptionContract, float, float] | None:
    if contract is None or contract.delta is None:
        return None
    liquidity = (contract.volume or 0) + (contract.open_interest or 0)
    if liquidity <= 0:
        return None
    if _surface_eligible(contract):
        return (
            contract,
            (float(contract.bid) + float(contract.ask)) / 2.0,
            float(contract.calculated_implied_volatility),
        )
    vendor_iv = contract.vendor_implied_volatility
    market_price = contract.market_price
    if (
        vendor_iv is None
        or not 0.005 <= vendor_iv <= 5.0
        or market_price is None
        or market_price <= 0
    ):
        return None
    return contract, market_price, float(vendor_iv)


def _interpolate(points: list[VolatilityPoint], target: float) -> float | None:
    ordered = sorted(points, key=lambda item: item.moneyness)
    for point in ordered:
        if abs(point.moneyness - target) <= 0.0025:
            return point.implied_volatility
    lower = next((point for point in reversed(ordered) if point.moneyness < target), None)
    upper = next((point for point in ordered if point.moneyness > target), None)
    if lower is None or upper is None or upper.moneyness == lower.moneyness:
        return None
    weight = (target - lower.moneyness) / (upper.moneyness - lower.moneyness)
    return lower.implied_volatility + weight * (upper.implied_volatility - lower.implied_volatility)


def _representative_expirations(expirations: list[date], limit: int) -> list[date]:
    if len(expirations) <= limit:
        return sorted(expirations)
    targets = (7, 30, 60, 90, 180, 365, 540, 730)
    selected: list[date] = []
    for target in targets:
        remaining = [expiry for expiry in expirations if expiry not in selected]
        if not remaining or len(selected) >= limit:
            break
        selected.append(min(remaining, key=lambda expiry: abs((expiry - date.today()).days - target)))
    return sorted(selected)


def _chain_to_dict(chain: OptionChain) -> dict:
    def contract(item: OptionContract) -> dict:
        payload = asdict(item)
        payload["expiry"] = item.expiry.isoformat()
        payload["last_trade"] = item.last_trade.isoformat() if item.last_trade else None
        return payload

    return {
        "symbol": chain.symbol,
        "name": chain.name,
        "spot": chain.spot,
        "currency": chain.currency,
        "expirations": [item.isoformat() for item in chain.expirations],
        "selected_expiry": chain.selected_expiry.isoformat() if chain.selected_expiry else None,
        "calls": [contract(item) for item in chain.calls],
        "puts": [contract(item) for item in chain.puts],
        "provider": chain.provider,
        "quality": str(chain.quality),
        "dividend_yield": chain.dividend_yield,
        "underlying_change": chain.underlying_change,
        "underlying_change_percent": chain.underlying_change_percent,
        "market_status": chain.market_status,
        "timestamp": chain.timestamp.isoformat(),
        "message": chain.message,
    }


def _chain_from_dict(payload: dict) -> OptionChain:
    def contract(node: dict) -> OptionContract:
        return OptionContract(
            **{
                **node,
                "expiry": date.fromisoformat(node["expiry"]),
                "last_trade": datetime.fromisoformat(node["last_trade"]) if node.get("last_trade") else None,
            }
        )

    return OptionChain(
        symbol=str(payload.get("symbol") or ""),
        name=str(payload.get("name") or payload.get("symbol") or ""),
        spot=payload.get("spot"),
        currency=str(payload.get("currency") or ""),
        expirations=[date.fromisoformat(value) for value in payload.get("expirations", [])],
        selected_expiry=date.fromisoformat(payload["selected_expiry"]) if payload.get("selected_expiry") else None,
        calls=[contract(node) for node in payload.get("calls", [])],
        puts=[contract(node) for node in payload.get("puts", [])],
        provider=str(payload.get("provider") or "UNKNOWN"),
        quality=DataQuality(payload.get("quality", DataQuality.UNAVAILABLE)),
        dividend_yield=float(payload.get("dividend_yield") or 0.0),
        underlying_change=payload.get("underlying_change"),
        underlying_change_percent=payload.get("underlying_change_percent"),
        market_status=str(payload.get("market_status") or ""),
        timestamp=datetime.fromisoformat(payload["timestamp"]) if payload.get("timestamp") else datetime.now(timezone.utc),
        message=str(payload.get("message") or ""),
    )
