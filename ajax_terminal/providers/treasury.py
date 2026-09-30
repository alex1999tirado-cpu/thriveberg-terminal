from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

import requests
from defusedxml import ElementTree

from ajax_terminal.models.quote import Curve, CurvePoint, DataQuality
from ajax_terminal.providers.base import ProviderError


_FIELDS = {
    "1M": "BC_1MONTH",
    "2M": "BC_2MONTH",
    "3M": "BC_3MONTH",
    "4M": "BC_4MONTH",
    "6M": "BC_6MONTH",
    "1Y": "BC_1YEAR",
    "2Y": "BC_2YEAR",
    "3Y": "BC_3YEAR",
    "5Y": "BC_5YEAR",
    "7Y": "BC_7YEAR",
    "10Y": "BC_10YEAR",
    "20Y": "BC_20YEAR",
    "30Y": "BC_30YEAR",
}
_YEARS = {
    "1M": 1 / 12,
    "2M": 2 / 12,
    "3M": 3 / 12,
    "4M": 4 / 12,
    "6M": 6 / 12,
    "1Y": 1,
    "2Y": 2,
    "3Y": 3,
    "5Y": 5,
    "7Y": 7,
    "10Y": 10,
    "20Y": 20,
    "30Y": 30,
}


class TreasuryProvider:
    """Official daily US Treasury par yield curve XML feed."""

    name = "US Treasury"

    async def curve(self, currency: str) -> Curve:
        if currency.upper() != "USD":
            raise ProviderError(f"US Treasury does not provide a {currency.upper()} curve")

        def read() -> str:
            year = datetime.now(timezone.utc).year
            url = (
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                f"?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
            )
            response = requests.get(
                url,
                headers={"User-Agent": "AJAX-Financial-Terminal/0.1"},
                timeout=10,
            )
            response.raise_for_status()
            return response.text

        try:
            payload = await asyncio.to_thread(read)
            return parse_treasury_curve(payload)
        except Exception as exc:  # pragma: no cover - network path
            raise ProviderError(str(exc)) from exc


def parse_treasury_curve(payload: str) -> Curve:
    root = ElementTree.fromstring(payload)
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    }
    observations: list[tuple[datetime, dict[str, float]]] = []
    for entry in root.findall("atom:entry", namespaces):
        properties = entry.find("atom:content/m:properties", namespaces)
        if properties is None:
            continue
        date_node = properties.find("d:NEW_DATE", namespaces)
        if date_node is None or not date_node.text:
            continue
        observed_at = datetime.fromisoformat(date_node.text.replace("Z", "+00:00"))
        values: dict[str, float] = {}
        for tenor, field in _FIELDS.items():
            node = properties.find(f"d:{field}", namespaces)
            if node is not None and node.text:
                values[tenor] = float(node.text)
        if values:
            observations.append((observed_at, values))
    if not observations:
        raise ProviderError("US Treasury XML feed returned no yield observations")
    observations.sort(key=lambda item: item[0])
    latest_date, latest = observations[-1]
    previous = observations[-2][1] if len(observations) > 1 else {}
    points = [
        CurvePoint(
            tenor=tenor,
            years=_YEARS[tenor],
            yield_pct=value,
            change_bp=(value - previous[tenor]) * 100.0 if tenor in previous else None,
        )
        for tenor, value in latest.items()
    ]
    timestamp = datetime.combine(latest_date.date(), time(), timezone.utc)
    return Curve(
        currency="USD",
        name="USD TREASURY PAR YIELD CURVE",
        points=points,
        provider="US Treasury",
        quality=DataQuality.DELAYED,
        timestamp=timestamp,
    )
