from __future__ import annotations

import re

from ajax_terminal.models.quote import FinancialPeriod, StatementType


_STATEMENT_METRIC_ORDER: dict[StatementType, tuple[str, ...]] = {
    StatementType.INCOME: (
        "totalRevenue",
        "revenue",
        "operatingRevenue",
        "costOfRevenue",
        "grossProfit",
        "researchAndDevelopment",
        "sellingGeneralAndAdministrative",
        "sellingGeneralAndAdministration",
        "generalAndAdministrativeExpense",
        "marketingExpense",
        "operatingExpense",
        "operatingExpenses",
        "operatingIncome",
        "ebit",
        "EBIT",
        "ebitda",
        "EBITDA",
        "normalizedEBITDA",
        "interestIncome",
        "interestExpense",
        "nonOperatingIncomeExpense",
        "otherNonOperatingIncomeExpense",
        "incomeBeforeTax",
        "pretaxIncome",
        "taxProvision",
        "incomeTaxExpense",
        "incomeFromContinuingOperations",
        "netIncome",
        "netIncomeNoncontrollingInterests",
        "preferredDividends",
        "netIncomeCommonStockholders",
        "netIncomeApplicableToCommonShares",
        "basicEPS",
        "dilutedEPS",
        "basicAverageShares",
        "dilutedAverageShares",
    ),
    StatementType.BALANCE_SHEET: (
        "cashAndCashEquivalents",
        "cash",
        "restrictedCashCurrent",
        "shortTermInvestments",
        "otherShortTermInvestments",
        "cashCashEquivalentsAndShortTermInvestments",
        "accountsReceivableNetCurrent",
        "accountsReceivable",
        "grossAccountsReceivable",
        "allowanceForDoubtfulAccountsReceivable",
        "receivables",
        "netReceivables",
        "inventory",
        "prepaidExpenseCurrent",
        "otherCurrentAssets",
        "currentAssets",
        "totalCurrentAssets",
        "properties",
        "landAndImprovements",
        "buildingsAndImprovements",
        "machineryFurnitureEquipment",
        "constructionInProgress",
        "propertyPlantEquipmentGross",
        "propertyPlantEquipment",
        "grossPPE",
        "accumulatedDepreciation",
        "netPPE",
        "leases",
        "operatingLeaseRightOfUseAsset",
        "goodwill",
        "intangibleAssetsNet",
        "goodwillAndOtherIntangibleAssets",
        "equityMethodInvestments",
        "longTermInvestments",
        "otherNonCurrentAssets",
        "totalNonCurrentAssets",
        "totalAssets",
        "accountsPayableCurrent",
        "accountsPayable",
        "payables",
        "payablesAndAccruedExpenses",
        "accruedLiabilitiesCurrent",
        "currentAccruedExpenses",
        "commercialPaper",
        "shortTermBorrowings",
        "otherCurrentBorrowings",
        "currentDebt",
        "currentCapitalLeaseObligation",
        "currentDebtAndCapitalLeaseObligation",
        "operatingLeaseLiabilityCurrent",
        "deferredRevenueCurrent",
        "currentDeferredRevenue",
        "otherCurrentLiabilities",
        "currentLiabilities",
        "totalCurrentLiabilities",
        "longTermDebt",
        "longTermCapitalLeaseObligation",
        "longTermDebtAndCapitalLeaseObligation",
        "operatingLeaseLiabilityNonCurrent",
        "deferredTaxLiabilitiesNonCurrent",
        "deferredRevenueNonCurrent",
        "otherNonCurrentLiabilities",
        "totalNonCurrentLiabilities",
        "totalNonCurrentLiabilitiesNetMinorityInterest",
        "totalDebt",
        "totalLiabilities",
        "totalLiabilitiesNetMinorityInterest",
        "commonStockValue",
        "capitalStock",
        "commonStock",
        "additionalPaidInCapital",
        "retainedEarnings",
        "accumulatedOtherComprehensiveIncome",
        "gainsLossesNotAffectingRetainedEarnings",
        "treasuryStockValue",
        "commonStockEquity",
        "stockholdersEquity",
        "totalStockholderEquity",
        "minorityInterest",
        "totalEquity",
        "totalEquityGrossMinorityInterest",
        "liabilitiesAndEquity",
        "workingCapital",
        "investedCapital",
        "tangibleBookValue",
        "netDebt",
        "ordinarySharesNumber",
        "shareIssued",
        "treasurySharesNumber",
    ),
    StatementType.CASH_FLOW: (
        "netIncome",
        "depreciationAndAmortization",
        "stockBasedCompensation",
        "deferredIncomeTax",
        "otherNonCashItems",
        "changeInAccountsReceivable",
        "changeInInventory",
        "changeInPrepaidAssets",
        "changeInAccountsPayable",
        "changeInAccruedLiabilities",
        "changeInDeferredRevenue",
        "changeInOtherOperatingAssets",
        "changeInOtherOperatingLiabilities",
        "operatingCashFlow",
        "totalCashFromOperatingActivities",
        "capitalExpenditure",
        "capitalExpenditures",
        "acquisitions",
        "purchasesOfInvestments",
        "proceedsFromInvestments",
        "investingCashFlow",
        "issuanceOfDebt",
        "repaymentOfDebt",
        "issuanceOfCommonStock",
        "repurchaseOfCapitalStock",
        "cashDividendsPaid",
        "financingCashFlow",
        "effectOfExchangeRate",
        "changesInCash",
        "endCashPosition",
        "freeCashFlow",
        "freeCashFlowCalculated",
    ),
}


