from __future__ import annotations

import asyncio
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ajax_terminal.models.quote import (
    DataQuality,
    FinancialPeriod,
    FinancialStatements,
    StatementType,
)
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.global_filings import (
    ESEFFilingsProvider,
    _ESEF_COUNTRIES,
    _get_json,
    country_for_symbol,
)


@dataclass(frozen=True, slots=True)
class _ESEFReport:
    attributes: dict[str, Any]
    payload: dict[str, Any]


class ESEFFinancialStatementsProvider:
    """Consolidated statement facts from public ESEF XBRL-JSON filings."""

    name = "ESEF XBRL-JSON / FILINGS.XBRL.ORG"
    FILINGS_URL = "https://filings.xbrl.org/api/entities/{lei}/filings"

    def __init__(self) -> None:
        self.filings = ESEFFilingsProvider()

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
    ) -> FinancialStatements:
        clean = symbol.strip().upper()
        country = country_for_symbol(clean)
        if country not in _ESEF_COUNTRIES:
            raise ProviderError(f"{clean} is not an ESEF jurisdiction listing")
        collection = await self.filings.filings(clean, ("10-K",), 6, country=country)
        if not collection.cik:
            raise ProviderError(collection.message or f"No ESEF issuer identity found for {clean}")
        index = await asyncio.to_thread(
            _get_json,
            self.FILINGS_URL.format(lei=urllib.parse.quote(collection.cik))
            + "?"
            + urllib.parse.urlencode({"page[size]": 100, "sort": "-period_end"}),
        )
        selected = _select_filing_attributes(index, country, limit=4)
        if not selected:
            raise ProviderError(f"No ESEF XBRL-JSON filing found for {clean}")
        payloads = await asyncio.gather(
            *(
                asyncio.to_thread(
                    _get_json,
                    _absolute_filings_url(str(attributes.get("json_url") or "")),
                )
                for attributes in selected
            ),
            return_exceptions=True,
        )
        reports = [
            _ESEFReport(attributes, payload)
            for attributes, payload in zip(selected, payloads, strict=True)
            if isinstance(payload, dict)
        ]
        if not reports:
            raise ProviderError(f"ESEF XBRL-JSON downloads failed for {clean}")
        return normalize_esef_xbrl_statements(
            clean,
            collection.company_name,
            reports,
            statement_type,
            self.name,
        )


