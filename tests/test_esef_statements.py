from __future__ import annotations

from ajax_terminal.models.quote import StatementType
from ajax_terminal.providers.esef_statements import (
    _ESEFReport,
    _metric_section,
    normalize_esef_xbrl_statements,
)


def _fact(value: float, concept: str, period: str, unit: str = "iso4217:EUR", **dimensions):
    return {
        "value": str(value),
        "dimensions": {
            "concept": concept,
            "entity": "scheme:TESTLEI",
            "period": period,
            "unit": unit,
            **dimensions,
        },
    }


def _report() -> _ESEFReport:
    return _ESEFReport(
        {
            "period_end": "2025-12-31",
            "date_added": "2026-03-01 10:00:00",
            "fxo_id": "TEST-2025-ESEF",
            "viewer_url": "/test/reports/ixbrlviewer.html",
        },
        {
            "facts": {
                "assets": _fact(500.0, "ifrs-full:Assets", "2026-01-01T00:00:00"),
                "liabilities": _fact(300.0, "ifrs-full:Liabilities", "2026-01-01T00:00:00"),
                "revenue": _fact(
                    200.0,
                    "ifrs-full:Revenue",
                    "2025-01-01T00:00:00/2026-01-01T00:00:00",
                ),
                "profit": _fact(
                    40.0,
                    "ifrs-full:ProfitLoss",
                    "2025-01-01T00:00:00/2026-01-01T00:00:00",
                ),
                "operating_cash": _fact(
                    55.0,
                    "ifrs-full:CashFlowsFromUsedInOperatingActivities",
                    "2025-01-01T00:00:00/2026-01-01T00:00:00",
                ),
                "segment_revenue": _fact(
                    80.0,
                    "ifrs-full:Revenue",
                    "2025-01-01T00:00:00/2026-01-01T00:00:00",
                    **{"ifrs-full:SegmentsAxis": "test:RetailMember"},
                ),
            }
        },
    )


def test_esef_normalizer_separates_primary_statements_and_ignores_dimensions() -> None:
    income = normalize_esef_xbrl_statements(
        "TEST.MC", "Test Bank", [_report()], StatementType.INCOME
    )
    balance = normalize_esef_xbrl_statements(
        "TEST.MC", "Test Bank", [_report()], StatementType.BALANCE_SHEET
    )
    cash_flow = normalize_esef_xbrl_statements(
        "TEST.MC", "Test Bank", [_report()], StatementType.CASH_FLOW
    )

    assert income.annual[0].values == {"totalRevenue": 200.0, "netIncome": 40.0}
    assert balance.annual[0].values == {"totalAssets": 500.0, "totalLiabilities": 300.0}
    assert cash_flow.annual[0].values == {"operatingCashFlow": 55.0}
    assert income.annual[0].period == "FY 2025"
    assert income.annual[0].source_form == "ESEF AFR"
    assert income.currency == "EUR"
    assert income.source_url == "https://filings.xbrl.org/test/reports/ixbrlviewer.html"


def test_esef_cash_flow_sections_follow_accounting_subtotals() -> None:
    assert _metric_section("paymentsToAcquireEntityShares", StatementType.CASH_FLOW) == (
        "FINANCING ACTIVITIES"
    )
    assert _metric_section("paymentsToAcquireOrRedeemEntitysShares", StatementType.CASH_FLOW) == (
        "FINANCING ACTIVITIES"
    )
    assert _metric_section("purchaseOfTreasuryShares", StatementType.CASH_FLOW) == (
        "FINANCING ACTIVITIES"
    )
    assert _metric_section(
        "proceedsFromSalesOfInvestmentsAccountedForUsingEquityMethod",
        StatementType.CASH_FLOW,
    ) == "INVESTING ACTIVITIES"
    assert _metric_section(
        "proceedsFromDisposalOfNoncurrentAssets",
        StatementType.CASH_FLOW,
    ) == "INVESTING ACTIVITIES"
    assert _metric_section("effectOfExchangeRate", StatementType.CASH_FLOW) == (
        "CASH RECONCILIATION / SUPPLEMENTAL"
    )
    assert _metric_section("changesInCash", StatementType.CASH_FLOW) == (
        "CASH RECONCILIATION / SUPPLEMENTAL"
    )
