from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from ajax_terminal.analytics.fundamentals import (
    free_cash_flow,
    margin,
    net_debt,
    return_on_assets,
    return_on_equity,
    return_on_invested_capital,
)
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    CorporateEvent,
    DividendAnalysis,
    DividendRecord,
    Estimate,
    EstimateSet,
    FinancialAnalysis,
    FinancialMetric,
    PeerCompany,
    RelativeValuation,
    ScreenerFilter,
    ScreenerPage,
    ScreenerResult,
)
from ajax_terminal.models.quote import DataQuality, FinancialPeriod, StatementType
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache


LOGGER = logging.getLogger(__name__)
_FILTER_PATTERN = re.compile(r"^([A-Z]+)(>=|<=|>|<|=)(.+)$")
_NUMERIC_FILTERS = {
    "PRICE",
    "CHANGE",
    "MARKETCAP",
    "PE",
    "FORWARDPE",
    "DIVYIELD",
    "ROE",
    "ROIC",
    "REVENUEGROWTH",
    "MARGIN",
    "VOLUME",
}
_TEXT_FILTERS = {"COUNTRY", "SECTOR"}

# Yahoo's industry screener is not consistently available for smaller non-US
# listings. These are candidate pools, never accepted peers by themselves: each
# symbol is still checked against the target's live sector and industry profile.
_INDUSTRY_PEER_CANDIDATES: dict[str, tuple[str, ...]] = {
    "packaged foods": ("BN.PA", "NESN.SW", "MDLZ", "GIS", "KHC", "ULVR.L", "JDEP.AS"),
    "banks diversified": ("SAN.MC", "BBVA.MC", "BNP.PA", "GLE.PA", "DBK.DE", "BARC.L", "HSBA.L"),
    "consumer electronics": ("AAPL", "SONY", "6758.T", "005930.KS", "DELL", "HPQ"),
    "semiconductors": ("NVDA", "AMD", "AVGO", "INTC", "TSM", "QCOM", "ASML.AS"),
    "software infrastructure": ("MSFT", "ORCL", "ADBE", "CRM", "PANW", "CRWD", "NOW"),
    "internet content information": ("GOOGL", "META", "BIDU", "PINS", "SNAP", "RDDT"),
    "auto manufacturers": ("TSLA", "TM", "STLA", "BMW.DE", "MBG.DE", "VOW3.DE", "RACE"),
    "drug manufacturers general": ("LLY", "JNJ", "PFE", "NVS", "AZN", "GSK", "SAN.PA"),
    "oil gas integrated": ("XOM", "CVX", "SHEL", "TTE", "BP", "ENI.MI", "REP.MC"),
    "telecom services": ("VZ", "T", "DTE.DE", "TEF.MC", "ORA.PA", "VOD.L"),
    "aerospace defense": ("BA", "AIR.PA", "LMT", "RTX", "NOC", "SAF.PA", "RR.L"),
    "specialty retail": ("AMZN", "HD", "LOW", "OR.PA", "KER.PA", "ITX.MC"),
    "utilities regulated electric": ("NEE", "DUK", "SO", "IBE.MC", "ENEL.MI", "RWE.DE"),
    "insurance diversified": ("ALV.DE", "AXA.PA", "ZURN.SW", "AIG", "CB", "MUV2.DE"),
}


