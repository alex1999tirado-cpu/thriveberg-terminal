from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from ajax_terminal.models.equity import CorporateAction, CorporateActionType
from ajax_terminal.models.quote import DataQuality, PriceBar, PriceHistory
from ajax_terminal.services.corporate_actions_service import (
    apply_eligible_corporate_actions,
    load_portfolio_corporate_actions,
)
from ajax_terminal.storage.database import get_connection
from ajax_terminal.storage.workstation import PortfolioStore


def _action(
    identifier: str,
    action_type: CorporateActionType,
    effective: date,
    *,
    amount: float | None = None,
    currency: str = "USD",
    numerator: float | None = None,
    denominator: float | None = None,
) -> CorporateAction:
    return CorporateAction(
        identifier,
        "TEST",
        action_type,
        effective,
        amount=amount,
        currency=currency,
        numerator=numerator,
        denominator=denominator,
        provider="TEST PROVIDER",
        quality=DataQuality.DELAYED,
    )


class _Market:
    def __init__(
        self,
        actions: list[CorporateAction],
        histories: dict[str, PriceHistory] | None = None,
    ) -> None:
        self.actions = actions
        self.histories = histories or {}
        self.refreshes: list[bool] = []

    async def corporate_actions(self, symbol: str, *, refresh: bool = False):
        self.refreshes.append(refresh)
        return [item for item in self.actions if item.symbol == symbol]

    async def history(
        self,
        symbol: str,
        period: str = "1Y",
        interval: str | None = None,
        *,
        allow_mock: bool = False,
        refresh: bool = False,
    ) -> PriceHistory:
        assert not allow_mock
        return self.histories.get(
            symbol,
            PriceHistory(symbol, period, interval or "1d", [], provider="UNAVAILABLE"),
        )