_EXPENSE_AND_OUTFLOW_METRICS: dict[StatementType, frozenset[str]] = {
    StatementType.INCOME: frozenset(
        {
            "costofrevenue",
            "researchanddevelopment",
            "researchdevelopment",
            "sellinggeneralandadministrative",
            "sellinggeneralandadministration",
            "sellinggeneraladministrative",
            "generalandadministrativeexpense",
            "marketingexpense",
            "operatingexpense",
            "operatingexpenses",
            "interestexpense",
            "taxprovision",
            "incometaxexpense",
            "preferreddividends",
        }
    ),
    StatementType.BALANCE_SHEET: frozenset(),
    StatementType.CASH_FLOW: frozenset(
        {
            "capitalexpenditure",
            "capitalexpenditures",
            "acquisitions",
            "purchasesofinvestments",
            "repaymentofdebt",
            "repurchaseofcapitalstock",
            "repurchaseofstock",
            "cashdividendspaid",
            "dividendspaid",
        }
    ),
}


_BALANCE_SHEET_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ASSETS",
        _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET][
            : _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("accountsPayableCurrent")
        ],
    ),
    (
        "LIABILITIES",
        _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET][
            _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("accountsPayableCurrent")
            : _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("commonStockValue")
        ],
    ),
    (
        "SHAREHOLDERS' EQUITY",
        _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET][
            _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("commonStockValue")
            : _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("workingCapital")
        ],
    ),
    (
        "SUPPLEMENTAL",
        _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET][
            _STATEMENT_METRIC_ORDER[StatementType.BALANCE_SHEET].index("workingCapital") :
        ],
    ),
)