def _select_filing_attributes(
    payload: dict[str, Any],
    country: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    by_period: dict[str, dict[str, Any]] = {}
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        attributes = item.get("attributes")
        if not isinstance(attributes, dict) or not attributes.get("json_url"):
            continue
        period = str(attributes.get("period_end") or "")
        if not period:
            continue
        current = by_period.get(period)
        if current is None or (
            str(attributes.get("country") or "").upper() == country
            and str(current.get("country") or "").upper() != country
        ):
            by_period[period] = attributes
    return [by_period[key] for key in sorted(by_period, reverse=True)[:limit]]


def _absolute_filings_url(value: str) -> str:
    if value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"https://filings.xbrl.org{value}"
    raise ProviderError("ESEF filing did not provide a valid XBRL-JSON URL")


def normalize_esef_xbrl_statements(
    symbol: str,
    company_name: str,
    reports: list[_ESEFReport],
    statement_type: StatementType,
    provider: str = "ESEF XBRL-JSON / FILINGS.XBRL.ORG",
) -> FinancialStatements:
    periods: dict[date, FinancialPeriod] = {}
    labels: dict[str, str] = {}
    sections: dict[str, str] = {}
    order: list[str] = []
    currencies: list[str] = []
    source_url = ""

    for report in reports:
        attributes = report.attributes
        source_url = source_url or _viewer_url(attributes)
        filed_date = _parse_date(attributes.get("date_added"))
        accession = str(attributes.get("fxo_id") or "")
        facts = report.payload.get("facts", {})
        if not isinstance(facts, dict):
            continue
        for fact in facts.values():
            normalized = _normalized_esef_fact(fact, statement_type)
            if normalized is None:
                continue
            concept, end_date, value, currency = normalized
            key = _canonical_metric(concept)
            period = periods.setdefault(
                end_date,
                FinancialPeriod(
                    period=f"FY {end_date.year}",
                    end_date=end_date,
                    values={},
                    source_form="ESEF AFR",
                    filed_date=filed_date,
                    accession_number=accession,
                ),
            )
            period.values.setdefault(key, value)
            if key not in order:
                order.append(key)
            labels.setdefault(key, _concept_label(concept))
            sections.setdefault(key, _metric_section(key, statement_type))
            if currency:
                currencies.append(currency)

    annual = sorted(periods.values(), key=lambda item: item.end_date or date.min, reverse=True)[:8]
    if not annual:
        raise ProviderError(f"ESEF returned no consolidated {statement_type} facts for {symbol}")
    currency = max(set(currencies), key=currencies.count) if currencies else ""
    return FinancialStatements(
        symbol=symbol,
        name=company_name or symbol,
        statement_type=statement_type,
        annual=annual,
        quarterly=[],
        currency=currency,
        provider=provider,
        quality=DataQuality.REALTIME,
        metric_labels=labels,
        metric_order=order,
        metric_sections=sections,
        source_url=source_url,
    )


def _normalized_esef_fact(
    fact: object,
    statement_type: StatementType,
) -> tuple[str, date, float, str] | None:
    if not isinstance(fact, dict):
        return None
    dimensions = fact.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    extra_dimensions = set(dimensions) - {"concept", "entity", "period", "unit", "language"}
    if extra_dimensions:
        return None
    concept = str(dimensions.get("concept") or "")
    period_text = str(dimensions.get("period") or "")
    if not concept or not period_text:
        return None
    unit = str(dimensions.get("unit") or "")
    if "iso4217:" not in unit.lower() and "shares" not in unit.lower():
        return None
    try:
        value = float(str(fact.get("value")))
    except (TypeError, ValueError):
        return None
    is_duration = "/" in period_text
    if statement_type == StatementType.BALANCE_SHEET:
        if is_duration:
            return None
        end_date = _exclusive_date(period_text)
    else:
        if not is_duration:
            return None
        start_text, end_text = period_text.split("/", 1)
        start_date = _iso_datetime(start_text).date()
        end_date = _exclusive_date(end_text)
        duration = (end_date - start_date).days + 1
        if not 250 <= duration <= 450:
            return None
        cash_flow = _is_cash_flow_concept(concept)
        if statement_type == StatementType.CASH_FLOW and not cash_flow:
            return None
        if statement_type == StatementType.INCOME and (cash_flow or _is_equity_movement(concept)):
            return None
    currency_match = re.search(r"iso4217:([A-Z]{3})", unit, re.IGNORECASE)
    currency = currency_match.group(1).upper() if currency_match else ""
    return concept, end_date, value, currency


def _is_cash_flow_concept(concept: str) -> bool:
    normalized = _local_concept(concept).lower()
    return normalized.startswith(
        (
            "adjustmentsfor",
            "cashflows",
            "effectofexchangerate",
            "incometaxespaid",
            "increasedecreaseincash",
            "inflowsofcash",
            "outflowsofcash",
            "otherinflowsofcash",
            "otheroutflowsofcash",
            "payments",
            "proceeds",
            "purchase",
            "repayments",
        )
    ) or any(
        token in normalized
        for token in (
            "classifiedasfinancingactivities",
            "classifiedasinvestingactivities",
            "classifiedasoperatingactivities",
            "increaseincashandcashequivalents",
        )
    )


def _is_equity_movement(concept: str) -> bool:
    normalized = _local_concept(concept).lower()
    return normalized.startswith(
        (
            "cancellationof",
            "increasedecreasethrough",
            "increasedecreaseinequity",
            "reductionofissuedcapital",
            "transferfrom",
        )
    )


_CANONICAL_METRICS = {
    "Revenue": "totalRevenue",
    "CostOfSales": "costOfRevenue",
    "GrossProfit": "grossProfit",
    "AdministrativeExpense": "generalAndAdministrativeExpense",
    "EmployeeBenefitsExpense": "employeeBenefitsExpense",
    "DepreciationAndAmortisationExpense": "depreciationAndAmortization",
    "InterestExpense": "interestExpense",
    "RevenueFromInterest": "interestIncome",
    "ProfitLossBeforeTax": "incomeBeforeTax",
    "IncomeTaxExpenseContinuingOperations": "taxProvision",
    "ProfitLoss": "netIncome",
    "Assets": "totalAssets",
    "Liabilities": "totalLiabilities",
    "Equity": "totalEquity",
    "EquityAndLiabilities": "liabilitiesAndEquity",
    "CashAndCashEquivalents": "cashAndCashEquivalents",
    "Inventories": "inventory",
    "Goodwill": "goodwill",
    "IntangibleAssetsOtherThanGoodwill": "intangibleAssetsNet",
    "CashFlowsFromUsedInOperatingActivities": "operatingCashFlow",
    "CashFlowsFromUsedInInvestingActivities": "investingCashFlow",
    "CashFlowsFromUsedInFinancingActivities": "financingCashFlow",
    "IncreaseDecreaseInCashAndCashEquivalents": "changesInCash",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents": "effectOfExchangeRate",
    "DividendsPaidClassifiedAsFinancingActivities": "cashDividendsPaid",
}


def _canonical_metric(concept: str) -> str:
    local = _local_concept(concept)
    return _CANONICAL_METRICS.get(local, local[:1].lower() + local[1:])


def _local_concept(concept: str) -> str:
    return concept.split(":", 1)[-1]


def _concept_label(concept: str) -> str:
    local = _local_concept(concept)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", local)
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", separated)
    return " ".join(separated.split())


def _metric_section(metric: str, statement_type: StatementType) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", metric.lower())
    if statement_type == StatementType.BALANCE_SHEET:
        if any(token in normalized for token in ("equity", "capital", "retainedearning", "reserve", "treasuryshare")):
            return "SHAREHOLDERS' EQUITY"
        if any(token in normalized for token in ("liabilit", "payable", "debt", "provision")):
            return "LIABILITIES"
        if any(token in normalized for token in ("asset", "cash", "inventory", "goodwill", "investment", "receivable")):
            return "ASSETS"
        return "SUPPLEMENTAL"
    if statement_type == StatementType.CASH_FLOW:
        if any(
            token in normalized
            for token in (
                "effectofexchange",
                "changesincash",
                "increasedecreaseincash",
                "cashandcashequivalentsatbeginning",
                "cashandcashequivalentsatend",
            )
        ):
            return "CASH RECONCILIATION / SUPPLEMENTAL"
        equity_financing = "share" in normalized and any(
            token in normalized
            for token in ("treasury", "entity", "redeem", "acquire", "repurchase", "issu")
        )
        if "financing" in normalized or equity_financing or any(
            token in normalized
            for token in (
                "dividendspaid",
                "issuingshares",
                "issueofshares",
                "treasuryshare",
                "entityshare",
                "repurchaseshare",
                "subordinatedliabilit",
                "issuanceofdebt",
                "repaymentofdebt",
            )
        ):
            return "FINANCING ACTIVITIES"
        if "investing" in normalized or any(
            token in normalized
            for token in (
                "purchaseof",
                "saleof",
                "salesof",
                "proceedsfromsale",
                "acquisition",
                "disposal",
                "obtainingcontrol",
                "losingcontrol",
            )
        ):
            return "INVESTING ACTIVITIES"
        return "OPERATING ACTIVITIES"
    if any(token in normalized for token in ("revenue", "grossprofit", "costofsales")):
        return "REVENUE / GROSS PROFIT"
    if any(token in normalized for token in ("administrative", "employee", "operatingexpense", "depreciation")):
        return "OPERATING EXPENSES"
    if any(token in normalized for token in ("operatingincome", "operatingprofit")):
        return "OPERATING RESULT"
    if any(token in normalized for token in ("interest", "beforetax", "taxexpense", "impairment", "associate")):
        return "NON-OPERATING / TAX"
    if any(token in normalized for token in ("profitloss", "netincome", "earningspershare")):
        return "NET INCOME / PER SHARE"
    return "COMPREHENSIVE / SUPPLEMENTAL"


def _viewer_url(attributes: dict[str, Any]) -> str:
    value = str(attributes.get("viewer_url") or attributes.get("report_url") or "")
    return f"https://filings.xbrl.org{value}" if value.startswith("/") else value


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _exclusive_date(value: str) -> date:
    return _iso_datetime(value).date() - timedelta(days=1)
