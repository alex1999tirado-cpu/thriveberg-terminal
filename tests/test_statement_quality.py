from __future__ import annotations

import asyncio
from datetime import date

from ajax_terminal.models.quote import (
    DataQuality,
    FinancialPeriod,
    FinancialStatements,
    StatementType,
)
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore


class _StatementProvider:
    def __init__(self, name: str, line_count: int) -> None:
        self.name = name
        self.line_count = line_count
        self.calls = 0

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
    ) -> FinancialStatements:
        self.calls += 1
        values = {f"line{index}": float(index) for index in range(self.line_count)}
        return FinancialStatements(
            symbol=symbol,
            name="Test Company",
            statement_type=statement_type,
            annual=[FinancialPeriod("FY 2025", date(2025, 12, 31), values)],
            quarterly=[],
            currency="USD",
            provider=self.name,
            quality=DataQuality.DELAYED,
        )


def _service(tmp_path, providers: list[_StatementProvider]) -> MarketService:
    database = tmp_path / "statements.sqlite3"
    return MarketService(
        cache=SQLiteCache(database),
        watchlists=WatchlistStore(database),
        market_providers=providers,
    )


def test_sparse_statement_does_not_block_a_complete_provider(tmp_path) -> None:
    sparse = _StatementProvider("SPARSE", 3)
    complete = _StatementProvider("COMPLETE", 16)

    statements = asyncio.run(
        _service(tmp_path, [sparse, complete]).financial_statements(
            "AAPL", StatementType.INCOME
        )
    )

    assert statements.provider == "COMPLETE"
    assert sparse.calls == 1
    assert complete.calls == 1


def test_sparse_cached_statement_is_replaced_on_next_load(tmp_path) -> None:
    sparse = _StatementProvider("SPARSE", 3)
    first = asyncio.run(
        _service(tmp_path, [sparse]).financial_statements("AAPL", StatementType.INCOME)
    )
    complete = _StatementProvider("COMPLETE", 16)
    second = asyncio.run(
        _service(tmp_path, [complete]).financial_statements("AAPL", StatementType.INCOME)
    )

    assert first.provider == "SPARSE"
    assert second.provider == "COMPLETE"
    assert complete.calls == 1


def test_refresh_bypasses_a_complete_statement_cache(tmp_path) -> None:
    provider = _StatementProvider("COMPLETE", 16)
    service = _service(tmp_path, [provider])

    asyncio.run(service.financial_statements("AAPL", StatementType.INCOME))
    asyncio.run(service.financial_statements("AAPL", StatementType.INCOME))
    asyncio.run(
        service.financial_statements("AAPL", StatementType.INCOME, refresh=True)
    )

    assert provider.calls == 2
