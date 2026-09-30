from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QPushButton, QTableWidget, QTabWidget

from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_CYAN, AJAX_RED, AJAX_TEXT
from ajax_terminal.fundamentals_desktop import (
    FinancialAnalysisWorkspace,
    FinancialStatementsWorkspace,
    SecurityDescriptionData,
    SecurityDescriptionWorkspace,
)
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    EstimateSet,
    FinancialAnalysis,
    FinancialMetric,
)
from ajax_terminal.models.quote import (
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    PriceHistory,
    Quote,
    StatementType,
)


def test_financial_workspace_switches_frequency_and_emits_commands() -> None:
    app = QApplication.instance() or QApplication([])
    statements = FinancialStatements(
        symbol="AAPL",
        name="Apple Inc.",
        statement_type=StatementType.INCOME,
        annual=[FinancialPeriod("FY 2025", date(2025, 9, 27), {"totalRevenue": 416e9})],
        quarterly=[FinancialPeriod("Q1 2026", date(2025, 12, 27), {"totalRevenue": 94e9})],
        currency="USD",
        provider="TEST",
        quality=DataQuality.DELAYED,
    )
    workspace = FinancialStatementsWorkspace(statements)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    buttons = {button.text(): button for button in workspace.findChildren(QPushButton)}

    buttons["QUARTERLY"].click()
    buttons["2) BALANCE SHEET"].click()
    buttons["EXPORT XLSX"].click()
    app.processEvents()

    assert workspace.frequency == "QUARTERLY"
    assert workspace.table.horizontalHeaderItem(1).text() == "Q1 2026"
    assert commands == ["AAPL BS", "AAPL XLS"]
    workspace.close()


def test_statement_labels_stay_neutral_and_only_outflow_values_are_red() -> None:
    app = QApplication.instance() or QApplication([])
    statements = FinancialStatements(
        symbol="TEST",
        name="Test Company",
        statement_type=StatementType.INCOME,
        annual=[
            FinancialPeriod(
                "FY 2025",
                date(2025, 12, 31),
                {"totalRevenue": -10.0, "costOfRevenue": 4.0},
            )
        ],
        quarterly=[],
    )
    workspace = FinancialStatementsWorkspace(statements)
    app.processEvents()

    labels = {
        workspace.table.item(row, 0).text(): row
        for row in range(workspace.table.rowCount())
        if workspace.table.item(row, 0) is not None
    }
    revenue_row = labels["TOTAL REVENUE"]
    cost_row = labels["COST OF REVENUE"]
    assert workspace.table.item(revenue_row, 0).foreground().color().name() == AJAX_TEXT
    assert workspace.table.item(revenue_row, 1).foreground().color().name() == AJAX_AMBER
    assert workspace.table.item(cost_row, 0).foreground().color().name() == AJAX_TEXT
    assert workspace.table.item(cost_row, 1).foreground().color().name() == AJAX_RED
    workspace.close()


def test_financial_workspace_uses_one_selectable_table_scale() -> None:
    app = QApplication.instance() or QApplication([])
    app.setProperty("financialStatementUnit", "AUTO")
    statements = FinancialStatements(
        symbol="BN.PA",
        name="Danone S.A.",
        statement_type=StatementType.INCOME,
        annual=[
            FinancialPeriod(
                "FY 2025",
                date(2025, 12, 31),
                {
                    "totalRevenue": 27_300_000_000.0,
                    "sellingGeneralAndAdministration": 9_564_000_000.0,
                    "interestIncome": 301_000_000.0,
                    "basicEPS": 6.75,
                },
            )
        ],
        quarterly=[],
        currency="EUR",
        provider="TEST",
        quality=DataQuality.DELAYED,
    )
    workspace = FinancialStatementsWorkspace(statements)
    app.processEvents()

    labels = {
        workspace.table.item(row, 0).text(): row
        for row in range(workspace.table.rowCount())
        if workspace.table.item(row, 0) is not None
    }
    selector = workspace.findChild(QComboBox, "amberField")
    assert selector is workspace.unit_selector
    assert selector.currentText() == "AUTO"
    assert workspace.table.item(labels["TOTAL REVENUE"], 1).text() == "27,300.00"
    assert workspace.table.item(labels["SELLING GENERAL AND ADMINISTRATION"], 1).text() == "9,564.00"
    assert workspace.table.item(labels["INTEREST INCOME"], 1).text() == "301.00"
    assert workspace.table.item(labels["BASIC EPS"], 1).text() == "6.75"
    assert "UNITS: EUR MILLIONS (AUTO)" in workspace.source.text()

    selector.setCurrentText("BILLIONS")
    app.processEvents()
    assert workspace.table.item(labels["TOTAL REVENUE"], 1).text() == "27.30"
    assert workspace.table.item(labels["SELLING GENERAL AND ADMINISTRATION"], 1).text() == "9.56"
    assert workspace.table.item(labels["INTEREST INCOME"], 1).text() == "0.30"
    assert workspace.table.item(labels["BASIC EPS"], 1).text() == "6.75"
    assert "UNITS: EUR BILLIONS" in workspace.source.text()

    selector.setCurrentText("AUTO")
    workspace.close()