def ordered_statement_metrics(
    periods: list[FinancialPeriod],
    statement_type: StatementType,
    preferred_order: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    available = {key for period in periods for key in period.values}
    preferred = {
        _normalize_metric(key): index
        for index, key in enumerate(preferred_order or ())
    }
    standard_offset = len(preferred)
    priority = dict(preferred)
    for index, key in enumerate(_STATEMENT_METRIC_ORDER[statement_type]):
        priority.setdefault(_normalize_metric(key), standard_offset + index)
    return sorted(
        available,
        key=lambda key: (
            priority.get(_normalize_metric(key), len(priority)),
            _normalize_metric(key),
        ),
    )


def is_expense_or_outflow_metric(metric: str, statement_type: StatementType) -> bool:
    normalized = _normalize_metric(metric)
    if normalized in _EXPENSE_AND_OUTFLOW_METRICS[statement_type]:
        return True
    if statement_type == StatementType.INCOME:
        return any(
            token in normalized
            for token in (
                "costof",
                "expense",
                "expenses",
                "taxprovision",
                "taxexpense",
                "impairmentloss",
            )
        )
    if statement_type == StatementType.CASH_FLOW:
        return normalized.startswith(("payment", "payments", "purchase", "purchases", "repayment")) or any(
            token in normalized
            for token in ("cashoutflow", "dividendspaid", "repurchase")
        )
    return False


def grouped_statement_metrics(
    metrics: list[str],
    statement_type: StatementType,
    section_overrides: dict[str, str] | None = None,
) -> list[tuple[str, list[str]]]:
    """Return display groups while preserving the provider-normalized metric order."""
    titles = {
        StatementType.INCOME: (
            "REVENUE / GROSS PROFIT",
            "OPERATING EXPENSES",
            "OPERATING RESULT",
            "NON-OPERATING / TAX",
            "NET INCOME / PER SHARE",
            "COMPREHENSIVE / SUPPLEMENTAL",
        ),
        StatementType.BALANCE_SHEET: tuple(title for title, _metrics in _BALANCE_SHEET_SECTIONS),
        StatementType.CASH_FLOW: (
            "OPERATING ACTIVITIES",
            "INVESTING ACTIVITIES",
            "FINANCING ACTIVITIES",
            "CASH RECONCILIATION / SUPPLEMENTAL",
        ),
    }[statement_type]
    normalized_overrides = {
        _normalize_metric(metric): section
        for metric, section in (section_overrides or {}).items()
        if section in titles
    }
    section_lookup = {}
    if statement_type == StatementType.BALANCE_SHEET:
        section_lookup = {
            _normalize_metric(metric): title
            for title, section_metrics in _BALANCE_SHEET_SECTIONS
            for metric in section_metrics
        }
    grouped = {title: [] for title in titles}
    for metric in metrics:
        normalized = _normalize_metric(metric)
        title = normalized_overrides.get(normalized) or section_lookup.get(normalized)
        if not title:
            title = {
                StatementType.INCOME: _infer_income_statement_section,
                StatementType.BALANCE_SHEET: _infer_balance_sheet_section,
                StatementType.CASH_FLOW: _infer_cash_flow_section,
            }[statement_type](normalized)
        grouped[title].append(metric)
    return [(title, grouped[title]) for title in titles if grouped[title]]


def _normalize_metric(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _infer_balance_sheet_section(metric: str) -> str:
    """Classify provider-specific balance-sheet aliases by accounting meaning."""
    equity_terms = (
        "equity",
        "retainedearning",
        "paidincapital",
        "commonstock",
        "preferredstock",
        "capitalstock",
        "treasurystock",
        "minorityinterest",
        "gainslossesnotaffectingretainedearnings",
    )
    liability_terms = (
        "liabilit",
        "payable",
        "debt",
        "borrowing",
        "commercialpaper",
        "deferredrevenue",
        "contractliability",
        "obligation",
        "accruedexpense",
    )
    asset_terms = (
        "asset",
        "cash",
        "receivable",
        "inventory",
        "prepaid",
        "investment",
        "propertyplantequipment",
        "ppe",
        "goodwill",
        "intangible",
        "rightofuseasset",
        "leases",
        "properties",
        "land",
        "building",
        "machinery",
        "constructioninprogress",
    )
    if any(term in metric for term in equity_terms):
        return "SHAREHOLDERS' EQUITY"
    if any(term in metric for term in liability_terms):
        return "LIABILITIES"
    if any(term in metric for term in asset_terms):
        return "ASSETS"
    return "SUPPLEMENTAL"


def _infer_income_statement_section(metric: str) -> str:
    if (
        any(token in metric for token in ("revenue", "costof", "grossprofit", "grossmargin"))
        or metric.startswith("sales")
        or "netsales" in metric
    ):
        return "REVENUE / GROSS PROFIT"
    if any(
        token in metric
        for token in (
            "research",
            "selling",
            "marketing",
            "administrative",
            "employeebenefit",
            "operatingexpense",
            "depreciation",
            "amortisation",
            "amortization",
        )
    ):
        return "OPERATING EXPENSES"
    if any(token in metric for token in ("operatingincome", "operatingprofit", "ebit", "ebitda")):
        return "OPERATING RESULT"
    if any(
        token in metric
        for token in (
            "interest",
            "nonoperating",
            "pretax",
            "beforetax",
            "taxexpense",
            "taxprovision",
            "impairment",
            "associate",
            "jointventure",
        )
    ):
        return "NON-OPERATING / TAX"
    if any(
        token in metric
        for token in (
            "netincome",
            "profitloss",
            "earningspershare",
            "eps",
            "averageshares",
            "preferreddividend",
        )
    ):
        return "NET INCOME / PER SHARE"
    return "COMPREHENSIVE / SUPPLEMENTAL"


def _infer_cash_flow_section(metric: str) -> str:
    if any(
        token in metric
        for token in (
            "operatingcashflow",
            "operatingactivit",
            "changein",
            "adjustmentsfor",
            "depreciation",
            "amortisation",
            "amortization",
            "stockbasedcompensation",
            "noncash",
            "netincome",
            "profitloss",
        )
    ):
        return "OPERATING ACTIVITIES"
    if any(
        token in metric
        for token in (
            "investing",
            "capitalexpenditure",
            "propertyplantequipment",
            "intangibleasset",
            "acquisition",
            "investmentpurchase",
            "purchaseofinvestment",
            "proceedsfrominvestment",
            "saleofinvestment",
        )
    ):
        return "INVESTING ACTIVITIES"
    if any(
        token in metric
        for token in (
            "financing",
            "issuanceofdebt",
            "repaymentofdebt",
            "issuanceofcapital",
            "repurchase",
            "dividendspaid",
            "treasuryshare",
        )
    ):
        return "FINANCING ACTIVITIES"
    return "CASH RECONCILIATION / SUPPLEMENTAL"
