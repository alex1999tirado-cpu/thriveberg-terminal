from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

from ajax_terminal.models.fixed_income import CreditBenchmark
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory, Quote
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.fred_csv import fred_observations
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period


SERIES = {
    "USCORPIG": ("BAMLC0A0CMEY", "BAMLC0A0CM", "ICE BofA US Corporate IG", "IG"),
    "USCORPHY": ("BAMLH0A0HYM2EY", "BAMLH0A0HYM2", "ICE BofA US High Yield", "HY"),
    "USCORPAAA": ("BAMLC0A1CAAAEY", "BAMLC0A1CAAA", "ICE BofA AAA US Corporate", "AAA"),
    "USCORPAA": ("BAMLC0A2CAAEY", "BAMLC0A2CAA", "ICE BofA AA US Corporate", "AA"),
    "USCORPA": ("BAMLC0A3CAEY", "BAMLC0A3CA", "ICE BofA Single-A US Corporate", "A"),
    "USCORPBBB": ("BAMLC0A4CBBBEY", "BAMLC0A4CBBB", "ICE BofA BBB US Corporate", "BBB"),
}


class FredCreditProvider:
    """Daily ICE BofA effective yields and OAS series distributed by FRED."""

    name = "FRED / ICE BofA"

    async def benchmark(self, symbol: str) -> CreditBenchmark:
        clean = symbol.upper()
        yield_id, oas_id, name, rating = _series(clean)
        yields, spreads = await asyncio.gather(
            fred_observations(yield_id, "2023-01-01"),
            fred_observations(oas_id, "2023-01-01"),
        )
        if not yields or not spreads:
            raise ProviderError(f"FRED credit benchmark unavailable for {clean}")
        yield_date, effective_yield = yields[-1]
        oas_date, oas_pct = spreads[-1]
        previous_yield = yields[-2][1] if len(yields) > 1 else None
        previous_oas = spreads[-2][1] if len(spreads) > 1 else None
        latest_date = max(yield_date, oas_date)
        return CreditBenchmark(
            symbol=clean,
            name=name,
            rating=rating,
            effective_yield_pct=effective_yield,
            yield_change_bp=(effective_yield - previous_yield) * 100.0 if previous_yield is not None else None,
            oas_bp=oas_pct * 100.0,
            oas_change_bp=(oas_pct - previous_oas) * 100.0 if previous_oas is not None else None,
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=datetime.combine(latest_date, time(), timezone.utc),
        )

    async def quote(self, symbol: str) -> Quote:
        benchmark = await self.benchmark(symbol)
        change = benchmark.yield_change_bp / 100.0 if benchmark.yield_change_bp is not None else None
        previous = benchmark.effective_yield_pct - change if change is not None else None
        change_percent = change / previous * 100.0 if change is not None and previous else None
        return Quote(
            symbol=benchmark.symbol,
            name=benchmark.name,
            price=benchmark.effective_yield_pct,
            change=change,
            change_percent=change_percent,
            currency="%",
            asset_class="RATE",
            previous_close=previous,
            provider=benchmark.provider,
            quality=benchmark.quality,
            timestamp=benchmark.timestamp,
        )

    async def historical(self, symbol: str, period: str = "1Y", interval: str | None = None) -> PriceHistory:
        clean = symbol.upper()
        yield_id, _oas_id, _name, _rating = _series(clean)
        observations = await fred_observations(yield_id, "2023-01-01")
        if not observations:
            raise ProviderError(f"FRED credit history unavailable for {clean}")
        normalized = normalize_history_period(period)
        selected_interval = normalize_history_interval(normalized, interval)
        counts = {"1D": 2, "5D": 6, "1M": 23, "3M": 66, "6M": 132, "YTD": 260, "1Y": 265, "5Y": 800}
        selected = observations[-counts.get(normalized, 265) :]
        bars = [
            PriceBar(
                timestamp=datetime.combine(day, time(), timezone.utc),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=None,
            )
            for day, value in selected
        ]
        return PriceHistory(
            symbol=clean,
            period=normalized,
            interval=selected_interval,
            bars=bars,
            currency="%",
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=bars[-1].timestamp,
        )


def _series(symbol: str) -> tuple[str, str, str, str]:
    try:
        return SERIES[symbol]
    except KeyError as exc:
        raise ProviderError(f"No FRED credit benchmark mapping for {symbol}") from exc
