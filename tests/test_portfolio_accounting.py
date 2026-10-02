from __future__ import annotations

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.services import workstation_service
from ajax_terminal.services.portfolio_import_service import (
    apply_broker_import,
    preview_broker_csv,
)
from ajax_terminal.services.workstation_service import load_portfolio
from ajax_terminal.storage.database import get_connection
from ajax_terminal.storage.workstation import PortfolioStore
from ajax_terminal.workstation_desktop import PortfolioWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_trade_ledger_uses_weighted_native_and_base_costs(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_cash_flow(
        "DEPOSIT", 5_000, currency="EUR", fx_rate=1.10,
        flow_date="2026-08-31", external_id="cash-1", source="TEST",
    )
    store.record_trade(
        "ASML.AS", "BUY", 10, 100, fees=10, currency="EUR", fx_rate=1.10,
        trade_date="2026-09-01", external_id="trade-1", source="TEST",
    )
    store.record_trade(
        "ASML.AS", "BUY", 10, 120, currency="EUR", fx_rate=1.20,
        trade_date="2026-09-02", external_id="trade-2", source="TEST",
    )
    sale = store.record_trade(
        "ASML.AS", "SELL", 5, 150, fees=5, currency="EUR", fx_rate=1.15,
        trade_date="2026-09-03", external_id="trade-3", source="TEST",
    )
    store.record_cash_flow(
        "DIVIDEND", 30, currency="EUR", fx_rate=1.10, symbol="ASML.AS",
        flow_date="2026-09-04", external_id="cash-2", source="TEST",
    )
    store.record_cash_flow(
        "TAX", 5, currency="EUR", fx_rate=1.10, symbol="ASML.AS",
        flow_date="2026-09-04", external_id="cash-3", source="TEST",
    )

    position = store.positions()[0]
    assert position.quantity == pytest.approx(15)
    assert position.cost_basis == pytest.approx(110.5)
    assert position.cost_basis_base == pytest.approx(127.55)
    assert sale.realized_pnl == pytest.approx(219.0)
    assert store.cash_balance() == pytest.approx(3_833.25)
    assert store.net_external_flow() == pytest.approx(5_500.0)
    assert store.invested_capital() == pytest.approx(2_551.0)


def test_trade_ledger_is_idempotent_and_rejects_overselling(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    first = store.record_trade(
        "AAPL", "BUY", 4, 200, external_id="broker-42", source="IBKR",
    )
    duplicate = store.record_trade(
        "AAPL", "BUY", 4, 200, external_id="broker-42", source="IBKR",
    )

    assert duplicate.id == first.id
    assert len(store.transactions()) == 1
    assert store.positions()[0].quantity == 4
    assert store.has_transaction_history("AAPL")
    assert not store.has_transaction_history("MSFT")

    with pytest.raises(ValueError, match="available quantity is 4"):
        store.record_trade("AAPL", "SELL", 5, 210)

    assert len(store.transactions()) == 1
    assert store.positions()[0].quantity == 4


def test_schema_migrates_existing_portfolio_positions_without_data_loss(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE portfolio_positions (
                portfolio TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                cost_basis REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (portfolio, symbol)
            )
            """
        )
        connection.execute(
            "INSERT INTO portfolio_positions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MAIN", "AAPL", 2.0, 150.0, "USD", 0, "2026-09-01T00:00:00Z"),
        )

    with get_connection(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(portfolio_positions)")
        }
        row = connection.execute(
            "SELECT symbol, quantity, cost_basis, cost_basis_base FROM portfolio_positions"
        ).fetchone()

    assert "cost_basis_base" in columns
    assert tuple(row) == ("AAPL", 2.0, 150.0, None)


def test_degiro_csv_preview_and_apply_are_idempotent(tmp_path) -> None:
    source = tmp_path / "degiro_activity.csv"
    source.write_text(
        "Fecha;Producto;Accion;Cantidad;Precio;Comision;Divisa;Tipo de cambio;Referencia;Importe\n"
        "01/09/2026;ASML.AS;Compra;2;650,50;1,50;EUR;1,10;T1;\n"
        "02/09/2026;ASML.AS;Venta;1;700,00;1,00;EUR;1,11;T2;\n"
        "03/09/2026;;Dividendo;;;;EUR;1,10;C1;10,00\n",
        encoding="utf-8",
    )
    preview = preview_broker_csv(source, default_currency="USD")
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")

    assert preview.broker == "DEGIRO"
    assert preview.ready_count == 3
    assert preview.error_count == 0
    assert preview.rows[0].price == pytest.approx(650.5)

    first = apply_broker_import(preview, "MAIN", store)
    second = apply_broker_import(preview, "MAIN", store)

    assert (first.imported, first.duplicates, first.failed) == (3, 0, 0)
    assert (second.imported, second.duplicates, second.failed) == (0, 3, 0)
    assert store.positions()[0].quantity == 1
    assert len(store.transactions()) == 2
    assert len(store.cash_flows()) == 1


def test_import_applies_descending_csv_in_accounting_order(tmp_path) -> None:
    source = tmp_path / "broker.csv"
    source.write_text(
        "Date,Symbol,Action,Quantity,Price,Fees,Currency,ID\n"
        "2026-09-02,AAPL,SELL,2,110,1,USD,S1\n"
        "2026-09-01,AAPL,BUY,5,100,1,USD,B1\n",
        encoding="utf-8",
    )
    preview = preview_broker_csv(source)
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")

    result = apply_broker_import(preview, "MAIN", store)

    assert (result.imported, result.failed) == (2, 0)
    assert store.positions()[0].quantity == 3
    assert store.transactions()[0].side == "SELL"


def test_foreign_currency_import_requires_an_explicit_fx_rate(tmp_path) -> None:
    source = tmp_path / "foreign.csv"
    source.write_text(
        "Date,Symbol,Action,Quantity,Price,Currency\n"
        "2026-09-01,ASML.AS,BUY,2,650,EUR\n",
        encoding="utf-8",
    )

    preview = preview_broker_csv(source, default_currency="USD")

    assert preview.ready_count == 0
    assert "missing FX rate for EUR to USD" in preview.rows[0].message


def test_ibkr_and_trading212_native_headers_are_normalized(tmp_path) -> None:
    ibkr = tmp_path / "ibkr-flex.csv"
    ibkr.write_text(
        "ClientAccountID,AssetClass,TradeDate,Symbol,Buy/Sell,Quantity,TradePrice,IBCommission,CurrencyPrimary,TradeID\n"
        "U123,STK,09/01/2026,AAPL,BOT,10,200.00,-1.25,USD,IB-1\n",
        encoding="utf-8",
    )
    trading212 = tmp_path / "trading212.csv"
    trading212.write_text(
        "Action,Time,Ticker,No. of shares,Price / share,Currency (Price / share),Exchange rate,Currency conversion fee,Stamp duty reserve tax,ID\n"
        "Market buy,2026-09-01 14:30:00,MSFT,2,510.50,USD,1,1.25,0.50,T212-1\n",
        encoding="utf-8",
    )

    ibkr_preview = preview_broker_csv(ibkr)
    trading212_preview = preview_broker_csv(trading212)

    assert ibkr_preview.broker == "IBKR"
    assert ibkr_preview.rows[0].external_id == "U123:IB-1"
    assert ibkr_preview.rows[0].fees == pytest.approx(1.25)
    assert ibkr_preview.rows[0].currency == "USD"
    assert trading212_preview.broker == "TRADING 212"
    assert trading212_preview.rows[0].action == "BUY"
    assert trading212_preview.rows[0].price == pytest.approx(510.5)
    assert trading212_preview.rows[0].fees == pytest.approx(1.75)


def test_degiro_signed_quantity_can_supply_missing_action(tmp_path) -> None:
    source = tmp_path / "degiro_transactions.csv"
    source.write_text(
        "Fecha;Producto;Número;Precio;Divisa;Tipo de cambio;Referencia\n"
        "01/09/2026;ASML.AS;-2;650,50;EUR;1,10;D1\n",
        encoding="utf-8",
    )

    preview = preview_broker_csv(source, default_currency="USD")

    assert preview.broker == "DEGIRO"
    assert preview.ready_count == 1
    assert preview.rows[0].action == "SELL"
    assert preview.rows[0].quantity == pytest.approx(2)


def test_portfolio_load_reports_cash_pnl_and_attribution(tmp_path, monkeypatch) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.record_cash_flow("DEPOSIT", 2_000, external_id="D1", source="TEST")
    store.record_trade(
        "AAPL", "BUY", 10, 100, fees=10,
        trade_date="2026-09-01", external_id="B1", source="TEST",
    )
    store.record_cash_flow(
        "DIVIDEND", 20, symbol="AAPL",
        flow_date="2026-09-20", external_id="DIV1", source="TEST",
    )
    store.record_cash_flow(
        "TAX", 3, symbol="AAPL",
        flow_date="2026-09-20", external_id="TAX1", source="TEST",
    )

    async def quotes(_service, symbols, allow_mock=False):
        assert symbols == ["AAPL"]
        assert not allow_mock
        return [
            Quote(
                "AAPL", "Apple Inc.", 120.0, currency="USD",
                provider="TEST", quality=DataQuality.REALTIME,
            )
        ]

    monkeypatch.setattr(workstation_service.MarketService, "bulk_quotes", quotes)

    model = load_portfolio(("MAIN",), store)

    assert model.market_value == pytest.approx(1_200)
    assert model.book_value == pytest.approx(1_010)
    assert model.cash_balance == pytest.approx(1_007)
    assert model.net_asset_value == pytest.approx(2_207)
    assert model.unrealized_pnl == pytest.approx(190)
    assert model.income == pytest.approx(20)
    assert model.profit_loss == pytest.approx(207)
    assert model.cash_expenses == pytest.approx(-3)
    assert model.net_external_flow == pytest.approx(2_000)
    assert model.fees == pytest.approx(10)
    assert model.total_return_percent == pytest.approx(207 / 1_010 * 100)
    assert model.net_asset_value == pytest.approx(
        store.net_external_flow() + model.profit_loss
    )
    assert model.attribution[0].symbol == "AAPL"
    assert model.attribution[0].cash_expenses == pytest.approx(-3)
    assert model.attribution[0].total_pnl == pytest.approx(207)


def test_portfolio_workspace_exposes_accounting_and_import_tabs(tmp_path) -> None:
    app = _app()
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    model = load_portfolio(("MAIN",), store)
    workspace = PortfolioWorkspace(model, store)
    source = tmp_path / "preview.csv"
    source.write_text(
        "Date,Symbol,Action,Quantity,Price,Currency,ID\n"
        "2026-09-01,AAPL,BUY,1,200,USD,B1\n",
        encoding="utf-8",
    )

    workspace._set_import_preview(preview_broker_csv(source))
    tabs = workspace.findChild(QTabWidget)

    assert tabs is not None
    assert tabs.count() == 10
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "1) HOLDINGS",
        "2) ATTRIBUTION",
        "3) TRANSACTIONS",
        "4) CASH LEDGER",
        "5) IMPORT PREVIEW",
        "6) RISK",
        "7) FACTORS",
        "8) CORRELATION",
        "9) STRESS",
        "10) CORP ACTIONS",
    ]
    assert tabs.currentIndex() == 4
    assert workspace.apply_import_button.isEnabled()
    assert workspace.import_table.item(0, 1).text() == "READY"

    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    workspace.new_name.setText("EURO FUND")
    workspace.new_base.setCurrentText("EUR")
    workspace._create()
    assert store.base_currency("EURO FUND") == "EUR"
    assert commands[-1] == "PORT EURO FUND"
    workspace.risk_benchmark.setCurrentText("ACWI")
    workspace.risk_period.setCurrentText("2Y")
    workspace._calculate_risk()
    assert commands[-1] == "PORT MAIN RISK ACWI 2Y"
    workspace._sync_actions()
    assert commands[-1] == "PORT MAIN ACTIONS REFRESH"
    workspace.close()
    app.processEvents()


def test_named_portfolio_risk_request_preserves_benchmark_and_period(tmp_path, monkeypatch) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.create("EURO FUND", "EUR")
    store.upsert("ASML.AS", 2, 600, "EUR", "EURO FUND")

    async def quotes(_service, symbols, allow_mock=False):
        assert symbols == ["ASML.AS"]
        assert not allow_mock
        return [
            Quote(
                "ASML.AS", "ASML Holding", 700.0, currency="EUR",
                provider="TEST", quality=DataQuality.DELAYED,
            )
        ]

    captured: dict[str, object] = {}
    sentinel = object()

    def risk(positions, **kwargs):
        captured["positions"] = positions
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(workstation_service.MarketService, "bulk_quotes", quotes)
    monkeypatch.setattr(workstation_service, "load_portfolio_risk", risk)

    model = load_portfolio(("EURO", "FUND", "RISK", "ACWI", "2Y"), store)

    assert model.name == "EURO FUND"
    assert model.risk is sentinel
    assert model.risk_benchmark == "ACWI"
    assert model.risk_period == "2Y"
    assert captured["benchmark"] == "ACWI"
    assert captured["period"] == "2Y"
    assert captured["base_currency"] == "EUR"
    positions = captured["positions"]
    assert positions[0].symbol == "ASML.AS"


def test_named_portfolio_actions_request_preserves_name_and_mode(tmp_path, monkeypatch) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.create("EURO FUND", "EUR")
    captured: list[tuple[str, bool]] = []
    sentinel = object()

    def actions(_store, name, *, refresh=False):
        captured.append((name, refresh))
        return sentinel

    monkeypatch.setattr(workstation_service, "load_portfolio_corporate_actions", actions)

    model = load_portfolio(("EURO", "FUND", "ACTIONS", "REFRESH"), store)

    assert model.name == "EURO FUND"
    assert model.corporate_actions is sentinel
    assert captured == [("EURO FUND", True)]