def test_store_applies_split_once_and_preserves_total_book_value(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_trade(
        "TEST", "BUY", 10, 100, trade_date="2025-01-02",
        external_id="B1", source="TEST",
    )
    store.record_trade(
        "TEST", "BUY", 5, 80, trade_date="2025-02-15",
        external_id="B2", source="TEST",
    )
    before = store.positions()[0]

    first = store.apply_corporate_action(
        action_id="SPLIT-1",
        symbol="TEST",
        action_type="SPLIT",
        effective_date="2025-02-01",
        eligible_quantity=10,
        numerator=2,
        denominator=1,
        provider="TEST",
        quality="DELAYED",
    )
    duplicate = store.apply_corporate_action(
        action_id="SPLIT-1",
        symbol="TEST",
        action_type="SPLIT",
        effective_date="2025-02-01",
        eligible_quantity=10,
        numerator=2,
        denominator=1,
        provider="TEST",
        quality="DELAYED",
    )
    after = store.positions()[0]

    assert duplicate.id == first.id
    assert after.quantity == pytest.approx(25)
    assert after.quantity * after.cost_basis == pytest.approx(
        before.quantity * before.cost_basis
    )
    assert len(store.corporate_actions()) == 1


def test_service_replays_split_before_later_dividend_and_is_idempotent(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_cash_flow("DEPOSIT", 10_000, external_id="D1", source="TEST")
    store.record_trade(
        "TEST", "BUY", 10, 100, trade_date="2025-01-02",
        external_id="B1", source="TEST",
    )
    store.record_trade(
        "TEST", "BUY", 5, 80, trade_date="2025-02-15",
        external_id="B2", source="TEST",
    )
    actions = [
        _action(
            "SPLIT-1", CorporateActionType.SPLIT, date(2025, 2, 1),
            numerator=2, denominator=1,
        ),
        _action(
            "DIV-1", CorporateActionType.DIVIDEND, date(2025, 3, 1), amount=1.0,
        ),
    ]
    market = _Market(actions)

    preview = load_portfolio_corporate_actions(store, market=market, refresh=True)

    assert preview.eligible == 2
    assert preview.discovered == 2
    split = next(item for item in preview.candidates if item.action.action_id == "SPLIT-1")
    dividend = next(item for item in preview.candidates if item.action.action_id == "DIV-1")
    assert split.eligible_quantity == pytest.approx(10)
    assert split.position_delta == pytest.approx(10)
    assert dividend.eligible_quantity == pytest.approx(25)
    assert dividend.cash_amount == pytest.approx(25)
    assert market.refreshes == [True]

    first = apply_eligible_corporate_actions(store, preview)
    second_preview = load_portfolio_corporate_actions(store, market=market)
    second = apply_eligible_corporate_actions(store, second_preview)

    assert (first.applied, first.failed) == (2, 0)
    assert second.applied == 0
    assert store.positions()[0].quantity == pytest.approx(25)
    assert len(store.cash_flows()) == 2
    assert len(store.corporate_actions()) == 2
    assert second_preview.applied == 2


def test_split_restates_post_event_sale_cost_and_realized_pnl(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_trade(
        "TEST", "BUY", 10, 100, trade_date="2025-01-02",
        external_id="B1", source="TEST",
    )
    original_sale = store.record_trade(
        "TEST", "SELL", 5, 60, trade_date="2025-03-01",
        external_id="S1", source="TEST",
    )
    assert original_sale.realized_pnl == pytest.approx(-200)

    store.apply_corporate_action(
        action_id="SPLIT-1",
        symbol="TEST",
        action_type="SPLIT",
        effective_date="2025-02-01",
        eligible_quantity=10,
        numerator=2,
        denominator=1,
        provider="TEST",
        quality="DELAYED",
    )

    position = store.positions()[0]
    sale = next(item for item in store.transactions() if item.side == "SELL")
    assert position.quantity == pytest.approx(15)
    assert position.cost_basis == pytest.approx(50)
    assert sale.realized_pnl == pytest.approx(50)


def test_foreign_dividend_uses_observed_historical_fx(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_trade(
        "TEST", "BUY", 4, 100, currency="EUR", fx_rate=1.1,
        trade_date="2025-01-02", external_id="B1", source="TEST",
    )
    action = _action(
        "DIV-EUR", CorporateActionType.DIVIDEND, date(2025, 3, 1),
        amount=2.0, currency="EUR",
    )
    fx = PriceHistory(
        "EURUSD",
        "5Y",
        "1d",
        [
            PriceBar(
                datetime(2025, 2, 28, tzinfo=timezone.utc),
                1.2, 1.2, 1.2, 1.2, adjusted_close=1.2,
            )
        ],
        currency="USD",
        provider="TEST FX",
        quality=DataQuality.DELAYED,
    )

    preview = load_portfolio_corporate_actions(
        store,
        market=_Market([action], {"EURUSD": fx}),
    )
    candidate = preview.candidates[0]

    assert candidate.status == "ELIGIBLE"
    assert candidate.cash_amount == pytest.approx(8)
    assert candidate.fx_rate == pytest.approx(1.2)
    assert candidate.base_value == pytest.approx(9.6)


def test_manual_same_day_dividend_requires_review(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_trade(
        "TEST", "BUY", 4, 100, trade_date="2025-01-02",
        external_id="B1", source="TEST",
    )
    store.record_cash_flow(
        "DIVIDEND", 4, symbol="TEST", flow_date="2025-03-01",
        external_id="MANUAL-DIV", source="MANUAL",
    )
    action = _action(
        "DIV-1", CorporateActionType.DIVIDEND, date(2025, 3, 1), amount=1,
    )

    preview = load_portfolio_corporate_actions(store, market=_Market([action]))

    assert preview.eligible == 0
    assert preview.review == 1
    assert "POSSIBLE MANUAL DIVIDEND" in preview.candidates[0].notes


def test_schema_creates_corporate_action_audit_table(tmp_path) -> None:
    database = tmp_path / "portfolio.sqlite3"
    with get_connection(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(portfolio_corporate_actions)")
        }

    assert {
        "portfolio", "action_id", "action_type", "eligible_quantity",
        "position_delta", "cash_amount", "fx_rate", "applied_at",
    } <= columns
