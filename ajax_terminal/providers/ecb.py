from __future__ import annotations

import asyncio
import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timezone

import requests

from ajax_terminal.models.quote import Curve, CurvePoint, DataQuality
from ajax_terminal.providers.base import ProviderError


TENORS = ("3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y")
SERIES = "+".join(f"SR_{tenor}" for tenor in TENORS)
URL = (
    "https://data-api.ecb.europa.eu/service/data/YC/"
    f"B.U2.EUR.4F.G_N_A.SV_C_YM.{SERIES}"
    "?lastNObservations=2&format=csvdata&detail=dataonly"
)


class ECBProvider:
    """ECB daily AAA euro-area government zero-coupon spot curve."""

    name = "ECB"

    async def curve(self, currency: str) -> Curve:
        if currency.upper() != "EUR":
            raise ProviderError(f"ECB does not provide a {currency.upper()} curve")

        def read() -> str:
            response = requests.get(
                URL,
                headers={
                    "Accept": "text/csv",
                    "User-Agent": "AJAX-Financial-Terminal/0.1",
                },
                timeout=12,
            )
            response.raise_for_status()
            return response.text

        try:
            return parse_ecb_curve(await asyncio.to_thread(read))
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network path
            raise ProviderError(str(exc)) from exc


def parse_ecb_curve(payload: str) -> Curve:
    observations: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(payload)):
        data_type = (row.get("DATA_TYPE_FM") or "").strip()
        if not data_type.startswith("SR_"):
            continue
        tenor = data_type.removeprefix("SR_")
        try:
            observed_on = date.fromisoformat((row.get("TIME_PERIOD") or "").strip())
            value = float(row.get("OBS_VALUE") or "")
        except (TypeError, ValueError):
            continue
        observations[tenor].append((observed_on, value))
    if not observations:
        raise ProviderError("ECB API returned no euro yield-curve observations")

    points: list[CurvePoint] = []
    latest_dates: list[date] = []
    for tenor in TENORS:
        series = sorted(observations.get(tenor, []), key=lambda item: item[0])
        if not series:
            continue
        latest_date, latest = series[-1]
        previous = series[-2][1] if len(series) > 1 else None
        points.append(
            CurvePoint(
                tenor=tenor,
                years=_tenor_years(tenor),
                yield_pct=latest,
                change_bp=(latest - previous) * 100.0 if previous is not None else None,
            )
        )
        latest_dates.append(latest_date)
    if not points:
        raise ProviderError("ECB API returned no supported euro curve tenors")
    latest_date = max(latest_dates)
    return Curve(
        currency="EUR",
        name="EUR AAA ZERO-COUPON CURVE",
        points=points,
        provider="ECB",
        quality=DataQuality.DELAYED,
        timestamp=datetime.combine(latest_date, time(), timezone.utc),
        method="ECB SVENSSON / AAA EURO AREA GOVERNMENT SPOT RATES",
    )


def _tenor_years(tenor: str) -> float:
    if tenor.endswith("M"):
        return int(tenor[:-1]) / 12.0
    return float(tenor[:-1])