class EquityResearchService:
    TTL = 6 * 3600

    def __init__(
        self,
        market_service: MarketService,
        providers: list[Any] | None = None,
        cache: SQLiteCache | None = None,
    ) -> None:
        self.market_service = market_service
        self.providers = market_service.market_providers if providers is None else providers
        self.cache = cache or market_service.cache

    async def company_profile(self, symbol: str) -> CompanyProfile:
        clean = symbol.upper()
        return await self._single(
            f"research:profile:{clean}",
            "company_profile",
            (clean,),
            _profile_to_dict,
            _profile_from_dict,
            CompanyProfile(clean, clean),
        )

    async def estimates(self, symbol: str) -> EstimateSet:
        clean = symbol.upper()
        return await self._single(
            f"research:estimates:{clean}",
            "estimates",
            (clean,),
            _estimate_set_to_dict,
            _estimate_set_from_dict,
            EstimateSet(clean, clean, "", []),
        )

    async def analyst_consensus(self, symbol: str) -> AnalystConsensus:
        clean = symbol.upper()
        return await self._single(
            f"research:analyst:{clean}",
            "analyst_consensus",
            (clean,),
            _analyst_to_dict,
            _analyst_from_dict,
            AnalystConsensus(clean, clean),
        )

    async def dividends(self, symbol: str) -> DividendAnalysis:
        clean = symbol.upper()
        return await self._single(
            f"research:dividends:{clean}",
            "dividends",
            (clean,),
            _dividend_to_dict,
            _dividend_from_dict,
            DividendAnalysis(clean, clean, []),
        )

    async def events(self, symbol: str) -> list[CorporateEvent]:
        clean = symbol.upper()
        key = f"research:events:{clean}"
        cached = self.cache.get_json(key)
        if isinstance(cached, list):
            return [_event_from_dict(item, False) for item in cached if isinstance(item, dict)]
        for provider in self.providers:
            if not hasattr(provider, "events"):
                continue
            try:
                events = await provider.events(clean)
                self.cache.set_json(key, [_event_to_dict(item) for item in events], self.TTL)
                return events
            except Exception as exc:
                LOGGER.warning("events provider=%s symbol=%s error=%s", getattr(provider, "name", "?"), clean, exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, list):
            return [_event_from_dict(item, True) for item in stale if isinstance(item, dict)]
        return []

    async def event_schedule(self, symbols: list[str], days: int = 7) -> list[CorporateEvent]:
        unique = list(dict.fromkeys(symbol.upper() for symbol in symbols if symbol))
        batches = await asyncio.gather(*(self.events(symbol) for symbol in unique))
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        return sorted(
            [item for batch in batches for item in batch if now <= item.event_date <= end],
            key=lambda item: item.event_date,
        )

    async def relative_valuation(self, symbol: str, peer_symbols: list[str] | None = None) -> RelativeValuation:
        clean = symbol.upper()
        automatic = not peer_symbols
        selected = [item.upper() for item in peer_symbols or [] if item.upper() != clean]
        provider_name = ""
        target_profile = await self.company_profile(clean)
        if not selected:
            for provider in self.providers:
                if not hasattr(provider, "peers"):
                    continue
                try:
                    candidates = await provider.peers(clean, limit=16)
                    provider_name = getattr(provider, "name", "UNKNOWN")
                    selected = await self._industry_matched_peers(target_profile, candidates, limit=5)
                    if selected:
                        break
                except Exception as exc:
                    LOGGER.warning("peers provider=%s symbol=%s error=%s", getattr(provider, "name", "?"), clean, exc)
        if not selected:
            selected = await self._industry_matched_peers(
                target_profile,
                _curated_peer_candidates(target_profile),
                limit=5,
            )
            if selected:
                provider_name = "Validated industry fallback"
        symbols = [clean, *selected[:7]]

        async def peer_data(item: str) -> PeerCompany | None:
            quote, fundamentals = await asyncio.gather(
                self.market_service.quote(item),
                self.market_service.equity_fundamentals(item),
            )
            if quote.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE} or fundamentals.quality in {
                DataQuality.MOCK,
                DataQuality.UNAVAILABLE,
            }:
                return None
            return PeerCompany(
                symbol=item,
                name=fundamentals.name or quote.name,
                price=quote.price,
                market_cap=fundamentals.market_cap,
                pe=fundamentals.pe,
                forward_pe=fundamentals.forward_pe,
                ev_ebitda=fundamentals.ev_ebitda,
                price_book=fundamentals.price_book,
                revenue_growth=fundamentals.revenue_growth,
                operating_margin=fundamentals.operating_margin,
                roe=fundamentals.roe,
                dividend_yield=fundamentals.dividend_yield,
                quality=fundamentals.quality,
            )

        rows = [item for item in await asyncio.gather(*(peer_data(item) for item in symbols)) if item is not None]
        quality = _combined_quality([item.quality for item in rows])
        message = ""
        if len(rows) <= 1:
            message = "No industry-matched peers were available. Use RV TICKER PEER1 PEER2 ..."
        return RelativeValuation(
            symbol=clean,
            peers=rows,
            automatic=automatic,
            provider=provider_name or "Configured market providers",
            quality=quality,
            message=message,
            peer_sector=target_profile.sector,
            peer_industry=target_profile.industry,
        )

    async def _industry_matched_peers(
        self,
        target: CompanyProfile,
        candidates: list[str],
        *,
        limit: int,
    ) -> list[str]:
        if target.quality == DataQuality.UNAVAILABLE or not (target.industry or target.sector):
            return []
        unique = [
            item
            for item in dict.fromkeys(symbol.upper() for symbol in candidates)
            if item and item.upper() != target.symbol.upper()
        ]
        profiles = await asyncio.gather(*(self.company_profile(symbol) for symbol in unique))
        ranked = sorted(
            (
                (_peer_profile_score(target, profile), -index, profile.symbol)
                for index, profile in enumerate(profiles)
                if profile.quality != DataQuality.UNAVAILABLE
            ),
            reverse=True,
        )
        return [symbol for score, _order, symbol in ranked if score >= 100.0][:limit]

    async def financial_analysis(self, symbol: str) -> FinancialAnalysis:
        clean = symbol.upper()
        profile, estimates = await asyncio.gather(self.company_profile(clean), self.estimates(clean))
        if profile.quality == DataQuality.UNAVAILABLE:
            return FinancialAnalysis(clean, clean, "", [], {}, quality=DataQuality.UNAVAILABLE, message="Invalid or unavailable equity ticker")
        fundamentals, income, balance, cashflow = await asyncio.gather(
            self.market_service.equity_fundamentals(clean),
            self.market_service.financial_statements(clean, StatementType.INCOME),
            self.market_service.financial_statements(clean, StatementType.BALANCE_SHEET),
            self.market_service.financial_statements(clean, StatementType.CASH_FLOW),
        )
        real_statements = [
            item
            for item in (income, balance, cashflow)
            if item.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        if not real_statements:
            return FinancialAnalysis(
                clean,
                profile.name,
                profile.currency,
                [],
                {},
                provider=profile.provider,
                quality=DataQuality.UNAVAILABLE,
                message="Financial statements unavailable from configured public providers",
            )
        period_source = next(
            (
                item.annual
                for item in (income, cashflow, balance)
                if item.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE} and item.annual
            ),
            [],
        )
        actual_periods = [item.period for item in period_source[:4]]
        estimate_periods = ["FY", "FY+1", "FY+2", "FY+3"]
        categories: dict[str, list[FinancialMetric]] = {
            "INCOME STATEMENT": [],
            "CASH FLOW": [],
            "BALANCE SHEET": [],
            "RETURNS / MARGINS": [],
            "VALUATION": [],
        }
        unusable = {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        income_by_period = {item.period: item for item in income.annual} if income.quality not in unusable else {}
        balance_by_period = {item.period: item for item in balance.annual} if balance.quality not in unusable else {}
        cashflow_by_period = {item.period: item for item in cashflow.annual} if cashflow.quality not in unusable else {}
        for period in actual_periods:
            inc = income_by_period.get(period, FinancialPeriod(period, None, {})).values
            bal = balance_by_period.get(period, FinancialPeriod(period, None, {})).values
            cf = cashflow_by_period.get(period, FinancialPeriod(period, None, {})).values
            revenue = _value(inc, "totalRevenue", "operatingRevenue")
            gross_profit = _value(inc, "grossProfit")
            ebitda = _value(inc, "ebitda", "normalizedEBITDA")
            ebit = _value(inc, "ebit", "operatingIncome")
            net_income = _value(inc, "netIncome", "netIncomeApplicableToCommonShares")
            eps = _value(inc, "dilutedEPS", "basicEPS")
            operating_cf = _value(cf, "totalCashFromOperatingActivities", "operatingCashFlow")
            capex = _value(cf, "capitalExpenditures", "capitalExpenditure")
            fcf = _value(cf, "freeCashFlow")
            if fcf is None:
                fcf = free_cash_flow(operating_cf, capex)
            cash = _value(bal, "cash", "cashAndCashEquivalents", "cashCashEquivalentsAndShortTermInvestments")
            debt = _value(bal, "totalDebt", "longTermDebt")
            assets = _value(bal, "totalAssets")
            equity = _value(bal, "totalStockholderEquity", "stockholdersEquity")
            tax = _value(inc, "incomeTaxExpense", "taxProvision")
            pretax = _value(inc, "incomeBeforeTax", "pretaxIncome")
            tax_rate = tax / pretax if tax is not None and pretax not in {None, 0} else None
            _add_metrics(categories["INCOME STATEMENT"], period, {
                "Revenue": revenue, "Gross Profit": gross_profit, "EBITDA": ebitda,
                "EBIT": ebit, "Net Income": net_income, "EPS": eps,
            })
            _add_metrics(categories["CASH FLOW"], period, {
                "Operating Cash Flow": operating_cf, "Capital Expenditure": capex, "Free Cash Flow": fcf,
            })
            _add_metrics(categories["BALANCE SHEET"], period, {
                "Cash": cash, "Total Debt": debt, "Net Debt": net_debt(debt, cash),
                "Total Assets": assets, "Shareholders Equity": equity,
            })
            _add_metrics(categories["RETURNS / MARGINS"], period, {
                "Gross Margin": margin(gross_profit, revenue),
                "Operating Margin": margin(ebit, revenue),
                "Net Margin": margin(net_income, revenue),
                "ROE": return_on_equity(net_income, equity),
                "ROA": return_on_assets(net_income, assets),
                "ROIC": return_on_invested_capital(ebit, tax_rate, debt, equity, cash),
            }, unit="percent")
        for period in estimate_periods:
            revenue_estimate = _find_estimate(estimates, "Revenue", period)
            eps_estimate = _find_estimate(estimates, "EPS", period)
            _add_metrics(categories["INCOME STATEMENT"], period, {
                "Revenue": revenue_estimate.average if revenue_estimate else None,
                "Gross Profit": None,
                "EBITDA": None,
                "EBIT": None,
                "Net Income": None,
                "EPS": eps_estimate.average if eps_estimate else None,
            }, status="ESTIMATE")
        latest_period = actual_periods[0] if actual_periods else "LTM"
        valuation_values = {
            "Market Cap": fundamentals.market_cap,
            "Enterprise Value": fundamentals.enterprise_value,
            "P/E": fundamentals.pe,
            "Forward P/E": fundamentals.forward_pe,
            "EV / EBITDA": fundamentals.ev_ebitda,
            "Price / Book": fundamentals.price_book,
            "Dividend Yield": fundamentals.dividend_yield,
        }
        if fundamentals.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
            valuation_values = {key: None for key in valuation_values}
        _add_metrics(categories["VALUATION"], latest_period, valuation_values)
        quality = _combined_quality([item.quality for item in real_statements] + [estimates.quality])
        providers = ", ".join(dict.fromkeys(item.provider for item in real_statements))
        return FinancialAnalysis(
            clean,
            profile.name,
            profile.currency or income.currency,
            [*actual_periods, *estimate_periods],
            categories,
            provider=providers,
            quality=quality,
        )

    async def screener(self, filters: list[ScreenerFilter], limit: int = 30) -> ScreenerPage:
        key = "research:screener:" + ":".join(f"{item.field}{item.operator}{item.value}" for item in filters)
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            return _screener_from_dict(cached, False)
        for provider in self.providers:
            if not hasattr(provider, "screener"):
                continue
            try:
                page = await provider.screener(filters, limit=limit)
                self.cache.set_json(key, _screener_to_dict(page), 30 * 60)
                return page
            except Exception as exc:
                LOGGER.warning("screener provider=%s error=%s", getattr(provider, "name", "?"), exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            return _screener_from_dict(stale, True)
        return ScreenerPage(filters, [], "Unavailable", quality=DataQuality.UNAVAILABLE, message="Screener provider unavailable")

    async def _single(
        self,
        key: str,
        method_name: str,
        args: tuple[Any, ...],
        serializer: Callable[[Any], dict[str, Any]],
        deserializer: Callable[[dict[str, Any], bool], Any],
        unavailable: Any,
    ) -> Any:
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            return deserializer(cached, False)
        for provider in self.providers:
            if not hasattr(provider, method_name):
                continue
            try:
                value = await getattr(provider, method_name)(*args)
                self.cache.set_json(key, serializer(value), self.TTL)
                return value
            except Exception as exc:
                LOGGER.warning("research method=%s provider=%s error=%s", method_name, getattr(provider, "name", "?"), exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            return deserializer(stale, True)
        return unavailable


def parse_screener_filters(tokens: tuple[str, ...] | list[str]) -> list[ScreenerFilter]:
    filters: list[ScreenerFilter] = []
    for token in tokens:
        match = _FILTER_PATTERN.match(token.upper())
        if match is None:
            raise ValueError(f"Invalid filter '{token}'. Example: MARKETCAP>10B")
        field, operator, raw_value = match.groups()
        if field not in _NUMERIC_FILTERS | _TEXT_FILTERS:
            raise ValueError(f"Unsupported filter '{field}'")
        if field in _TEXT_FILTERS:
            if operator != "=":
                raise ValueError(f"{field} only supports '='")
            value: float | str = raw_value
        else:
            value = _parse_scaled_number(raw_value)
        filters.append(ScreenerFilter(field, operator, value))
    return filters


def _parse_scaled_number(value: str) -> float:
    multipliers = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
    suffix = value[-1:] if value[-1:] in multipliers else ""
    number = value[:-1] if suffix else value
    try:
        return float(number) * multipliers.get(suffix, 1.0)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value '{value}'") from exc


def _value(values: dict[str, float | None], *names: str) -> float | None:
    return next((values.get(name) for name in names if values.get(name) is not None), None)


def _add_metrics(
    target: list[FinancialMetric],
    period: str,
    values: dict[str, float | None],
    unit: str = "currency",
    status: str = "ACTUAL",
) -> None:
    for name, value in values.items():
        metric_unit = "multiple" if name in {"P/E", "Forward P/E", "EV / EBITDA", "Price / Book"} else unit
        if name == "Dividend Yield":
            metric_unit = "percent"
        target.append(FinancialMetric(name, value, period, metric_unit, status))


def _find_estimate(estimates: EstimateSet, metric: str, period: str) -> Estimate | None:
    return next((item for item in estimates.estimates if item.metric == metric and item.period == period), None)


def _combined_quality(values: list[DataQuality]) -> DataQuality:
    clean = [item for item in values if item != DataQuality.UNAVAILABLE]
    if not clean:
        return DataQuality.UNAVAILABLE
    if DataQuality.MOCK in clean:
        return DataQuality.MOCK
    if DataQuality.CACHED in clean:
        return DataQuality.CACHED
    if DataQuality.DELAYED in clean:
        return DataQuality.DELAYED
    return clean[0]


def _peer_profile_score(target: CompanyProfile, candidate: CompanyProfile) -> float:
    target_industry = _classification_key(target.industry)
    candidate_industry = _classification_key(candidate.industry)
    target_sector = _classification_key(target.sector)
    candidate_sector = _classification_key(candidate.sector)
    if target_industry and target_industry == candidate_industry:
        score = 100.0
    elif target_sector and target_sector == candidate_sector:
        target_tokens = set(target_industry.split())
        candidate_tokens = set(candidate_industry.split())
        overlap = target_tokens & candidate_tokens
        if not overlap:
            return 0.0
        score = 70.0 + 10.0 * len(overlap)
    else:
        return 0.0
    if target.country and target.country.casefold() == candidate.country.casefold():
        score += 8.0
    if target.exchange and target.exchange.casefold() == candidate.exchange.casefold():
        score += 4.0
    return score


def _classification_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _curated_peer_candidates(profile: CompanyProfile) -> list[str]:
    """Return only candidates for the target's normalized provider industry."""
    return list(_INDUSTRY_PEER_CANDIDATES.get(_classification_key(profile.industry), ()))


def _base_dict(value: Any) -> dict[str, Any]:
    data = asdict(value)
    data["quality"] = str(value.quality)
    data["timestamp"] = value.timestamp.isoformat()
    return data


def _quality(data: dict[str, Any], stale: bool) -> DataQuality:
    original = DataQuality(data.get("quality", DataQuality.UNAVAILABLE))
    return DataQuality.CACHED if stale and original not in {DataQuality.MOCK, DataQuality.UNAVAILABLE} else original


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _optional_dt(value: Any) -> datetime | None:
    return _dt(value) if value else None


def _optional_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _profile_to_dict(value: CompanyProfile) -> dict[str, Any]:
    return _base_dict(value)


def _profile_from_dict(data: dict[str, Any], stale: bool) -> CompanyProfile:
    copy = dict(data)
    copy["quality"] = _quality(copy, stale)
    copy["timestamp"] = _dt(copy.get("timestamp"))
    return CompanyProfile(**copy)


def _estimate_set_to_dict(value: EstimateSet) -> dict[str, Any]:
    data = _base_dict(value)
    data["earnings_date"] = value.earnings_date.isoformat() if value.earnings_date else None
    data["estimates"] = [
        {**asdict(item), "end_date": item.end_date.isoformat() if item.end_date else None}
        for item in value.estimates
    ]
    return data


def _estimate_set_from_dict(data: dict[str, Any], stale: bool) -> EstimateSet:
    return EstimateSet(
        symbol=data.get("symbol", ""),
        name=data.get("name", ""),
        currency=data.get("currency", ""),
        estimates=[Estimate(**{**item, "end_date": _optional_date(item.get("end_date"))}) for item in data.get("estimates", [])],
        earnings_date=_optional_dt(data.get("earnings_date")),
        provider=data.get("provider", "UNKNOWN"),
        quality=_quality(data, stale),
        timestamp=_dt(data.get("timestamp")),
    )


def _analyst_to_dict(value: AnalystConsensus) -> dict[str, Any]:
    return _base_dict(value)


def _analyst_from_dict(data: dict[str, Any], stale: bool) -> AnalystConsensus:
    copy = dict(data)
    copy["quality"] = _quality(copy, stale)
    copy["timestamp"] = _dt(copy.get("timestamp"))
    return AnalystConsensus(**copy)


def _dividend_to_dict(value: DividendAnalysis) -> dict[str, Any]:
    data = _base_dict(value)
    data["records"] = [{**asdict(item), "ex_date": item.ex_date.isoformat()} for item in value.records]
    data["ex_dividend_date"] = value.ex_dividend_date.isoformat() if value.ex_dividend_date else None
    data["payment_date"] = value.payment_date.isoformat() if value.payment_date else None
    return data


def _dividend_from_dict(data: dict[str, Any], stale: bool) -> DividendAnalysis:
    return DividendAnalysis(
        symbol=data.get("symbol", ""),
        name=data.get("name", ""),
        records=[DividendRecord(_optional_date(item.get("ex_date")) or date.min, float(item.get("amount", 0)), item.get("currency", "")) for item in data.get("records", [])],
        indicated_rate=data.get("indicated_rate"),
        yield_percent=data.get("yield_percent"),
        payout_ratio_percent=data.get("payout_ratio_percent"),
        five_year_average_yield=data.get("five_year_average_yield"),
        ex_dividend_date=_optional_date(data.get("ex_dividend_date")),
        payment_date=_optional_date(data.get("payment_date")),
        currency=data.get("currency", ""),
        provider=data.get("provider", "UNKNOWN"),
        quality=_quality(data, stale),
        timestamp=_dt(data.get("timestamp")),
    )


def _event_to_dict(value: CorporateEvent) -> dict[str, Any]:
    data = _base_dict(value)
    data["event_date"] = value.event_date.isoformat()
    return data


def _event_from_dict(data: dict[str, Any], stale: bool) -> CorporateEvent:
    copy = dict(data)
    copy["event_date"] = _dt(copy.get("event_date"))
    copy["quality"] = _quality(copy, stale)
    copy["timestamp"] = _dt(copy.get("timestamp"))
    return CorporateEvent(**copy)


def _screener_to_dict(value: ScreenerPage) -> dict[str, Any]:
    data = _base_dict(value)
    data["filters"] = [asdict(item) for item in value.filters]
    data["results"] = [{**asdict(item), "quality": str(item.quality)} for item in value.results]
    return data


def _screener_from_dict(data: dict[str, Any], stale: bool) -> ScreenerPage:
    results = []
    for item in data.get("results", []):
        copy = dict(item)
        original = DataQuality(copy.get("quality", DataQuality.UNAVAILABLE))
        copy["quality"] = DataQuality.CACHED if stale and original != DataQuality.UNAVAILABLE else original
        results.append(ScreenerResult(**copy))
    return ScreenerPage(
        filters=[ScreenerFilter(**item) for item in data.get("filters", [])],
        results=results,
        universe=data.get("universe", ""),
        provider=data.get("provider", "UNKNOWN"),
        quality=_quality(data, stale),
        timestamp=_dt(data.get("timestamp")),
        message=data.get("message", ""),
    )
