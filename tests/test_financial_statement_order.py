from __future__ import annotations

import asyncio
from datetime import date

from ajax_terminal.models.quote import FinancialPeriod, StatementType
from ajax_terminal.providers.mock import MockMarketProvider
from ajax_terminal.ui.screens.renderers import _humanize_metric
from ajax_terminal.utils.financials import (
    grouped_statement_metrics,
    is_expense_or_outflow_metric,
    ordered_statement_metrics,
)


def test_income_statement_uses_accounting_order_not_json_key_order() -> None:
    period = FinancialPeriod(
        "FY 2025",
        date(2025, 12, 31),
        {
            "basicAverageShares": 10.0,
            "taxProvision": 20.0,
            "netIncome": 80.0,
            "grossProfit": 300.0,
            "totalRevenue": 500.0,
            "operatingIncome": 120.0,
            "costOfRevenue": 200.0,
            "researchAndDevelopment": 50.0,
            "basicEPS": 8.0,
        },
    )

    assert ordered_statement_metrics([period], StatementType.INCOME) == [
        "totalRevenue",
        "costOfRevenue",
        "grossProfit",
        "researchAndDevelopment",
        "operatingIncome",
        "taxProvision",
        "netIncome",
        "basicEPS",
        "basicAverageShares",
    ]


def test_balance_and_cash_flow_follow_statement_sections() -> None:
    balance = FinancialPeriod(
        "FY 2025",
        None,
        {
            "stockholdersEquity": 40.0,
            "accountsPayableCurrent": 20.0,
            "totalAssets": 100.0,
            "cashAndCashEquivalents": 10.0,
        },
    )
    cash_flow = FinancialPeriod(
        "FY 2025",
        None,
        {
            "financingCashFlow": -20.0,
            "capitalExpenditure": -10.0,
            "operatingCashFlow": 50.0,
            "netIncome": 30.0,
        },
    )

    assert ordered_statement_metrics([balance], StatementType.BALANCE_SHEET) == [
        "cashAndCashEquivalents",
        "totalAssets",
        "accountsPayableCurrent",
        "stockholdersEquity",
    ]
    assert ordered_statement_metrics([cash_flow], StatementType.CASH_FLOW) == [
        "netIncome",
        "operatingCashFlow",
        "capitalExpenditure",
        "financingCashFlow",
    ]


def test_provider_balance_sheet_aliases_are_ordered_and_grouped_by_accounting_section() -> None:
    period = FinancialPeriod(
        "2025",
        None,
        {
            "totalAssets": 411.2,
            "totalCurrentAssets": 156.2,
            "cash": 53.5,
            "netReceivables": 45.2,
            "propertyPlantEquipment": 119.2,
            "totalLiabilitiesNetMinorityInterest": 263.1,
            "totalCurrentLiabilities": 111.0,
            "longTermDebt": 78.1,
            "totalStockholderEquity": 148.0,
        },
    )

    metrics = ordered_statement_metrics([period], StatementType.BALANCE_SHEET)
    groups = dict(grouped_statement_metrics(metrics, StatementType.BALANCE_SHEET))

    assert groups == {
        "ASSETS": [
            "cash",
            "netReceivables",
            "totalCurrentAssets",
            "propertyPlantEquipment",
            "totalAssets",
        ],
        "LIABILITIES": [
            "totalCurrentLiabilities",
            "longTermDebt",
            "totalLiabilitiesNetMinorityInterest",
        ],
        "SHAREHOLDERS' EQUITY": ["totalStockholderEquity"],
    }


def test_mock_balance_sheet_exposes_a_complete_statement() -> None:
    statements = asyncio.run(
        MockMarketProvider().financial_statements("TEST", StatementType.BALANCE_SHEET)
    )
    metrics = ordered_statement_metrics(statements.annual, StatementType.BALANCE_SHEET)
    groups = dict(grouped_statement_metrics(metrics, StatementType.BALANCE_SHEET))

    assert len(statements.annual[0].values) >= 40
    assert len(groups["ASSETS"]) >= 15
    assert len(groups["LIABILITIES"]) >= 14
    assert len(groups["SHAREHOLDERS' EQUITY"]) >= 6


def test_statement_labels_preserve_financial_acronyms() -> None:
    assert _humanize_metric("basicEPS") == "BASIC EPS"
    assert _humanize_metric("normalizedEBITDA") == "NORMALIZED EBITDA"
    assert _humanize_metric("netPPE") == "NET PPE"


def test_expenses_and_cash_outflows_are_classified_for_red_display() -> None:
    assert is_expense_or_outflow_metric("costOfRevenue", StatementType.INCOME)
    assert is_expense_or_outflow_metric("researchAndDevelopment", StatementType.INCOME)
    assert is_expense_or_outflow_metric("taxProvision", StatementType.INCOME)
    assert is_expense_or_outflow_metric("capitalExpenditure", StatementType.CASH_FLOW)
    assert is_expense_or_outflow_metric("cashDividendsPaid", StatementType.CASH_FLOW)
    assert not is_expense_or_outflow_metric("totalRevenue", StatementType.INCOME)
    assert not is_expense_or_outflow_metric("totalAssets", StatementType.BALANCE_SHEET)


def test_available_for_sale_oci_is_not_misclassified_as_sales_revenue() -> None:
    metric = "unrealizedGainLossOnAvailableForSaleSecurities"

    assert grouped_statement_metrics([metric], StatementType.INCOME) == [
        ("COMPREHENSIVE / SUPPLEMENTAL", [metric])
    ]
