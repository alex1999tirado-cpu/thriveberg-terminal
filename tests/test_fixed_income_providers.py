from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.banco_de_espana import BancoDeEspanaProvider
from ajax_terminal.providers.ecb import parse_ecb_curve
from ajax_terminal.providers.fred_credit import FredCreditProvider
from ajax_terminal.providers.japan_mof import parse_jgb_curve
from ajax_terminal.providers.treasury import parse_treasury_curve
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache


def test_banco_de_espana_quote_is_a_percent_yield_with_daily_bp_change(monkeypatch) -> None:
    provider = BancoDeEspanaProvider()

    async def observations(_symbol: str, _api_range: str):
        return [
            (datetime(2026, 9, 24, 8, 15, tzinfo=timezone.utc), 3.212),
            (datetime(2026, 9, 25, 8, 15, tzinfo=timezone.utc), 3.276),
        ]

    monkeypatch.setattr(provider, "_observations", observations)
    quote = asyncio.run(provider.quote("ES2Y"))

    assert quote.price == 3.276
    assert round((quote.change or 0) * 100.0, 6) == 6.4
    assert quote.currency == "%"
    assert quote.asset_class == "RATE"
    assert quote.provider == "Banco de Espana"
    assert quote.quality == DataQuality.DELAYED


def test_treasury_xml_normalization_builds_curve_and_daily_changes() -> None:
    payload = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
          xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE>2026-09-24T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.00</d:BC_2YEAR><d:BC_10YEAR>4.20</d:BC_10YEAR>
      </m:properties></content></entry>
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE>2026-09-25T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.03</d:BC_2YEAR><d:BC_10YEAR>4.18</d:BC_10YEAR>
      </m:properties></content></entry>
    </feed>"""

    curve = parse_treasury_curve(payload)

    assert curve.name == "USD TREASURY PAR YIELD CURVE"
    assert curve.quality == DataQuality.DELAYED
    assert curve.point("2Y").yield_pct == 4.03  # type: ignore[union-attr]
    assert round(curve.point("2Y").change_bp, 6) == 3.0  # type: ignore[union-attr]
    assert round(curve.point("10Y").change_bp, 6) == -2.0  # type: ignore[union-attr]


def test_credit_benchmark_combines_effective_yield_and_oas(monkeypatch) -> None:
    async def observations(series_id: str, _start: str):
        from datetime import date

        if series_id.endswith("EY"):
            return [(date(2026, 9, 24), 5.50), (date(2026, 9, 25), 5.57)]
        return [(date(2026, 9, 24), 0.85), (date(2026, 9, 25), 0.88)]

    monkeypatch.setattr("ajax_terminal.providers.fred_credit.fred_observations", observations)
    benchmark = asyncio.run(FredCreditProvider().benchmark("USCORPIG"))

    assert benchmark.effective_yield_pct == 5.57
    assert round(benchmark.yield_change_bp or 0, 6) == 7.0
    assert benchmark.oas_bp == 88.0
    assert round(benchmark.oas_change_bp or 0, 6) == 3.0
    assert benchmark.quality == DataQuality.DELAYED


def test_curve_can_suppress_mock_fallback(tmp_path) -> None:
    service = MarketService(
        cache=SQLiteCache(tmp_path / "curve.sqlite3"),
        market_providers=[],
    )

    curve = asyncio.run(service.curve("JPY", allow_mock=False))

    assert curve.name == "JPY REFERENCE CURVE"
    assert curve.provider == "UNAVAILABLE"
    assert curve.quality == DataQuality.UNAVAILABLE
    assert curve.points == []


def test_japan_mof_curve_is_bootstrapped_from_official_nodes() -> None:
    payload = """Interest Rate,,,,,,,,,,,,,,,(Unit : %)
Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y
2026/9/23,1.60,1.80,1.95,2.10,2.25,2.35,2.45,2.55,2.65,2.75,3.10,3.35,3.55,3.70,3.80
2026/9/24,1.62,1.82,1.97,2.12,2.27,2.37,2.47,2.57,2.67,2.77,3.12,3.37,3.57,3.72,3.82
"""

    curve = parse_jgb_curve(payload)

    assert curve.name == "JPY BOOTSTRAPPED ZERO CURVE"
    assert curve.provider == "Japan MOF"
    assert curve.quality == DataQuality.DELAYED
    assert curve.method.startswith("BOOTSTRAP")
    assert curve.point("1M") is not None
    assert curve.point("10Y") is not None
    assert curve.point("10Y").change_bp is not None  # type: ignore[union-attr]


def test_ecb_curve_uses_distinct_official_spot_rate_nodes() -> None:
    payload = """KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE
YC.TEST.10Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_10Y,2026-09-23,3.5236609264
YC.TEST.10Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_10Y,2026-09-24,3.5661681763
YC.TEST.3M,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_3M,2026-09-23,2.6414499631
YC.TEST.3M,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_3M,2026-09-24,2.6590123456
YC.TEST.30Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_30Y,2026-09-23,3.7627496552
YC.TEST.30Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_30Y,2026-09-24,3.7442467417
"""

    curve = parse_ecb_curve(payload)

    assert curve.name == "EUR AAA ZERO-COUPON CURVE"
    assert curve.provider == "ECB"
    assert curve.method.startswith("ECB SVENSSON")
    assert curve.point("3M").yield_pct == 2.6590123456  # type: ignore[union-attr]
    assert curve.point("10Y").yield_pct == 3.5661681763  # type: ignore[union-attr]
    assert curve.point("30Y").yield_pct == 3.7442467417  # type: ignore[union-attr]
    assert curve.point("3M").yield_pct != curve.point("10Y").yield_pct  # type: ignore[union-attr]


def test_single_real_benchmark_stays_partial_when_official_feed_fails(tmp_path) -> None:
    class TenYearOnlyProvider:
        name = "TEST BENCHMARK"

        async def quote(self, symbol: str) -> Quote:
            if symbol != "JP10Y":
                raise ProviderError("not available")
            return Quote(
                symbol=symbol,
                name="Japan 10Y",
                price=2.94,
                change=0.02,
                previous_close=2.92,
                currency="%",
                asset_class="RATES",
                provider=self.name,
                quality=DataQuality.DELAYED,
                timestamp=datetime(2026, 9, 24, tzinfo=timezone.utc),
            )

    service = MarketService(
        cache=SQLiteCache(tmp_path / "benchmark-curve.sqlite3"),
        market_providers=[TenYearOnlyProvider()],
    )

    curve = asyncio.run(service.curve("JPY", allow_mock=False))

    assert curve.quality == DataQuality.DELAYED
    assert curve.provider == "TEST BENCHMARK"
    assert curve.method == "PARTIAL / SINGLE OBSERVED BENCHMARK JP10Y / NO EXTRAPOLATION"
    assert curve.point("10Y") is not None
    assert curve.point("1M") is None
    assert curve.point("30Y") is None
