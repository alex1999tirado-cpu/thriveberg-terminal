from __future__ import annotations

import asyncio
import csv
import io
from datetime import date, datetime, time, timezone

import requests

from ajax_terminal.analytics.fixed_income import bootstrap_zero_rates
from ajax_terminal.models.quote import Curve, CurvePoint, DataQuality
from ajax_terminal.providers.base import ProviderError


CURRENT_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
HISTORICAL_URL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    "historical/jgbcme_all.csv"
)
TENORS = ("1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "15Y", "20Y", "25Y", "30Y", "40Y")
DISPLAY_TENORS = ("1M", "3M", "6M", *TENORS)


class JapanMofCurveProvider:
    """Official JGB constant-maturity yields, converted to a zero curve."""

    name = "Japan MOF"

    async def curve(self, currency: str) -> Curve:
        if currency.upper() != "JPY":
            raise ProviderError(f"Japan MOF does not provide a {currency.upper()} curve")

        def read() -> bytes:
            error: Exception | None = None
            for url in (CURRENT_URL, HISTORICAL_URL):
                try:
                    response = requests.get(
                        url,
                        headers={"User-Agent": "AJAX-Financial-Terminal/0.1"},
                        timeout=12,
                    )
                    response.raise_for_status()
                    return response.content
                except Exception as exc:  # pragma: no cover - network path
                    error = exc
            raise ProviderError(str(error or "Japan MOF curve download failed"))

        try:
            return parse_jgb_curve(await asyncio.to_thread(read))
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - network path
            raise ProviderError(str(exc)) from exc


def parse_jgb_curve(payload: bytes | str) -> Curve:
    text = payload.decode("cp932", errors="replace") if isinstance(payload, bytes) else payload
    observations: list[tuple[date, dict[float, float]]] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < len(TENORS) + 1:
            continue
        observed_on = _parse_mof_date(row[0].strip())
        if observed_on is None:
            continue
        values: dict[float, float] = {}
        for tenor, raw in zip(TENORS, row[1:]):
            try:
                values[_tenor_years(tenor)] = float(raw)
            except (TypeError, ValueError):
                continue
        if values:
            observations.append((observed_on, values))
    if not observations:
        raise ProviderError("Japan MOF CSV returned no yield observations")

    observations.sort(key=lambda item: item[0])
    latest_date, latest_par = observations[-1]
    previous_par = observations[-2][1] if len(observations) > 1 else {}
    years = [_tenor_years(tenor) for tenor in DISPLAY_TENORS]
    latest_zero = bootstrap_zero_rates(latest_par, years)
    previous_zero = bootstrap_zero_rates(previous_par, years) if previous_par else {}
    points = [
        CurvePoint(
            tenor=tenor,
            years=year,
            yield_pct=latest_zero[year],
            change_bp=(latest_zero[year] - previous_zero[year]) * 100.0 if year in previous_zero else None,
        )
        for tenor, year in zip(DISPLAY_TENORS, years)
        if year in latest_zero
    ]
    return Curve(
        currency="JPY",
        name="JPY BOOTSTRAPPED ZERO CURVE",
        points=points,
        provider="Japan MOF",
        quality=DataQuality.DELAYED,
        timestamp=datetime.combine(latest_date, time(), timezone.utc),
        method="BOOTSTRAP / OFFICIAL CONSTANT-MATURITY JGB YIELDS",
    )


def _parse_mof_date(value: str) -> date | None:
    try:
        if "/" in value:
            return datetime.strptime(value, "%Y/%m/%d").date()
        if value.startswith("R"):
            year, month, day = (int(part) for part in value[1:].split("."))
            return date(2018 + year, month, day)
    except (TypeError, ValueError):
        return None
    return None


def _tenor_years(tenor: str) -> float:
    if tenor.endswith("M"):
        return int(tenor[:-1]) / 12.0
    return float(tenor[:-1])
