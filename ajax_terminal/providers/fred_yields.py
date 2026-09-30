from __future__ import annotations

from datetime import date, datetime, time, timezone

from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory, Quote
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.fred_csv import fred_observations
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period


SERIES = {
    "DE10Y": ("IRLTLT01DEM156N", "Germany 10Y Government Yield", "EUR"),
    "GB10Y": ("IRLTLT01GBM156N", "United Kingdom 10Y Government Yield", "GBP"),
    "JP10Y": ("IRLTLT01JPM156N", "Japan 10Y Government Yield", "JPY"),
    "FR10Y": ("IRLTLT01FRM156N", "France 10Y Government Yield", "EUR"),
    "IT10Y": ("IRLTLT01ITM156N", "Italy 10Y Government Yield", "EUR"),
    "ES10Y": ("IRLTLT01ESM156N", "Spain 10Y Government Yield", "EUR"),
    "CA10Y": ("IRLTLT01CAM156N", "Canada 10Y Government Yield", "CAD"),
    "MX10Y": ("IRLTLT01MXM156N", "Mexico 10Y Government Yield", "MXN"),
    "CH10Y": ("IRLTLT01CHM156N", "Switzerland 10Y Government Yield", "CHF"),
    "SE10Y": ("IRLTLT01SEM156N", "Sweden 10Y Government Yield", "SEK"),
    "NO10Y": ("IRLTLT01NOM156N", "Norway 10Y Government Yield", "NOK"),
    "PL10Y": ("IRLTLT01PLM156N", "Poland 10Y Government Yield", "PLN"),
    "KR10Y": ("IRLTLT01KRM156N", "South Korea 10Y Government Yield", "KRW"),
    "AU10Y": ("IRLTLT01AUM156N", "Australia 10Y Government Yield", "AUD"),
    "NZ10Y": ("IRLTLT01NZM156N", "New Zealand 10Y Government Yield", "NZD"),
    "ZA10Y": ("IRLTLT01ZAM156N", "South Africa 10Y Government Yield", "ZAR"),
}
class FredSovereignYieldProvider:
    """Official monthly OECD benchmark yields distributed by FRED."""

    name = "FRED / OECD"

    async def quote(self, symbol: str) -> Quote:
        clean = symbol.upper()
        series_id, name, currency = _series(clean)
        observations = await fred_observations(series_id)
        if not observations:
            raise ProviderError(f"FRED yield unavailable for {clean}")
        latest_date, latest = observations[-1]
        previous = observations[-2][1] if len(observations) > 1 else None
        change = latest - previous if previous is not None else None
        change_percent = change / previous * 100.0 if change is not None and previous else None
        return Quote(
            symbol=clean,
            name=name,
            price=latest,
            change=change,
            change_percent=change_percent,
            currency=currency,
            asset_class="RATES",
            previous_close=previous,
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=datetime.combine(latest_date, time(), timezone.utc),
        )

    async def historical(self, symbol: str, period: str = "1Y", interval: str | None = None) -> PriceHistory:
        clean = symbol.upper()
        series_id, _name, currency = _series(clean)
        observations = await fred_observations(series_id)
        if not observations:
            raise ProviderError(f"FRED yield history unavailable for {clean}")
        normalized = normalize_history_period(period)
        selected_interval = normalize_history_interval(normalized, interval)
        counts = {"1D": 2, "5D": 2, "1M": 2, "3M": 4, "6M": 7, "YTD": 12, "1Y": 13, "5Y": 61}
        selected = observations[-counts.get(normalized, 13) :]
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
            currency=currency,
            provider=self.name,
            quality=DataQuality.DELAYED,
            timestamp=bars[-1].timestamp,
        )


def _series(symbol: str) -> tuple[str, str, str]:
    try:
        return SERIES[symbol]
    except KeyError as exc:
        raise ProviderError(f"No FRED sovereign benchmark mapping for {symbol}") from exc
