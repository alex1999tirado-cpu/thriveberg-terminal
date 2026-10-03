from __future__ import annotations

import asyncio

import pytest

from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import DataQuality, StatementType
from ajax_terminal.providers.mock import MockMarketProvider
from ajax_terminal.services.market_service import MarketService, _quote_from_dict, _quote_to_dict
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore


def test_ndx_is_nasdaq_100() -> None:
    ndx = INSTRUMENT_REGISTRY.get("NDX")

    assert ndx is not None
    assert ndx.name == "Nasdaq-100"
    assert ndx.provider_symbol == "^NDX"
    assert "Composite" not in ndx.name


def test_registry_has_complete_unique_g10_matrix() -> None:
    pairs = INSTRUMENT_REGISTRY.fx_pairs()
    combinations = {frozenset((item.symbol[:3], item.symbol[3:])) for item in pairs}

    assert len(pairs) == 45
    assert len(combinations) == 45
    assert INSTRUMENT_REGISTRY.get("EURJPY") is not None
    assert INSTRUMENT_REGISTRY.get("GBPJPY") is not None


def test_registry_market_coverage_counts() -> None:
    assert len(INSTRUMENT_REGISTRY.list(AssetClass.INDEX)) == 27
    assert len(INSTRUMENT_REGISTRY.list(AssetClass.RATE)) == 39
    assert len(INSTRUMENT_REGISTRY.list(AssetClass.COMMODITY)) == 17
    assert len(INSTRUMENT_REGISTRY.list(AssetClass.BOND)) == 14
    assert INSTRUMENT_REGISTRY.asset_class("INDEX") == AssetClass.INDEX
    assert INSTRUMENT_REGISTRY.asset_class("RATES") == AssetClass.RATE
    assert INSTRUMENT_REGISTRY.asset_class("CMDTY") == AssetClass.COMMODITY


def test_registry_centralizes_government_and_corporate_fixed_income() -> None:
    assert len(INSTRUMENT_REGISTRY.government_benchmarks()) == 39
    assert len(INSTRUMENT_REGISTRY.credit_benchmarks()) == 6
    assert len(INSTRUMENT_REGISTRY.corporate_bonds()) == 8
    assert len(INSTRUMENT_REGISTRY.list_filter("GOVT") or []) == 39
    assert len(INSTRUMENT_REGISTRY.list_filter("CORP") or []) == 14
    assert INSTRUMENT_REGISTRY.get("AAPL44").identifier == "US037833AT77"  # type: ignore[union-attr]
    assert INSTRUMENT_REGISTRY.get("037833AT7").symbol == "AAPL44"  # type: ignore[union-attr]
    assert INSTRUMENT_REGISTRY.get("USCORPIG").instrument_type == "CREDIT_BENCHMARK"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("symbol", "asset_class"),
    [
        ("SPX", AssetClass.INDEX),
        ("SX5E", AssetClass.INDEX),
        ("IBEX", AssetClass.INDEX),
        ("NDX", AssetClass.INDEX),
        ("EURJPY", AssetClass.FX),
        ("GBPJPY", AssetClass.FX),
        ("US10Y", AssetClass.RATE),
        ("DE10Y", AssetClass.RATE),
        ("AAPL", AssetClass.EQUITY),
        ("MSFT", AssetClass.EQUITY),
        ("SAN.MC", AssetClass.EQUITY),
    ],
)
def test_required_instruments_resolve(symbol: str, asset_class: AssetClass) -> None:
    assert INSTRUMENT_REGISTRY.resolve(symbol).asset_class == asset_class


def test_required_instruments_load_through_service(tmp_path) -> None:
    async def run() -> None:
        database = tmp_path / "coverage.sqlite3"
        service = MarketService(
            cache=SQLiteCache(database),
            watchlists=WatchlistStore(database),
            market_providers=[],
        )
        symbols = ["SPX", "SX5E", "IBEX", "NDX", "EURJPY", "GBPJPY", "US10Y", "DE10Y", "AAPL", "MSFT", "SAN.MC"]
        for symbol in symbols:
            quote, history = await asyncio.gather(service.quote(symbol), service.history(symbol, "1M"))
            assert quote.symbol == symbol
            assert quote.quality == DataQuality.UNAVAILABLE
            assert history.bars == []
            assert history.quality == DataQuality.UNAVAILABLE
        for symbol in ["AAPL", "MSFT", "SAN.MC"]:
            for statement_type in StatementType:
                statements = await service.financial_statements(symbol, statement_type)
                assert statements.annual == []
                assert statements.quarterly == []
                assert statements.quality == DataQuality.UNAVAILABLE

    asyncio.run(run())


def test_stale_mock_data_remains_explicitly_mock() -> None:
    quote = asyncio.run(MockMarketProvider().quote("SPX"))

    restored = _quote_from_dict(_quote_to_dict(quote), cached_quality=True)

    assert restored.quality == DataQuality.MOCK
