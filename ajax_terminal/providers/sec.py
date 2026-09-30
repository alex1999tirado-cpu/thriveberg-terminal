from __future__ import annotations

import asyncio
import gzip
import html
import json
import os
import re
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from defusedxml import ElementTree as ET

from ajax_terminal.models.filing import Filing, FilingCollection
from ajax_terminal.models.quote import (
    DataQuality,
    FinancialPeriod,
    FinancialStatements,
    StatementType,
)
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.utils.url_security import require_https_url


_SEC_HOSTS = ("sec.gov",)


class SECFilingsProvider:
    name = "SEC EDGAR"
    TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    def __init__(self, user_agent: str | None = None, timeout: int = 12) -> None:
        self.user_agent = user_agent or os.getenv(
            "AJAX_SEC_USER_AGENT",
            "THRIVEBERG Terminal thriveberg-terminal@example.com",
        )
        self.timeout = timeout
        self._ticker_index: dict[str, tuple[str, str]] | None = None
        self._ticker_lock = asyncio.Lock()
        self._company_facts_cache: dict[str, dict[str, Any]] = {}
        self._company_facts_lock = asyncio.Lock()
        self._presentation_cache: dict[tuple[str, StatementType], _StatementPresentation] = {}
        self._presentation_lock = asyncio.Lock()

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        limit: int = 20,
    ) -> FilingCollection:
        clean = symbol.strip().upper()
        ticker_index = await self._ticker_lookup()
        identity = ticker_index.get(clean) or ticker_index.get(clean.replace(".", "-"))
        if identity is None:
            return FilingCollection(
                symbol=clean,
                company_name=clean,
                cik="",
                filings=[],
                provider=self.name,
                message="Ticker not found in the SEC company index. Non-US listings may not file 10-K/10-Q.",
            )

        cik, company_name = identity
        payload = await asyncio.to_thread(
            self._get_json,
            self.SUBMISSIONS_URL.format(cik=cik),
        )
        recent = payload.get("filings", {}).get("recent", {})
        requested = {form.upper() for form in forms}
        filings: list[Filing] = []
        for row in _columnar_rows(recent):
            form = str(row.get("form", "")).upper()
            base_form = form.removesuffix("/A")
            if base_form not in requested:
                continue
            accession = str(row.get("accessionNumber", ""))
            primary_document = str(row.get("primaryDocument", ""))
            filing_date = _parse_date(row.get("filingDate"))
            if not accession or not primary_document or filing_date is None:
                continue
            filings.append(
                Filing(
                    symbol=clean,
                    company_name=str(payload.get("name") or company_name),
                    cik=cik,
                    form=form,
                    filing_date=filing_date,
                    report_date=_parse_date(row.get("reportDate")),
                    accession_number=accession,
                    primary_document=primary_document,
                    description=str(row.get("primaryDocDescription", "")),
                )
            )
            if len(filings) >= limit:
                break
        return FilingCollection(
            symbol=clean,
            company_name=str(payload.get("name") or company_name),
            cik=cik,
            filings=filings,
            provider=self.name,
            quality=DataQuality.REALTIME,
            message="" if filings else "No matching filings were returned by SEC EDGAR.",
        )

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
    ) -> FinancialStatements:
        clean = symbol.strip().upper()
        ticker_index = await self._ticker_lookup()
        identity = ticker_index.get(clean) or ticker_index.get(clean.replace(".", "-"))
        if identity is None:
            raise ProviderError(f"{clean} is not a US issuer in the SEC company index")
        cik, company_name = identity
        payload, presentation = await asyncio.gather(
            self._company_facts(cik),
            self._statement_presentation(cik, statement_type),
        )
        return normalize_sec_companyfacts(
            clean,
            company_name,
            payload,
            statement_type,
            self.name,
            presentation,
        )

    async def _ticker_lookup(self) -> dict[str, tuple[str, str]]:
        if self._ticker_index is not None:
            return self._ticker_index
        async with self._ticker_lock:
            if self._ticker_index is not None:
                return self._ticker_index
            payload = await asyncio.to_thread(self._get_json, self.TICKERS_URL)
            rows = payload.values() if isinstance(payload, dict) else []
            index: dict[str, tuple[str, str]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ticker = str(row.get("ticker", "")).upper()
                cik_value = row.get("cik_str")
                if not ticker or cik_value is None:
                    continue
                index[ticker] = (f"{int(cik_value):010d}", str(row.get("title", ticker)))
            if not index:
                raise ProviderError("SEC ticker index was empty")
            self._ticker_index = index
        return index

    async def _company_facts(self, cik: str) -> dict[str, Any]:
        cached = self._company_facts_cache.get(cik)
        if cached is not None:
            return cached
        async with self._company_facts_lock:
            cached = self._company_facts_cache.get(cik)
            if cached is not None:
                return cached
            payload = await asyncio.to_thread(
                self._get_json,
                self.COMPANY_FACTS_URL.format(cik=cik),
            )
            self._company_facts_cache[cik] = payload
            return payload

    async def _statement_presentation(
        self,
        cik: str,
        statement_type: StatementType,
    ) -> _StatementPresentation:
        cache_key = (cik, statement_type)
        cached = self._presentation_cache.get(cache_key)
        if cached is not None:
            return cached
        async with self._presentation_lock:
            cached = self._presentation_cache.get(cache_key)
            if cached is not None:
                return cached
            try:
                submissions = await asyncio.to_thread(
                    self._get_json,
                    self.SUBMISSIONS_URL.format(cik=cik),
                )
                rows = _columnar_rows(submissions.get("filings", {}).get("recent", {}))
                candidates: list[dict[str, object]] = []
                seen_forms: set[str] = set()
                for row in rows:
                    form = str(row.get("form", "")).upper()
                    base_form = form.removesuffix("/A")
                    if base_form not in {"10-K", "10-Q"} or base_form in seen_forms:
                        continue
                    if not row.get("accessionNumber"):
                        continue
                    candidates.append(row)
                    seen_forms.add(base_form)
                    if len(seen_forms) == 2:
                        break
                items: list[_PresentationItem] = []
                seen_concepts: set[tuple[str, str]] = set()
                source_url = ""
                for row in candidates:
                    accession = str(row.get("accessionNumber", "")).replace("-", "")
                    base_url = (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{int(cik)}/{accession}/"
                    )
                    filing_summary = await asyncio.to_thread(
                        self._get_text,
                        f"{base_url}FilingSummary.xml",
                    )
                    report_names = _statement_report_names(filing_summary, statement_type)
                    if not report_names:
                        continue
                    for report_name in report_names:
                        report_url = f"{base_url}{report_name}"
                        report_html = await asyncio.to_thread(self._get_text, report_url)
                        for item in _parse_statement_report(report_html, statement_type):
                            identity = (item.taxonomy, item.concept)
                            if identity in seen_concepts:
                                continue
                            seen_concepts.add(identity)
                            items.append(item)
                        source_url = source_url or report_url
                presentation = _StatementPresentation(tuple(items), source_url)
            except Exception:
                presentation = _StatementPresentation((), "")
            self._presentation_cache[cache_key] = presentation
            return presentation

    def _get_json(self, url: str) -> dict[str, Any]:
        body = self._get_body(url)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("SEC EDGAR returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("SEC EDGAR returned an unexpected payload")
        return payload

    def _get_text(self, url: str) -> str:
        body = self._get_body(url)
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderError("SEC EDGAR returned invalid text") from exc

    def _get_body(self, url: str) -> bytes:
        safe_url = require_https_url(url, allowed_hosts=_SEC_HOSTS)
        request = urllib.request.Request(
            safe_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                body = response.read()
                encoding = response.headers.get("Content-Encoding", "").lower()
        except Exception as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"SEC EDGAR request failed: {exc}") from exc
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
        return body


def _columnar_rows(columns: object) -> list[dict[str, object]]:
    if not isinstance(columns, dict):
        return []
    lengths = [len(value) for value in columns.values() if isinstance(value, list)]
    row_count = max(lengths, default=0)
    return [
        {
            key: value[index]
            for key, value in columns.items()
            if isinstance(value, list) and index < len(value)
        }
        for index in range(row_count)
    ]


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class _LineItem:
    key: str
    tags: tuple[str, ...]
    multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class _Fact:
    value: float
    start: date | None
    end: date
    filed: date
    fiscal_year: int | None
    fiscal_period: str
    form: str
    accession: str
    unit: str

    @property
    def duration_days(self) -> int | None:
        return (self.end - self.start).days + 1 if self.start else None


@dataclass(frozen=True, slots=True)
class _PresentationItem:
    taxonomy: str
    concept: str
    label: str
    section: str = ""


@dataclass(frozen=True, slots=True)
class _StatementPresentation:
    items: tuple[_PresentationItem, ...]
    source_url: str


_REPORT_ROW_RE = re.compile(
    r"<tr\s+class=[\"'](?P<class>[^\"']+)[\"'][^>]*>(?P<body>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
_REPORT_CONCEPT_RE = re.compile(
    r"defref_(?P<taxonomy>[A-Za-z0-9-]+)_(?P<concept>[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_REPORT_LABEL_RE = re.compile(
    r"<td\s+class=[\"']pl[\"'][^>]*>.*?<a\b[^>]*>(?P<label>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _statement_report_names(summary_xml: str, statement_type: StatementType) -> tuple[str, ...]:
    try:
        root = ET.fromstring(summary_xml)
    except ET.ParseError:
        return ()
    ranked: list[tuple[int, str]] = []
    comprehensive: list[str] = []
    for report in root.findall(".//Report"):
        category = (report.findtext("MenuCategory") or "").strip().upper()
        short_name = (report.findtext("ShortName") or "").strip()
        html_name = (report.findtext("HtmlFileName") or "").strip()
        if category != "STATEMENTS" or not html_name:
            continue
        normalized = re.sub(r"[^A-Z0-9]+", " ", short_name.upper()).strip()
        if "PARENTHETICAL" in normalized:
            continue
        if statement_type == StatementType.INCOME and "COMPREHENSIVE INCOME" in normalized:
            comprehensive.append(html_name)
            continue
        score = _statement_report_score(normalized, statement_type)
        if score:
            ranked.append((score, html_name))
    primary = max(ranked, default=(0, ""))[1]
    return tuple(name for name in (primary, *comprehensive[:1]) if name)


def _statement_report_score(name: str, statement_type: StatementType) -> int:
    if statement_type == StatementType.BALANCE_SHEET:
        if "BALANCE SHEET" in name:
            return 100
        if "FINANCIAL POSITION" in name:
            return 90
        return 0
    if statement_type == StatementType.CASH_FLOW:
        return 100 if "CASH FLOW" in name else 0
    if any(token in name for token in ("COMPREHENSIVE", "EQUITY", "CASH FLOW", "BALANCE")):
        return 0
    if "OPERATIONS" in name:
        return 100
    if "INCOME" in name:
        return 90
    if "EARNINGS" in name or "PROFIT OR LOSS" in name:
        return 80
    return 0


def _parse_statement_report(
    report_html: str,
    statement_type: StatementType,
) -> list[_PresentationItem]:
    items: list[_PresentationItem] = []
    section = ""
    for match in _REPORT_ROW_RE.finditer(report_html):
        row_class = set(match.group("class").lower().split())
        if "rh" in row_class:
            break
        body = match.group("body")
        concept_match = _REPORT_CONCEPT_RE.search(body)
        label_match = _REPORT_LABEL_RE.search(body)
        if concept_match is None or label_match is None:
            continue
        label = html.unescape(_HTML_TAG_RE.sub("", label_match.group("label")))
        label = " ".join(label.replace("\xa0", " ").split()).rstrip(":")
        concept = concept_match.group("concept")
        if not label:
            continue
        if concept.endswith("Abstract"):
            section = _presentation_section(label, statement_type)
            continue
        inferred_section = _presentation_section(label, statement_type)
        if statement_type == StatementType.INCOME:
            item_section = inferred_section
            if inferred_section == "COMPREHENSIVE / SUPPLEMENTAL" and section != inferred_section:
                item_section = ""
        else:
            default_section = (
                "SUPPLEMENTAL"
                if statement_type == StatementType.BALANCE_SHEET
                else "CASH RECONCILIATION / SUPPLEMENTAL"
            )
            item_section = section if inferred_section == default_section and section else inferred_section
        items.append(
            _PresentationItem(
                taxonomy=concept_match.group("taxonomy").lower(),
                concept=concept,
                label=label,
                section=item_section,
            )
        )
    return items


def _presentation_section(label: str, statement_type: StatementType) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower())
    if statement_type == StatementType.BALANCE_SHEET:
        if "equity" in normalized or "stockholder" in normalized or "shareholder" in normalized:
            return "SHAREHOLDERS' EQUITY"
        if "liabilit" in normalized or "payable" in normalized or "debt" in normalized:
            return "LIABILITIES"
        if "asset" in normalized or "cash" in normalized or "receivable" in normalized:
            return "ASSETS"
        return "SUPPLEMENTAL"
    if statement_type == StatementType.CASH_FLOW:
        if "operating" in normalized:
            return "OPERATING ACTIVITIES"
        if "investing" in normalized:
            return "INVESTING ACTIVITIES"
        if "financing" in normalized:
            return "FINANCING ACTIVITIES"
        return "CASH RECONCILIATION / SUPPLEMENTAL"
    if (
        "operating expense" in normalized
        or "research" in normalized
        or "selling" in normalized
        or "marketing" in normalized
    ):
        return "OPERATING EXPENSES"
    if "revenue" in normalized or "sales" in normalized or "gross" in normalized:
        return "REVENUE / GROSS PROFIT"
    if "operating income" in normalized or "operating profit" in normalized:
        return "OPERATING RESULT"
    if "tax" in normalized or "interest" in normalized or "before" in normalized:
        return "NON-OPERATING / TAX"
    if "net income" in normalized or "earnings per share" in normalized or "shares used" in normalized:
        return "NET INCOME / PER SHARE"
    return "COMPREHENSIVE / SUPPLEMENTAL"


_STATEMENT_ITEMS: dict[StatementType, tuple[_LineItem, ...]] = {
    StatementType.INCOME: (
        _LineItem("totalRevenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")),
        _LineItem("costOfRevenue", ("CostOfRevenue", "CostOfGoodsAndServicesSold")),
        _LineItem("grossProfit", ("GrossProfit",)),
        _LineItem("researchAndDevelopment", ("ResearchAndDevelopmentExpense",)),
        _LineItem("sellingGeneralAndAdministrative", ("SellingGeneralAndAdministrativeExpense",)),
        _LineItem("marketingExpense", ("MarketingExpense",)),
        _LineItem("operatingExpense", ("OperatingExpenses",)),
        _LineItem("operatingIncome", ("OperatingIncomeLoss",)),
        _LineItem("interestIncome", ("InterestIncomeExpenseNonoperatingNet", "InterestIncomeNonoperating")),
        _LineItem("interestExpense", ("InterestExpenseNonOperating", "InterestAndDebtExpense")),
        _LineItem("nonOperatingIncomeExpense", ("NonoperatingIncomeExpense",)),
        _LineItem("otherNonOperatingIncomeExpense", ("OtherNonoperatingIncomeExpense",)),
        _LineItem("incomeBeforeTax", ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",)),
        _LineItem("taxProvision", ("IncomeTaxExpenseBenefit",)),
        _LineItem("incomeFromContinuingOperations", ("IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",)),
        _LineItem("netIncome", ("NetIncomeLoss", "ProfitLoss")),
        _LineItem("netIncomeCommonStockholders", ("NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLossAvailableToCommonStockholdersDiluted")),
        _LineItem("netIncomeNoncontrollingInterests", ("NetIncomeLossAttributableToNoncontrollingInterest",)),
        _LineItem("preferredDividends", ("PreferredStockDividendsAndOtherAdjustments",)),
        _LineItem("basicEPS", ("EarningsPerShareBasic",)),
        _LineItem("dilutedEPS", ("EarningsPerShareDiluted",)),
        _LineItem("basicAverageShares", ("WeightedAverageNumberOfSharesOutstandingBasic",)),
        _LineItem("dilutedAverageShares", ("WeightedAverageNumberOfDilutedSharesOutstanding",)),
    ),
    StatementType.BALANCE_SHEET: (
        _LineItem("cashAndCashEquivalents", ("CashAndCashEquivalentsAtCarryingValue",)),
        _LineItem("restrictedCashCurrent", ("RestrictedCashAndCashEquivalentsCurrent",)),
        _LineItem("shortTermInvestments", ("ShortTermInvestments", "MarketableSecuritiesCurrent")),
        _LineItem("accountsReceivableNetCurrent", ("AccountsReceivableNetCurrent",)),
        _LineItem("inventory", ("InventoryNet",)),
        _LineItem("prepaidExpenseCurrent", ("PrepaidExpenseAndOtherAssetsCurrent", "PrepaidExpenseCurrent")),
        _LineItem("otherCurrentAssets", ("OtherCurrentAssets",)),
        _LineItem("currentAssets", ("AssetsCurrent",)),
        _LineItem("propertyPlantEquipmentGross", ("PropertyPlantAndEquipmentGross",)),
        _LineItem("accumulatedDepreciation", ("AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",), -1.0),
        _LineItem("netPPE", ("PropertyPlantAndEquipmentNet",)),
        _LineItem("operatingLeaseRightOfUseAsset", ("OperatingLeaseRightOfUseAsset",)),
        _LineItem("goodwill", ("Goodwill",)),
        _LineItem("intangibleAssetsNet", ("FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill")),
        _LineItem("equityMethodInvestments", ("EquityMethodInvestments",)),
        _LineItem("longTermInvestments", ("LongTermInvestments", "MarketableSecuritiesNoncurrent")),
        _LineItem("otherNonCurrentAssets", ("OtherAssetsNoncurrent",)),
        _LineItem("totalNonCurrentAssets", ("AssetsNoncurrent",)),
        _LineItem("totalAssets", ("Assets",)),
        _LineItem("accountsPayableCurrent", ("AccountsPayableCurrent",)),
        _LineItem("accruedLiabilitiesCurrent", ("AccruedLiabilitiesCurrent",)),
        _LineItem("commercialPaper", ("CommercialPaper",)),
        _LineItem("shortTermBorrowings", ("ShortTermBorrowings",)),
        _LineItem("currentDebt", ("LongTermDebtCurrent", "ShortTermBorrowings")),
        _LineItem("operatingLeaseLiabilityCurrent", ("OperatingLeaseLiabilityCurrent",)),
        _LineItem("deferredRevenueCurrent", ("ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent")),
        _LineItem("otherCurrentLiabilities", ("OtherLiabilitiesCurrent",)),
        _LineItem("currentLiabilities", ("LiabilitiesCurrent",)),
        _LineItem("longTermDebt", ("LongTermDebtNoncurrent",)),
        _LineItem("operatingLeaseLiabilityNonCurrent", ("OperatingLeaseLiabilityNoncurrent",)),
        _LineItem("deferredTaxLiabilitiesNonCurrent", ("DeferredTaxLiabilitiesNoncurrent",)),
        _LineItem("deferredRevenueNonCurrent", ("ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent")),
        _LineItem("otherNonCurrentLiabilities", ("OtherLiabilitiesNoncurrent",)),
        _LineItem("totalNonCurrentLiabilities", ("LiabilitiesNoncurrent",)),
        _LineItem("totalLiabilities", ("Liabilities",)),
        _LineItem("commonStockValue", ("CommonStockValue",)),
        _LineItem("additionalPaidInCapital", ("AdditionalPaidInCapital",)),
        _LineItem("retainedEarnings", ("RetainedEarningsAccumulatedDeficit",)),
        _LineItem("accumulatedOtherComprehensiveIncome", ("AccumulatedOtherComprehensiveIncomeLossNetOfTax",)),
        _LineItem("treasuryStockValue", ("TreasuryStockValue",), -1.0),
        _LineItem("stockholdersEquity", ("StockholdersEquity",)),
        _LineItem("minorityInterest", ("MinorityInterest",)),
        _LineItem("totalEquity", ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",)),
        _LineItem("liabilitiesAndEquity", ("LiabilitiesAndStockholdersEquity",)),
        _LineItem("ordinarySharesNumber", ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding")),
    ),
    StatementType.CASH_FLOW: (
        _LineItem("netIncome", ("NetIncomeLoss", "ProfitLoss")),
        _LineItem("depreciationAndAmortization", ("DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment")),
        _LineItem("stockBasedCompensation", ("ShareBasedCompensation",)),
        _LineItem("deferredIncomeTax", ("DeferredIncomeTaxExpenseBenefit",)),
        _LineItem("otherNonCashItems", ("OtherNoncashIncomeExpense",)),
        _LineItem("changeInAccountsReceivable", ("IncreaseDecreaseInAccountsReceivable",)),
        _LineItem("changeInInventory", ("IncreaseDecreaseInInventories",)),
        _LineItem("changeInPrepaidAssets", ("IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",)),
        _LineItem("changeInAccountsPayable", ("IncreaseDecreaseInAccountsPayable",)),
        _LineItem("changeInAccruedLiabilities", ("IncreaseDecreaseInAccruedLiabilities",)),
        _LineItem("changeInDeferredRevenue", ("IncreaseDecreaseInContractWithCustomerLiability", "IncreaseDecreaseInDeferredRevenue")),
        _LineItem("changeInOtherOperatingAssets", ("IncreaseDecreaseInOtherOperatingAssets",)),
        _LineItem("changeInOtherOperatingLiabilities", ("IncreaseDecreaseInOtherOperatingLiabilities",)),
        _LineItem("operatingCashFlow", ("NetCashProvidedByUsedInOperatingActivities",)),
        _LineItem("capitalExpenditure", ("PaymentsToAcquirePropertyPlantAndEquipment",), -1.0),
        _LineItem("acquisitions", ("PaymentsToAcquireBusinessesNetOfCashAcquired",), -1.0),
        _LineItem("purchasesOfInvestments", ("PaymentsToAcquireInvestments", "PaymentsToAcquireAvailableForSaleSecuritiesDebt"), -1.0),
        _LineItem("proceedsFromInvestments", ("ProceedsFromSaleMaturityAndPrepaymentOfInvestments", "ProceedsFromSaleAndMaturityOfAvailableForSaleSecuritiesDebt")),
        _LineItem("investingCashFlow", ("NetCashProvidedByUsedInInvestingActivities",)),
        _LineItem("issuanceOfDebt", ("ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt")),
        _LineItem("repaymentOfDebt", ("RepaymentsOfDebt", "RepaymentsOfLongTermDebt"), -1.0),
        _LineItem("issuanceOfCommonStock", ("ProceedsFromStockOptionsExercised", "ProceedsFromIssuanceOfCommonStock")),
        _LineItem("repurchaseOfCapitalStock", ("PaymentsForRepurchaseOfCommonStock",), -1.0),
        _LineItem("cashDividendsPaid", ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"), -1.0),
        _LineItem("financingCashFlow", ("NetCashProvidedByUsedInFinancingActivities",)),
        _LineItem("effectOfExchangeRate", ("EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",)),
        _LineItem("changesInCash", ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", "CashAndCashEquivalentsPeriodIncreaseDecrease")),
    ),
}


def normalize_sec_companyfacts(
    symbol: str,
    company_name: str,
    payload: dict[str, Any],
    statement_type: StatementType,
    provider: str = "SEC EDGAR",
    presentation: _StatementPresentation | None = None,
) -> FinancialStatements:
    facts = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(facts, dict) or not facts:
        raise ProviderError(f"SEC returned no US-GAAP company facts for {symbol}")

    items, metric_labels, metric_order, metric_sections = _items_for_presentation(
        facts,
        statement_type,
        presentation,
    )
    annual_periods: dict[date, FinancialPeriod] = {}
    quarterly_periods: dict[date, FinancialPeriod] = {}
    currencies: list[str] = []
    for item in items:
        observations = _item_facts(facts, item)
        currencies.extend(fact.unit for fact in observations if len(fact.unit) == 3 and fact.unit.isalpha())
        for fact in _annual_facts(observations, instant=statement_type == StatementType.BALANCE_SHEET):
            period = annual_periods.setdefault(fact.end, _financial_period(fact, annual=True))
            period.values.setdefault(item.key, fact.value * item.multiplier)
        quarterly = (
            _instant_quarter_facts(observations)
            if statement_type == StatementType.BALANCE_SHEET
            else _duration_quarter_facts(observations, derive=True)
        )
        for fact, value, derived in quarterly:
            period = quarterly_periods.setdefault(fact.end, _financial_period(fact, annual=False, derived=derived))
            period.values.setdefault(item.key, value * item.multiplier)
            period.derived = period.derived or derived

    annual = _complete_periods(annual_periods, statement_type)[:8]
    quarterly = _complete_periods(quarterly_periods, statement_type)[:12]
    if not annual and not quarterly:
        raise ProviderError(f"SEC returned no usable {statement_type} facts for {symbol}")
    currency = max(set(currencies), key=currencies.count) if currencies else "USD"
    return FinancialStatements(
        symbol=symbol,
        name=str(payload.get("entityName") or company_name or symbol),
        statement_type=statement_type,
        annual=annual,
        quarterly=quarterly,
        currency=currency,
        provider=f"{provider} XBRL",
        quality=DataQuality.REALTIME,
        metric_labels=metric_labels,
        metric_order=metric_order,
        metric_sections=metric_sections,
        source_url=presentation.source_url if presentation else "",
    )


def _items_for_presentation(
    facts: dict[str, Any],
    statement_type: StatementType,
    presentation: _StatementPresentation | None,
) -> tuple[list[_LineItem], dict[str, str], list[str], dict[str, str]]:
    standard_items = list(_STATEMENT_ITEMS[statement_type])
    by_tag = {
        tag: item
        for item in standard_items
        for tag in item.tags
    }
    items: list[_LineItem] = []
    labels: dict[str, str] = {}
    order: list[str] = []
    sections: dict[str, str] = {}
    used_keys: set[str] = set()

    for presented in presentation.items if presentation else ():
        if presented.taxonomy != "us-gaap" or presented.concept not in facts:
            continue
        item = by_tag.get(presented.concept)
        if item is None:
            key = presented.concept[:1].lower() + presented.concept[1:]
            item = _LineItem(
                key,
                (presented.concept,),
                _presentation_multiplier(statement_type, presented.concept, presented.label),
            )
        if item.key in used_keys:
            continue
        used_keys.add(item.key)
        items.append(item)
        order.append(item.key)
        labels[item.key] = presented.label
        if presented.section:
            sections[item.key] = presented.section

    for item in standard_items:
        if item.key in used_keys:
            continue
        used_keys.add(item.key)
        items.append(item)
        order.append(item.key)
        label = _first_concept_label(facts, item.tags)
        if label:
            labels[item.key] = label
    return items, labels, order, sections


def _presentation_multiplier(
    statement_type: StatementType,
    concept: str,
    label: str,
) -> float:
    normalized = re.sub(r"[^a-z0-9]", "", f"{concept} {label}".lower())
    if statement_type == StatementType.CASH_FLOW and normalized.startswith(
        ("payments", "repayments", "purchase", "purchases")
    ):
        return -1.0
    if statement_type == StatementType.BALANCE_SHEET and any(
        token in normalized for token in ("accumulateddepreciation", "treasurystock")
    ):
        return -1.0
    return 1.0


def _first_concept_label(facts: dict[str, Any], tags: tuple[str, ...]) -> str:
    for tag in tags:
        concept = facts.get(tag)
        if isinstance(concept, dict) and concept.get("label"):
            return str(concept["label"])
    return ""


def _item_facts(facts: dict[str, Any], item: _LineItem) -> list[_Fact]:
    selected: dict[tuple[date | None, date, str, str], _Fact] = {}
    for tag in item.tags:
        concept = facts.get(tag)
        if not isinstance(concept, dict):
            continue
        units = concept.get("units", {})
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            if not _supported_unit(item.key, str(unit)) or not isinstance(rows, list):
                continue
            for row in rows:
                fact = _parse_fact(row, str(unit))
                if fact is None:
                    continue
                identity = (fact.start, fact.end, fact.form, fact.accession)
                selected.setdefault(identity, fact)
    return list(selected.values())


def _parse_fact(row: object, unit: str) -> _Fact | None:
    if not isinstance(row, dict):
        return None
    end = _parse_date(row.get("end"))
    filed = _parse_date(row.get("filed"))
    value = row.get("val")
    if end is None or filed is None or not isinstance(value, (int, float)):
        return None
    form = str(row.get("form", "")).upper()
    if form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
        return None
    fiscal_year = row.get("fy")
    return _Fact(
        value=float(value),
        start=_parse_date(row.get("start")),
        end=end,
        filed=filed,
        fiscal_year=int(fiscal_year) if isinstance(fiscal_year, (int, float)) else None,
        fiscal_period=str(row.get("fp", "")).upper(),
        form=form,
        accession=str(row.get("accn", "")),
        unit=unit,
    )


def _supported_unit(key: str, unit: str) -> bool:
    normalized = unit.lower().replace("-per-", "/")
    if "eps" in key.lower():
        return normalized.endswith("/shares")
    if "shares" in key.lower():
        return normalized == "shares"
    return len(unit) == 3 and unit.isalpha()


def _is_original_reporting_window(fact: _Fact) -> bool:
    delay = (fact.filed - fact.end).days
    return 0 <= delay <= 200


def _annual_facts(facts: list[_Fact], instant: bool) -> list[_Fact]:
    selected: dict[date, _Fact] = {}
    for fact in facts:
        if not fact.form.startswith("10-K") or not _is_original_reporting_window(fact):
            continue
        if instant and fact.start is not None:
            continue
        if not instant and (fact.duration_days is None or not 270 <= fact.duration_days <= 430):
            continue
        current = selected.get(fact.end)
        if current is None or fact.filed > current.filed:
            selected[fact.end] = fact
    return list(selected.values())


def _instant_quarter_facts(facts: list[_Fact]) -> list[tuple[_Fact, float, bool]]:
    selected: dict[date, _Fact] = {}
    for fact in facts:
        if fact.start is not None or not _is_original_reporting_window(fact):
            continue
        if fact.form.startswith("10-Q") and fact.fiscal_period not in {"Q1", "Q2", "Q3"}:
            continue
        if fact.form.startswith("10-K") and fact.fiscal_period != "FY":
            continue
        current = selected.get(fact.end)
        if current is None or fact.filed > current.filed:
            selected[fact.end] = fact
    return [(fact, fact.value, False) for fact in selected.values()]


def _duration_quarter_facts(facts: list[_Fact], derive: bool) -> list[tuple[_Fact, float, bool]]:
    valid = [fact for fact in facts if fact.start and _is_original_reporting_window(fact)]
    direct: dict[tuple[int, str], _Fact] = {}
    cumulative: dict[tuple[int, str], _Fact] = {}
    annual: dict[int, _Fact] = {}
    for fact in valid:
        fiscal_year = fact.fiscal_year or fact.end.year
        days = fact.duration_days or 0
        if fact.form.startswith("10-Q") and fact.fiscal_period in {"Q1", "Q2", "Q3"}:
            target = direct if 50 <= days <= 130 else cumulative
            key = (fiscal_year, fact.fiscal_period)
            current = target.get(key)
            if current is None or fact.filed > current.filed:
                target[key] = fact
        elif fact.form.startswith("10-K") and fact.fiscal_period == "FY" and 270 <= days <= 430:
            current = annual.get(fiscal_year)
            if current is None or fact.filed > current.filed:
                annual[fiscal_year] = fact

    result: list[tuple[_Fact, float, bool]] = [(fact, fact.value, False) for fact in direct.values()]
    if not derive:
        return result
    years = set(year for year, _quarter in cumulative) | set(annual)
    for year in years:
        q1 = direct.get((year, "Q1"))
        q2_direct = direct.get((year, "Q2"))
        q3_direct = direct.get((year, "Q3"))
        q2_ytd = cumulative.get((year, "Q2"))
        q3_ytd = cumulative.get((year, "Q3"))
        if q2_direct is None and q1 is not None and q2_ytd is not None:
            result.append((q2_ytd, q2_ytd.value - q1.value, True))
        if q3_direct is None and q2_ytd is not None and q3_ytd is not None:
            result.append((q3_ytd, q3_ytd.value - q2_ytd.value, True))
        if q3_ytd is not None and year in annual:
            result.append((annual[year], annual[year].value - q3_ytd.value, True))
    return result


def _financial_period(fact: _Fact, annual: bool, derived: bool = False) -> FinancialPeriod:
    fiscal_year = fact.fiscal_year or fact.end.year
    if annual:
        label = f"FY {fiscal_year}"
    elif fact.form.startswith("10-K"):
        label = f"Q4 {fiscal_year}"
    else:
        label = f"{fact.fiscal_period or 'Q?'} {fiscal_year}"
    return FinancialPeriod(
        period=label,
        end_date=fact.end,
        values={},
        source_form=fact.form,
        filed_date=fact.filed,
        accession_number=fact.accession,
        derived=derived,
    )


def _complete_periods(
    periods: dict[date, FinancialPeriod],
    statement_type: StatementType,
) -> list[FinancialPeriod]:
    complete = [period for period in periods.values() if period.values]
    if statement_type == StatementType.CASH_FLOW:
        for period in complete:
            operating = period.values.get("operatingCashFlow")
            capex = period.values.get("capitalExpenditure")
            if operating is not None and capex is not None:
                period.values["freeCashFlowCalculated"] = operating + capex
    return sorted(complete, key=lambda period: period.end_date or date.min, reverse=True)