def test_balance_sheet_separates_assets_liabilities_and_equity_in_one_table() -> None:
    app = QApplication.instance() or QApplication([])
    statements = FinancialStatements(
        symbol="TEST",
        name="Test Company",
        statement_type=StatementType.BALANCE_SHEET,
        annual=[
            FinancialPeriod(
                "FY 2025",
                date(2025, 12, 31),
                {
                    "cashAndCashEquivalents": 20.0,
                    "totalAssets": 100.0,
                    "accountsPayableCurrent": 15.0,
                    "totalLiabilities": 60.0,
                    "stockholdersEquity": 40.0,
                },
            )
        ],
        quarterly=[],
    )
    workspace = FinancialStatementsWorkspace(statements)
    app.processEvents()

    labels = {
        workspace.table.item(row, 0).text(): row
        for row in range(workspace.table.rowCount())
        if workspace.table.item(row, 0) is not None
    }
    assert labels["ASSETS"] < labels["LIABILITIES"] < labels["SHAREHOLDERS' EQUITY"]
    assert workspace.table.item(labels["ASSETS"], 0).foreground().color().name() == AJAX_CYAN
    assert workspace.table.columnSpan(labels["LIABILITIES"], 0) == workspace.table.columnCount()
    assert workspace.table.item(labels["TOTAL LIABILITIES"], 1).foreground().color().name() == AJAX_AMBER
    workspace.close()


def test_description_uses_an_independently_scrollable_text_panel() -> None:
    app = QApplication.instance() or QApplication([])
    description_text = "Santander provides banking and financial services worldwide. " * 80
    data = SecurityDescriptionData(
        quote=Quote("SAN.MC", "Banco Santander", 12.5, currency="EUR"),
        history=PriceHistory("SAN.MC", "1Y", "1d", []),
        fundamentals=EquityFundamentals("SAN.MC", "Banco Santander"),
        profile=CompanyProfile(
            "SAN.MC",
            "Banco Santander, S.A.",
            exchange="BME",
            sector="Financial Services",
            country="Spain",
            description=description_text,
        ),
        analyst=AnalystConsensus("SAN.MC", "Banco Santander"),
        estimates=EstimateSet("SAN.MC", "Banco Santander", "EUR", []),
        news=[],
    )
    workspace = SecurityDescriptionWorkspace(data)
    workspace.resize(1200, 800)
    workspace.show()
    app.processEvents()

    description = workspace.findChild(QPlainTextEdit, "businessDescription")
    assert description is not None
    assert description.toPlainText() == description_text
    assert description.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
    assert description.verticalScrollBar().maximum() > 0
    workspace.close()


def test_rate_description_uses_percent_units_and_exposes_methodology_tab() -> None:
    app = QApplication.instance() or QApplication([])
    data = SecurityDescriptionData(
        quote=Quote(
            "ES30Y",
            "Spain Bono 30Y Yield",
            4.291,
            change=0.012,
            previous_close=4.279,
            currency="%",
            asset_class="RATE",
            provider="Banco de Espana + ECB",
            quality=DataQuality.DELAYED,
            estimated=True,
            methodology="Spain 10Y plus the ECB EUR AAA 30Y-minus-10Y slope.",
        ),
        history=PriceHistory("ES30Y", "1Y", "1d", [], "%", "UNAVAILABLE", DataQuality.UNAVAILABLE),
        fundamentals=EquityFundamentals("ES30Y", "Spain Bono 30Y Yield"),
        profile=CompanyProfile("ES30Y", "Spain Bono 30Y Yield"),
        analyst=AnalystConsensus("ES30Y", "Spain Bono 30Y Yield"),
        estimates=EstimateSet("ES30Y", "Spain Bono 30Y Yield", "%", []),
        news=[],
    )

    workspace = SecurityDescriptionWorkspace(data)
    workspace.show()
    app.processEvents()

    tabs = workspace.findChild(QTabWidget, "workspaceTabs")
    snapshot = workspace.findChild(QTableWidget, "rateSnapshot")
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["DES", "METHODOLOGY"]
    assert snapshot is not None
    assert snapshot.item(0, 1).text() == "4.291%*"
    assert snapshot.item(0, 3).text() == "+1.2bp"
    assert snapshot.item(3, 3).text() == "ESTIMATED *"
    workspace.close()


def test_financial_analysis_is_compact_and_omits_empty_provider_rows() -> None:
    app = QApplication.instance() or QApplication([])
    analysis = FinancialAnalysis(
        "SAN.MC",
        "Banco Santander, S.A.",
        "EUR",
        ["FY 2025", "FY 2024", "FY", "FY+1"],
        {
            "INCOME STATEMENT": [
                FinancialMetric("Revenue", 60e9, "FY 2025"),
                FinancialMetric("Revenue", 58e9, "FY 2024"),
                FinancialMetric("Net Income", 14e9, "FY 2025"),
                FinancialMetric("Revenue", 63e9, "FY", status="ESTIMATE"),
                FinancialMetric("Revenue", 66e9, "FY+1", status="ESTIMATE"),
                FinancialMetric("EBITDA", None, "FY+1", status="ESTIMATE"),
            ],
            "CASH FLOW": [FinancialMetric("Operating Cash Flow", 18e9, "FY 2025")],
            "BALANCE SHEET": [FinancialMetric("Cash", 179e9, "FY 2025")],
            "RETURNS / MARGINS": [
                FinancialMetric("Net Margin", 0.23, "FY 2025", unit="percent")
            ],
            "VALUATION": [FinancialMetric("P/E", 14.2, "FY 2025", unit="multiple")],
        },
        provider="TEST",
        quality=DataQuality.DELAYED,
    )
    workspace = FinancialAnalysisWorkspace(analysis)
    commands: list[str] = []
    workspace.command_requested.connect(commands.append)
    buttons = {button.text(): button for button in workspace.findChildren(QPushButton)}
    buttons["1) DES"].click()
    buttons["XLS"].click()
    app.processEvents()

    cells = [
        table.item(row, column).text()
        for table in workspace.findChildren(QTableWidget)
        for row in range(table.rowCount())
        for column in range(table.columnCount())
        if table.item(row, column) is not None
    ]
    assert "EBITDA" not in cells
    assert "N/A" not in cells
    assert commands == ["SAN.MC DES", "SAN.MC XLS"]
    workspace.close()
