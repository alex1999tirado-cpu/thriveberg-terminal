from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget

from ajax_terminal.data_quality_desktop import DataQualityWorkspace
from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.services.data_quality_service import (
    CacheDomainStatus,
    DataQualityDashboard,
    ProviderCapability,
    ProviderHealthRow,
    ProviderProbe,
    QuoteComparison,
    cache_inventory,
    compare_quote_providers,
    load_data_quality_dashboard,
    run_provider_probes,
)
from ajax_terminal.storage.cache import SQLiteCache
from ajax_terminal.storage.data_quality import DataQualityStore
from ajax_terminal.storage.database import get_connection


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _QuoteProvider:
    def __init__(
        self,
        name: str,
        price: float | None,
        *,
        configured: bool = True,
        error: str = "",
    ) -> None:
        self.name = name
        self.price = price
        self.configured = configured
        self.error = error

    async def quote(self, symbol: str) -> Quote:
        if self.error:
            raise RuntimeError(self.error)
        return Quote(
            symbol,
            symbol,
            self.price,
            currency="USD",
            provider=self.name,
            quality=DataQuality.DELAYED,
        )


def test_data_quality_store_preserves_success_and_failure_history(tmp_path) -> None:
    store = DataQualityStore(tmp_path / "quality.sqlite3")
    successful = store.record(
        "Provider A",
        "Quotes",
        status="AVAILABLE",
        quality=DataQuality.REALTIME,
        latency_ms=12.5,
    )
    failed = store.record(
        "Provider A",
        "Quotes",
        status="FAILED",
        latency_ms=40.0,
        message="temporary failure",
    )

    assert successful.success_count == 1
    assert successful.failure_count == 0
    assert failed.status == "FAILED"
    assert failed.success_count == 1
    assert failed.failure_count == 1
    assert failed.last_success_at is not None
    assert failed.last_failure_at is not None
    assert failed.message == "temporary failure"


def test_cache_inventory_groups_fresh_and_stale_entries(tmp_path) -> None:
    database = tmp_path / "cache.sqlite3"
    cache = SQLiteCache(database)
    cache.set_json(
        "quote:AAPL",
        {"provider": "Provider A", "quality": "DELAYED", "price": 100},
        600,
    )
    cache.set_json(
        "quote:MSFT",
        {"provider": "Provider B", "quality": "UNAVAILABLE"},
        600,
    )
    cache.set_json(
        "news:v3:TOP",
        [{"provider": "RSS", "quality": "CACHED"}],
        600,
    )
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE cache SET expires_at = ? WHERE key = ?",
            (time.time() - 1, "quote:MSFT"),
        )
        connection.commit()

    rows = {row.domain: row for row in cache_inventory(database)}

    assert rows["QUOTES"].total == 2
    assert rows["QUOTES"].fresh == 1
    assert rows["QUOTES"].stale == 1
    assert rows["QUOTES"].unavailable == 1
    assert rows["QUOTES"].providers == ("PROVIDER A", "PROVIDER B")
    assert rows["NEWS"].fresh == 1


def test_parallel_provider_probes_record_success_failure_and_redact_secrets(tmp_path) -> None:
    store = DataQualityStore(tmp_path / "quality.sqlite3")

    async def good() -> Quote:
        return Quote(
            "SPY",
            "SPY",
            500.0,
            provider="GOOD",
            quality=DataQuality.DELAYED,
        )

    async def bad() -> Quote:
        raise RuntimeError("https://provider.example/quote?token=TOPSECRET")

    results = asyncio.run(
        run_provider_probes(
            (
                ProviderProbe("GOOD", "MARKET", good),
                ProviderProbe("BAD", "MARKET", bad),
            ),
            store,
        )
    )

    by_provider = {row.provider: row for row in results}
    assert by_provider["GOOD"].status == "AVAILABLE"
    assert by_provider["GOOD"].quality == DataQuality.DELAYED
    assert by_provider["BAD"].status == "FAILED"
    assert "TOPSECRET" not in by_provider["BAD"].message
    assert "provider.example" in by_provider["BAD"].message


def test_quote_comparison_uses_cross_source_median_and_keeps_failures(tmp_path) -> None:
    rows = asyncio.run(
        compare_quote_providers(
            "AAPL",
            (
                _QuoteProvider("ONE", 100.0),
                _QuoteProvider("TWO", 102.0),
                _QuoteProvider("OFF", None, configured=False),
                _QuoteProvider("BAD", None, error="down"),
            ),
            DataQualityStore(tmp_path / "quality.sqlite3"),
        )
    )
    by_provider = {row.provider: row for row in rows}

    assert round(by_provider["ONE"].difference_bp or 0, 1) == -99.0
    assert round(by_provider["TWO"].difference_bp or 0, 1) == 99.0
    assert by_provider["ONE"].alignment == "DIVERGENT"
    assert by_provider["TWO"].alignment == "DIVERGENT"
    assert by_provider["OFF"].status == "DISABLED"
    assert by_provider["BAD"].status == "FAILED"


def test_dashboard_builds_without_network_or_default_security(tmp_path) -> None:
    database = tmp_path / "quality.sqlite3"
    store = DataQualityStore(database)
    store.record("YAHOO FINANCE", "MARKET", status="AVAILABLE", quality=DataQuality.DELAYED)

    dashboard = load_data_quality_dashboard(
        (),
        store=store,
        cache_path=database,
        probes=(),
    )

    assert dashboard.symbol == ""
    assert dashboard.available_count == 1
    assert dashboard.comparisons == ()
    assert len(dashboard.providers) >= 10


def test_data_quality_workspace_exposes_all_views_and_commands() -> None:
    app = _app()
    now = datetime.now(timezone.utc)
    capability = ProviderCapability(
        "TEST", "MARKET DATA", "MARKET", True, "PUBLIC", ("QUOTES", "HISTORY")
    )
    model = DataQualityDashboard(
        providers=(
            ProviderHealthRow(
                "TEST",
                "MARKET DATA",
                "MARKET",
                True,
                "PUBLIC",
                "AVAILABLE",
                DataQuality.DELAYED,
                10.0,
                1,
                0,
                now,
                "",
            ),
        ),
        cache=(CacheDomainStatus("QUOTES", 1, 1, 0, 0, 0, now, now, ("TEST",)),),
        capabilities=(capability,),
        comparisons=(
            QuoteComparison(
                "TEST", "AVAILABLE", 100.0, "USD", DataQuality.DELAYED, now, 0.0, 10.0
            ),
        ),
        symbol="AAPL",
        generated_at=now,
    )
    workspace = DataQualityWorkspace(model)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)

    assert workspace.tabs.count() == 4
    assert len(workspace.findChildren(QTableWidget)) == 4
    workspace._probe()
    workspace.symbol.setText("MSFT")
    workspace._compare()
    workspace._open_fields(0, 0)

    assert commands == ["DQM AAPL PROBE", "DQM MSFT", "AAPL FLDS PRICE"]
    workspace.close()
    app.processEvents()
