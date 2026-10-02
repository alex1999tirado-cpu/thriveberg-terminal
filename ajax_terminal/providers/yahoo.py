from __future__ import annotations

import asyncio
import http.cookiejar
import json
import math
import re
import threading
import urllib.parse
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from ajax_terminal.analytics.fundamentals import return_on_invested_capital
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    CorporateAction,
    CorporateActionType,
    CorporateEvent,
    DividendAnalysis,
    DividendRecord,
    Estimate,
    EstimateSet,
    ScreenerFilter,
    ScreenerPage,
    ScreenerResult,
)
from ajax_terminal.models.quote import (
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    PriceBar,
    PriceHistory,
    Quote,
    StatementType,
)
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.utils.url_security import require_https_url
from ajax_terminal.utils.periods import (
    history_period_config,
    normalize_history_interval,
    normalize_history_period,
)
from ajax_terminal.utils.symbols import display_fx_pair, is_fx_pair, normalize_symbol


class YahooProvider:
    name = "Yahoo Finance"

    def __init__(self) -> None:
        self._summary_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}

    async def quote(self, symbol: str) -> Quote:
        yahoo_symbol = _to_yahoo_symbol(symbol)
        payload = await _fetch_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?range=1d&interval=1m"
        )
        return normalize_yahoo_quote(symbol, payload, self.name)

    async def fundamentals(self, symbol: str) -> EquityFundamentals:
        yahoo_symbol = normalize_symbol(symbol)
        payload = await _fetch_json(
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{urllib.parse.quote(yahoo_symbol)}?modules=price,summaryDetail,defaultKeyStatistics,financialData",
            authenticated=True,
        )
        return normalize_yahoo_fundamentals(symbol, payload, self.name)

    async def historical(self, symbol: str, period: str = "1Y", interval: str | None = None) -> PriceHistory:
        normalized = normalize_history_period(period)
        yahoo_period, _, _ = history_period_config(normalized)
        selected_interval = normalize_history_interval(normalized, interval)
        yahoo_symbol = _to_yahoo_symbol(symbol)
        payload = await _fetch_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}"
            f"?range={yahoo_period}&interval={selected_interval}&events=div%2Csplits"
        )
        return normalize_yahoo_history(symbol, payload, normalized, selected_interval, self.name)

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
    ) -> FinancialStatements:
        yahoo_symbol = normalize_symbol(symbol)
        annual_module, quarterly_module = _statement_modules(statement_type)
        fields = _timeseries_fields(statement_type)
        summary_result, timeseries_result = await asyncio.gather(
            self._summary(symbol, "price", annual_module, quarterly_module),
            _fetch_statement_timeseries(yahoo_symbol, fields),
            return_exceptions=True,
        )
        candidates: list[FinancialStatements] = []
        price: dict[str, Any] = {}
        if isinstance(summary_result, dict):
            price = summary_result.get("price", {})
            try:
                candidates.append(
                    normalize_yahoo_financial_statements(
                        symbol,
                        {"quoteSummary": {"result": [summary_result]}},
                        statement_type,
                        self.name,
                    )
                )
            except Exception:
                pass
        if isinstance(timeseries_result, dict):
            try:
                candidates.append(
                    normalize_yahoo_timeseries_statements(
                        symbol,
                        timeseries_result,
                        price,
                        statement_type,
                        self.name,
                    )
                )
            except Exception:
                pass
        if not candidates:
            errors = [
                str(result)
                for result in (summary_result, timeseries_result)
                if isinstance(result, Exception)
            ]
            raise ProviderError(
                f"Yahoo returned no {statement_type} statements for {symbol}: "
                f"{' | '.join(errors) or 'empty response'}"
            )
        merged = candidates[0]
        for candidate in candidates[1:]:
            merged = merge_yahoo_financial_statements(merged, candidate)
        return merged

    async def company_profile(self, symbol: str) -> CompanyProfile:
        data = await self._summary(symbol, "assetProfile", "price")
        profile = data.get("assetProfile", {})
        price = data.get("price", {})
        return CompanyProfile(
            symbol=symbol.upper(),
            name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or symbol.upper()),
            exchange=str(_raw(price.get("exchangeName")) or _raw(price.get("exchange")) or ""),
            sector=str(profile.get("sector") or ""),
            industry=str(profile.get("industry") or ""),
            country=str(profile.get("country") or ""),
            website=str(profile.get("website") or ""),
            employees=_int_or_none(profile.get("fullTimeEmployees")),
            description=str(profile.get("longBusinessSummary") or ""),
            currency=str(_raw(price.get("currency")) or ""),
            provider=self.name,
            quality=DataQuality.DELAYED,
        )

    async def estimates(self, symbol: str) -> EstimateSet:
        data = await self._summary(symbol, "price", "financialData", "earningsTrend", "calendarEvents")
        price = data.get("price", {})
        currency = str(
            _raw(data.get("financialData", {}).get("financialCurrency"))
            or _raw(price.get("currency"))
            or ""
        )
        estimates: list[Estimate] = []
        period_names = {"0q": "CURRENT Q", "+1q": "NEXT Q", "0y": "FY", "+1y": "FY+1", "+2y": "FY+2", "+3y": "FY+3"}
        for trend in data.get("earningsTrend", {}).get("trend", []):
            period = period_names.get(str(trend.get("period")))
            if period is None:
                continue
            end_date = _date_from_value(trend.get("endDate"))
            for metric, node_name in (("Revenue", "revenueEstimate"), ("EPS", "earningsEstimate")):
                node = trend.get(node_name, {})
                eps_trend = trend.get("epsTrend", {}) if metric == "EPS" else {}
                current = _number(eps_trend.get("current"))
                estimates.append(
                    Estimate(
                        metric=metric,
                        period=period,
                        end_date=end_date,
                        average=_number(node.get("avg")),
                        low=_number(node.get("low")),
                        high=_number(node.get("high")),
                        year_ago=_number(node.get("yearAgoRevenue" if metric == "Revenue" else "yearAgoEps")),
                        growth_percent=_percent(node.get("growth") or trend.get("growth")),
                        analyst_count=_int_or_none(node.get("numberOfAnalysts")),
                        revision_7d=_revision(current, _number(eps_trend.get("7daysAgo"))),
                        revision_30d=_revision(current, _number(eps_trend.get("30daysAgo"))),
                    )
                )
        earnings = data.get("calendarEvents", {}).get("earnings", {})
        earnings_dates = earnings.get("earningsDate") or []
        return EstimateSet(
            symbol=symbol.upper(),
            name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or symbol.upper()),
            currency=currency,
            estimates=estimates,
            earnings_date=_datetime_from_value(earnings_dates[0]) if earnings_dates else None,
            provider=self.name,
            quality=DataQuality.DELAYED if estimates else DataQuality.UNAVAILABLE,
        )

    async def analyst_consensus(self, symbol: str) -> AnalystConsensus:
        data = await self._summary(symbol, "price", "financialData", "recommendationTrend")
        price = data.get("price", {})
        financial = data.get("financialData", {})
        trends = data.get("recommendationTrend", {}).get("trend") or []
        current = next((item for item in trends if item.get("period") == "0m"), trends[0] if trends else {})
        current_price = _number(financial.get("currentPrice")) or _number(price.get("regularMarketPrice"))
        target_mean = _number(financial.get("targetMeanPrice"))
        upside = None
        if current_price not in {None, 0} and target_mean is not None:
            upside = (target_mean / current_price - 1.0) * 100.0
        return AnalystConsensus(
            symbol=symbol.upper(),
            name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or symbol.upper()),
            recommendation=str(financial.get("recommendationKey") or "").upper(),
            recommendation_score=_number(financial.get("recommendationMean")),
            analyst_count=_int_or_none(financial.get("numberOfAnalystOpinions")),
            strong_buy=_int_or_none(current.get("strongBuy")),
            buy=_int_or_none(current.get("buy")),
            hold=_int_or_none(current.get("hold")),
            sell=_int_or_none(current.get("sell")),
            strong_sell=_int_or_none(current.get("strongSell")),
            target_low=_number(financial.get("targetLowPrice")),
            target_mean=target_mean,
            target_median=_number(financial.get("targetMedianPrice")),
            target_high=_number(financial.get("targetHighPrice")),
            current_price=current_price,
            upside_percent=upside,
            currency=str(_raw(price.get("currency")) or ""),
            provider=self.name,
            quality=DataQuality.DELAYED if financial else DataQuality.UNAVAILABLE,
        )

    async def dividends(self, symbol: str) -> DividendAnalysis:
        data = await self._summary(symbol, "price", "summaryDetail", "calendarEvents")
        price = data.get("price", {})
        summary = data.get("summaryDetail", {})
        calendar = data.get("calendarEvents", {})
        yahoo_symbol = normalize_symbol(symbol)
        chart = await _fetch_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(yahoo_symbol)}?range=max&interval=1mo&events=div"
        )
        result = chart.get("chart", {}).get("result") or []
        event_nodes = result[0].get("events", {}).get("dividends", {}) if result else {}
        records: list[DividendRecord] = []
        for node in event_nodes.values():
            event_date = _date_from_value(node.get("date"))
            amount = _number(node.get("amount"))
            if event_date is not None and amount is not None:
                records.append(DividendRecord(event_date, amount, str(_raw(price.get("currency")) or "")))
        records.sort(key=lambda item: item.ex_date, reverse=True)
        return DividendAnalysis(
            symbol=symbol.upper(),
            name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or symbol.upper()),
            records=records,
            indicated_rate=_number(summary.get("dividendRate")),
            yield_percent=_percent(summary.get("dividendYield")),
            payout_ratio_percent=_percent(summary.get("payoutRatio")),
            five_year_average_yield=_number(summary.get("fiveYearAvgDividendYield")),
            ex_dividend_date=_date_from_value(calendar.get("exDividendDate")),
            payment_date=_date_from_value(calendar.get("dividendDate")),
            currency=str(_raw(price.get("currency")) or ""),
            provider=self.name,
            quality=DataQuality.DELAYED,
        )

    async def corporate_actions(self, symbol: str) -> list[CorporateAction]:
        yahoo_symbol = _to_yahoo_symbol(symbol)
        payload = await _fetch_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(yahoo_symbol)}?range=max&interval=1mo&events=div%2Csplits"
        )
        result = payload.get("chart", {}).get("result") or []
        if not result:
            raise ProviderError(f"Yahoo corporate actions unavailable for {symbol}")
        data = result[0]
        currency = str(data.get("meta", {}).get("currency") or "").upper()
        events = data.get("events", {})
        actions: list[CorporateAction] = []
        for node in events.get("dividends", {}).values():
            effective_date = _date_from_value(node.get("date"))
            amount = _number(node.get("amount"))
            if effective_date is None or amount is None or amount <= 0:
                continue
            identifier = f"YAHOO:{yahoo_symbol}:DIVIDEND:{effective_date.isoformat()}:{amount:.10g}"
            actions.append(
                CorporateAction(
                    identifier,
                    symbol.upper(),
                    CorporateActionType.DIVIDEND,
                    effective_date,
                    amount=amount,
                    currency=currency,
                    provider=self.name,
                    quality=DataQuality.DELAYED,
                )
            )
        for node in events.get("splits", {}).values():
            effective_date = _date_from_value(node.get("date"))
            numerator = _number(node.get("numerator"))
            denominator = _number(node.get("denominator"))
            if numerator is None or denominator in {None, 0}:
                split_text = str(node.get("splitRatio") or "")
                match = re.fullmatch(r"\s*([0-9.]+)\s*[:/]\s*([0-9.]+)\s*", split_text)
                if match:
                    numerator = _number(match.group(1))
                    denominator = _number(match.group(2))
            if (
                effective_date is None
                or numerator is None
                or denominator is None
                or numerator <= 0
                or denominator <= 0
            ):
                continue
            identifier = (
                f"YAHOO:{yahoo_symbol}:SPLIT:{effective_date.isoformat()}:"
                f"{numerator:.10g}:{denominator:.10g}"
            )
            actions.append(
                CorporateAction(
                    identifier,
                    symbol.upper(),
                    CorporateActionType.SPLIT,
                    effective_date,
                    currency=currency,
                    numerator=numerator,
                    denominator=denominator,
                    provider=self.name,
                    quality=DataQuality.DELAYED,
                )
            )
        return sorted(actions, key=lambda item: (item.effective_date, item.action_type, item.action_id))

    async def events(self, symbol: str) -> list[CorporateEvent]:
        data = await self._summary(symbol, "price", "calendarEvents")
        price = data.get("price", {})
        calendar = data.get("calendarEvents", {})
        company = str(_raw(price.get("shortName")) or _raw(price.get("longName")) or symbol.upper())
        events: list[CorporateEvent] = []
        earnings = calendar.get("earnings", {})
        for node in earnings.get("earningsDate") or []:
            event_date = _datetime_from_value(node)
            if event_date is not None:
                consensus = _number(earnings.get("earningsAverage"))
                detail = f"EPS consensus {consensus:.2f}" if consensus is not None else "Earnings release"
                events.append(CorporateEvent(symbol.upper(), company, "EARNINGS", event_date, detail, bool(earnings.get("isEarningsDateEstimate")), self.name, DataQuality.DELAYED))
        for field, event_type in (("exDividendDate", "EX-DIVIDEND"), ("dividendDate", "DIVIDEND PAYMENT")):
            event_date = _datetime_from_value(calendar.get(field))
            if event_date is not None:
                events.append(CorporateEvent(symbol.upper(), company, event_type, event_date, "", False, self.name, DataQuality.DELAYED))
        return sorted(events, key=lambda item: item.event_date)

    async def peers(self, symbol: str, limit: int = 5) -> list[str]:
        yahoo_symbol = normalize_symbol(symbol)
        summary = await self._summary(symbol, "assetProfile", "price")
        profile = summary.get("assetProfile", {})
        price = summary.get("price", {})
        industry = str(profile.get("industry") or "").strip()
        if not industry:
            return []
        company_name = str(_raw(price.get("longName")) or _raw(price.get("shortName")) or "")
        recommendations, screened, searched = await asyncio.gather(
            self._recommended_symbols(yahoo_symbol),
            self._industry_peer_candidates(industry, str(profile.get("country") or "")),
            self._business_name_candidates(company_name),
        )
        target_currency = str(_raw(price.get("currency")) or "")
        target_market_cap = _number(price.get("marketCap"))
        target_text = " ".join(
            (
                company_name,
                industry,
                str(profile.get("longBusinessSummary") or ""),
            )
        )
        recommendation_set = set(recommendations)
        ranked: list[tuple[float, str, str]] = []
        for node in screened:
            candidate_symbol = str(node.get("symbol") or "").upper()
            if not candidate_symbol or candidate_symbol == yahoo_symbol.upper():
                continue
            name = str(node.get("longName") or node.get("shortName") or candidate_symbol)
            score = _peer_candidate_score(
                target_text,
                target_currency,
                target_market_cap,
                node,
                recommended=candidate_symbol in recommendation_set,
            )
            ranked.append((score, candidate_symbol, _peer_name_key(name)))
        for index, candidate_symbol in enumerate(recommendations):
            if candidate_symbol != yahoo_symbol.upper() and not any(item[1] == candidate_symbol for item in ranked):
                ranked.append((25.0 - index, candidate_symbol, candidate_symbol))
        for index, (candidate_symbol, candidate_name) in enumerate(searched):
            if candidate_symbol == yahoo_symbol.upper() or any(item[1] == candidate_symbol for item in ranked):
                continue
            overlap = len(_business_tokens(target_text) & _business_tokens(candidate_name))
            ranked.append((145.0 + min(overlap, 3) * 18.0 - index, candidate_symbol, _peer_name_key(candidate_name)))
        selected: list[str] = []
        seen_companies: set[str] = set()
        for _score, candidate_symbol, company_key in sorted(ranked, reverse=True):
            if company_key in seen_companies:
                continue
            selected.append(candidate_symbol)
            seen_companies.add(company_key)
            if len(selected) >= limit:
                break
        return selected

    async def _recommended_symbols(self, yahoo_symbol: str) -> list[str]:
        try:
            payload = await _fetch_json(
                "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/"
                f"{urllib.parse.quote(yahoo_symbol)}",
                authenticated=True,
            )
        except ProviderError:
            return []
        result = payload.get("finance", {}).get("result") or []
        if not result:
            return []
        return [
            str(item.get("symbol", "")).upper()
            for item in result[0].get("recommendedSymbols", [])
            if item.get("symbol")
        ]

    async def _business_name_candidates(self, company_name: str) -> list[tuple[str, str]]:
        terms = _peer_search_terms(company_name)
        if not terms:
            return []
        searches = await asyncio.gather(*(self.search(term, limit=12) for term in terms), return_exceptions=True)
        candidates: list[tuple[str, str]] = []
        for result in searches:
            if isinstance(result, Exception):
                continue
            for candidate_symbol, candidate_name, quote_type in result:
                if quote_type == "EQUITY":
                    candidates.append((candidate_symbol, candidate_name))
        return list(dict.fromkeys(candidates))

    async def _industry_peer_candidates(self, industry: str, country: str) -> list[dict[str, Any]]:
        industry_query: dict[str, Any] = {"operator": "EQ", "operands": ["industry", industry]}
        regions = _peer_regions(country)
        query = industry_query
        if regions:
            region_nodes = [{"operator": "EQ", "operands": ["region", region]} for region in regions]
            region_query = region_nodes[0] if len(region_nodes) == 1 else {"operator": "OR", "operands": region_nodes}
            query = {"operator": "AND", "operands": [industry_query, region_query]}
        body = {
            "offset": 0,
            "size": 160,
            "sortField": "intradaymarketcap",
            "sortType": "DESC",
            "quoteType": "EQUITY",
            "query": query,
            "userId": "",
            "userIdType": "guid",
        }
        try:
            payload = await _post_json("https://query1.finance.yahoo.com/v1/finance/screener", body, timeout=12)
        except ProviderError:
            return []
        result = payload.get("finance", {}).get("result") or []
        return [item for item in (result[0].get("quotes", []) if result else []) if isinstance(item, dict)]

    async def screener(self, filters: list[ScreenerFilter], limit: int = 30) -> ScreenerPage:
        query = urllib.parse.urlencode({"formatted": "false", "scrIds": "most_actives", "count": "100"})
        payload = await _fetch_json(
            f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?{query}",
            authenticated=True,
        )
        nodes = (payload.get("finance", {}).get("result") or [{}])[0].get("quotes", [])
        results = [_normalize_screener_result(node, self.name) for node in nodes]
        advanced = {"ROE", "ROIC", "REVENUEGROWTH", "MARGIN", "SECTOR"}
        requested_fields = {item.field for item in filters}
        simple_filters = [item for item in filters if item.field not in advanced]
        enrichment_candidates = [
            item for item in results if all(_matches_filter(item, item_filter) for item_filter in simple_filters)
        ]
        if requested_fields & advanced:
            await self._enrich_screener(enrichment_candidates[:30], requested_fields)
        filtered = [item for item in results if all(_matches_filter(item, item_filter) for item_filter in filters)]
        return ScreenerPage(
            filters=filters,
            results=filtered[:limit],
            universe="Yahoo Most Active Equities (up to 100)",
            provider=self.name,
            quality=DataQuality.DELAYED,
            message="Public screener universe; results are not an exhaustive global equity database.",
        )

    async def equity_universe_page(
        self,
        offset: int = 0,
        limit: int = 20,
        *,
        minimum_market_cap: float = 0,
        maximum_market_cap: float | None = None,
        industry: str = "",
        exchanges: tuple[str, ...] = (),
    ) -> tuple[list[str], int]:
        """Return one market-cap-ranked page of Yahoo equity listings."""
        clean_offset = max(0, int(offset))
        clean_limit = max(1, min(100, int(limit)))
        filters: list[dict[str, Any]] = [
            {"operator": "GT", "operands": ["intradaymarketcap", max(0, minimum_market_cap)]}
        ]
        if maximum_market_cap is not None:
            filters.append({"operator": "LT", "operands": ["intradaymarketcap", maximum_market_cap]})
        if industry:
            filters.append({"operator": "EQ", "operands": ["industry", industry]})
        if exchanges:
            exchange_filters = [
                {"operator": "EQ", "operands": ["exchange", exchange.upper()]}
                for exchange in exchanges
            ]
            filters.append(
                exchange_filters[0]
                if len(exchange_filters) == 1
                else {"operator": "OR", "operands": exchange_filters}
            )
        query = filters[0] if len(filters) == 1 else {"operator": "AND", "operands": filters}
        body = {
            "offset": clean_offset,
            "size": clean_limit,
            "sortField": "intradaymarketcap",
            "sortType": "DESC",
            "quoteType": "EQUITY",
            "query": query,
            "userId": "",
            "userIdType": "guid",
        }
        payload = await _post_json(
            "https://query1.finance.yahoo.com/v1/finance/screener",
            body,
            timeout=20,
        )
        result = payload.get("finance", {}).get("result") or []
        if not result:
            raise ProviderError("Yahoo returned no global equity universe")
        page = result[0]
        symbols = list(
            dict.fromkeys(
                str(item.get("symbol") or "").strip().upper()
                for item in page.get("quotes", [])
                if item.get("symbol")
                and str(item.get("quoteType") or "EQUITY").upper() == "EQUITY"
            )
        )
        return symbols, max(int(page.get("total") or len(symbols)), len(symbols))

    async def _enrich_screener(self, results: list[ScreenerResult], requested_fields: set[str]) -> None:
        semaphore = asyncio.Semaphore(6)

        async def enrich(result: ScreenerResult) -> None:
            async with semaphore:
                try:
                    data = await self._summary(
                        result.symbol,
                        "assetProfile",
                        "price",
                        "summaryDetail",
                        "defaultKeyStatistics",
                        "financialData",
                    )
                except Exception:
                    return
                profile = data.get("assetProfile", {})
                summary = data.get("summaryDetail", {})
                financial = data.get("financialData", {})
                result.pe = _number(summary.get("trailingPE")) or result.pe
                result.dividend_yield = _percent(summary.get("dividendYield"))
                result.roe = _percent(financial.get("returnOnEquity"))
                result.revenue_growth = _percent(financial.get("revenueGrowth"))
                result.operating_margin = _percent(financial.get("operatingMargins"))
                result.sector = str(profile.get("sector") or "")
                result.country = str(profile.get("country") or result.country)
                if "ROIC" in requested_fields:
                    result.roic = await self._calculated_roic(result.symbol)

        await asyncio.gather(*(enrich(item) for item in results))

    async def _calculated_roic(self, symbol: str) -> float | None:
        yahoo_symbol = normalize_symbol(symbol)
        fields = (
            "annualEBIT",
            "annualTaxProvision",
            "annualPretaxIncome",
            "annualTotalDebt",
            "annualStockholdersEquity",
            "annualCashCashEquivalentsAndShortTermInvestments",
        )
        now = int(datetime.now(timezone.utc).timestamp())
        query = urllib.parse.urlencode(
            {
                "symbol": yahoo_symbol,
                "type": ",".join(fields),
                "period1": now - 3 * 366 * 24 * 3600,
                "period2": now + 2 * 24 * 3600,
            }
        )
        payload = await _fetch_json(
            "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
            f"{urllib.parse.quote(yahoo_symbol)}?{query}",
            timeout=10,
        )
        result = payload.get("timeseries", {}).get("result") or []
        periods, _currency = _timeseries_periods(result, "annual")
        if not periods:
            return None
        values = periods[0].values
        ebit = _value_from_names(values, "ebit")
        tax = _value_from_names(values, "taxProvision")
        pretax = _value_from_names(values, "pretaxIncome")
        tax_rate = tax / pretax if tax is not None and pretax not in {None, 0} else None
        debt = _value_from_names(values, "totalDebt")
        equity = _value_from_names(values, "stockholdersEquity")
        cash = _value_from_names(values, "cashCashEquivalentsAndShortTermInvestments")
        return return_on_invested_capital(ebit, tax_rate, debt, equity, cash)

    async def _summary(self, symbol: str, *modules: str) -> dict[str, Any]:
        key = (normalize_symbol(symbol), tuple(sorted(modules)))
        cached = self._summary_cache.get(key)
        if cached is not None:
            return cached
        module_list = ",".join(modules)
        payload = await _fetch_json(
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{urllib.parse.quote(key[0])}?modules={urllib.parse.quote(module_list, safe=',')}",
            authenticated=True,
        )
        result = payload.get("quoteSummary", {}).get("result") or []
        if not result:
            raise ProviderError(f"Yahoo research data unavailable for {symbol}")
        self._summary_cache[key] = result[0]
        return result[0]

    async def search(self, query: str, limit: int = 10) -> list[tuple[str, str, str]]:
        payload = await _fetch_json(
            "https://query1.finance.yahoo.com/v1/finance/search?"
            f"q={urllib.parse.quote(query)}&quotesCount={limit}&newsCount=0"
        )
        results: list[tuple[str, str, str]] = []
        for item in payload.get("quotes", []):
            symbol = item.get("symbol")
            if not symbol:
                continue
            name = item.get("longname") or item.get("shortname") or symbol
            quote_type = item.get("quoteType") or item.get("typeDisp") or "MARKET"
            results.append((str(symbol).upper(), str(name), str(quote_type).upper()))
        return results[:limit]


def normalize_yahoo_quote(request_symbol: str, payload: dict[str, Any], provider: str = "Yahoo Finance") -> Quote:
    chart = payload.get("chart", {})
    result = chart.get("result") or []
    if not result:
        raise ProviderError(f"Yahoo quote unavailable for {request_symbol}: {chart.get('error')}")
    data = result[0]
    meta = data.get("meta", {})
    indicators = data.get("indicators", {}).get("quote", [{}])[0]
    closes = [item for item in indicators.get("close", []) if item is not None]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = price - previous if price is not None and previous else None
    change_pct = change / previous * 100.0 if change is not None and previous else None
    requested = request_symbol.upper().replace("/", "")
    name = display_fx_pair(requested) if is_fx_pair(requested) else meta.get("symbol", requested)
    return Quote(
        symbol=requested,
        name=name,
        price=price,
        change=change,
        change_percent=change_pct,
        currency=meta.get("currency", ""),
        asset_class="FX" if is_fx_pair(requested) else "MARKET",
        day_high=meta.get("regularMarketDayHigh"),
        day_low=meta.get("regularMarketDayLow"),
        week_52_high=meta.get("fiftyTwoWeekHigh"),
        week_52_low=meta.get("fiftyTwoWeekLow"),
        open_price=meta.get("regularMarketOpen") or _last_value(indicators.get("open", [])),
        previous_close=previous,
        volume=meta.get("regularMarketVolume") or _last_value(indicators.get("volume", [])),
        market_status=str(meta.get("marketState") or ""),
        provider=provider,
        quality=DataQuality.DELAYED,
        timestamp=datetime.fromtimestamp(meta.get("regularMarketTime", datetime.now().timestamp()), timezone.utc),
        bid=_number(meta.get("bid")),
        ask=_number(meta.get("ask")),
    )


def normalize_yahoo_fundamentals(
    request_symbol: str,
    payload: dict[str, Any],
    provider: str = "Yahoo Finance",
) -> EquityFundamentals:
    result = payload.get("quoteSummary", {}).get("result") or []
    if not result:
        raise ProviderError(f"Yahoo fundamentals unavailable for {request_symbol}")
    data = result[0]
    price = data.get("price", {})
    summary = data.get("summaryDetail", {})
    stats = data.get("defaultKeyStatistics", {})
    financial = data.get("financialData", {})
    return EquityFundamentals(
        symbol=request_symbol.upper(),
        name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or request_symbol.upper()),
        market_cap=_raw(price.get("marketCap")),
        enterprise_value=_raw(stats.get("enterpriseValue")),
        pe=_raw(summary.get("trailingPE")),
        forward_pe=_raw(summary.get("forwardPE")),
        ev_ebitda=_raw(stats.get("enterpriseToEbitda")),
        price_book=_raw(stats.get("priceToBook")),
        dividend_yield=_as_percent(summary.get("dividendYield")),
        revenue=_raw(financial.get("totalRevenue")),
        ebitda=_raw(financial.get("ebitda")),
        net_income=_raw(stats.get("netIncomeToCommon")),
        eps=_raw(stats.get("trailingEps")),
        free_cash_flow=_raw(financial.get("freeCashflow")),
        roe=_as_percent(financial.get("returnOnEquity")),
        gross_profit=_raw(financial.get("grossProfits")),
        operating_cash_flow=_raw(financial.get("operatingCashflow")),
        gross_margin=_as_percent(financial.get("grossMargins")),
        operating_margin=_as_percent(financial.get("operatingMargins")),
        profit_margin=_as_percent(financial.get("profitMargins")),
        revenue_growth=_as_percent(financial.get("revenueGrowth")),
        earnings_growth=_as_percent(financial.get("earningsGrowth")),
        roa=_as_percent(financial.get("returnOnAssets")),
        total_cash=_raw(financial.get("totalCash")),
        total_debt=_raw(financial.get("totalDebt")),
        net_debt=_net_debt(financial),
        beta=_raw(stats.get("beta")),
        shares_outstanding=_raw(stats.get("sharesOutstanding")),
        provider=provider,
        quality=DataQuality.DELAYED,
    )


def normalize_yahoo_history(
    request_symbol: str,
    payload: dict[str, Any],
    period: str,
    interval: str,
    provider: str = "Yahoo Finance",
) -> PriceHistory:
    chart = payload.get("chart", {})
    result = chart.get("result") or []
    if not result:
        raise ProviderError(f"Yahoo history unavailable for {request_symbol}: {chart.get('error')}")
    data = result[0]
    meta = data.get("meta", {})
    timestamps = data.get("timestamp") or []
    indicators = data.get("indicators", {}).get("quote", [{}])[0]
    opens = indicators.get("open") or []
    highs = indicators.get("high") or []
    lows = indicators.get("low") or []
    closes = indicators.get("close") or []
    volumes = indicators.get("volume") or []
    adjusted = data.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose") or []
    bars: list[PriceBar] = []
    for index, unix_time in enumerate(timestamps):
        close = _at(closes, index)
        if close is None:
            continue
        open_price = _at(opens, index) or close
        high = _at(highs, index) or max(open_price, close)
        low = _at(lows, index) or min(open_price, close)
        bars.append(
            PriceBar(
                timestamp=datetime.fromtimestamp(unix_time, timezone.utc),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=_float_or_none(_at(volumes, index)),
                adjusted_close=_float_or_none(_at(adjusted, index)),
            )
        )
    if not bars:
        raise ProviderError(f"Yahoo returned no historical bars for {request_symbol}")
    clean = request_symbol.upper().replace("/", "")
    return PriceHistory(
        symbol=clean,
        period=period,
        interval=interval,
        bars=bars,
        currency=meta.get("currency", ""),
        provider=provider,
        quality=DataQuality.DELAYED,
        timestamp=bars[-1].timestamp,
    )


def normalize_yahoo_financial_statements(
    request_symbol: str,
    payload: dict[str, Any],
    statement_type: StatementType,
    provider: str = "Yahoo Finance",
) -> FinancialStatements:
    result = payload.get("quoteSummary", {}).get("result") or []
    if not result:
        raise ProviderError(f"Yahoo financial statements unavailable for {request_symbol}")
    data = result[0]
    annual_module, quarterly_module = _statement_modules(statement_type)
    price = data.get("price", {})
    annual = _normalize_statement_periods(_statement_records(data.get(annual_module, {})), quarterly=False)
    quarterly = _normalize_statement_periods(_statement_records(data.get(quarterly_module, {})), quarterly=True)
    if not annual and not quarterly:
        raise ProviderError(f"Yahoo returned no {statement_type} history for {request_symbol}")
    return FinancialStatements(
        symbol=request_symbol.upper(),
        name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or request_symbol.upper()),
        statement_type=statement_type,
        annual=annual,
        quarterly=quarterly,
        currency=str(_raw(price.get("currency")) or ""),
        provider=provider,
        quality=DataQuality.DELAYED,
    )


def _to_yahoo_symbol(symbol: str) -> str:
    clean = symbol.upper().replace("/", "")
    return normalize_symbol(clean)


def _statement_modules(statement_type: StatementType) -> tuple[str, str]:
    modules = {
        StatementType.INCOME: ("incomeStatementHistory", "incomeStatementHistoryQuarterly"),
        StatementType.BALANCE_SHEET: ("balanceSheetHistory", "balanceSheetHistoryQuarterly"),
        StatementType.CASH_FLOW: ("cashflowStatementHistory", "cashflowStatementHistoryQuarterly"),
    }
    return modules[statement_type]


def _timeseries_fields(statement_type: StatementType) -> tuple[str, ...]:
    fields = {
        StatementType.INCOME: (
            "TotalRevenue",
            "OperatingRevenue",
            "CostOfRevenue",
            "GrossProfit",
            "OperatingExpense",
            "SellingGeneralAndAdministration",
            "ResearchAndDevelopment",
            "DepreciationAmortizationDepletionIncomeStatement",
            "OperatingIncome",
            "EBIT",
            "EBITDA",
            "NormalizedEBITDA",
            "InterestIncome",
            "InterestExpense",
            "NetInterestIncome",
            "OtherNonOperatingIncomeExpenses",
            "PretaxIncome",
            "TaxProvision",
            "NetIncomeContinuousOperations",
            "NetIncome",
            "NetIncomeIncludingNoncontrollingInterests",
            "NetIncomeFromContinuingAndDiscontinuedOperation",
            "NetIncomeCommonStockholders",
            "PreferredStockDividends",
            "BasicEPS",
            "DilutedEPS",
            "BasicAverageShares",
            "DilutedAverageShares",
        ),
        StatementType.BALANCE_SHEET: (
            "TotalAssets",
            "CurrentAssets",
            "CashCashEquivalentsAndShortTermInvestments",
            "CashAndCashEquivalents",
            "RestrictedCash",
            "OtherShortTermInvestments",
            "Receivables",
            "AccountsReceivable",
            "GrossAccountsReceivable",
            "AllowanceForDoubtfulAccountsReceivable",
            "Inventory",
            "RawMaterials",
            "WorkInProcess",
            "FinishedGoods",
            "OtherCurrentAssets",
            "TotalNonCurrentAssets",
            "NetPPE",
            "GrossPPE",
            "AccumulatedDepreciation",
            "Properties",
            "LandAndImprovements",
            "BuildingsAndImprovements",
            "MachineryFurnitureEquipment",
            "ConstructionInProgress",
            "Leases",
            "Goodwill",
            "OtherIntangibleAssets",
            "GoodwillAndOtherIntangibleAssets",
            "InvestmentsAndOtherFinancialAssets",
            "EquityMethodInvestments",
            "InvestmentProperties",
            "OtherNonCurrentAssets",
            "TotalLiabilitiesNetMinorityInterest",
            "CurrentLiabilities",
            "PayablesAndAccruedExpenses",
            "Payables",
            "AccountsPayable",
            "CurrentAccruedExpenses",
            "CurrentDebtAndCapitalLeaseObligation",
            "CurrentDebt",
            "CurrentCapitalLeaseObligation",
            "OtherCurrentBorrowings",
            "CommercialPaper",
            "CurrentDeferredRevenue",
            "OtherCurrentLiabilities",
            "TotalNonCurrentLiabilitiesNetMinorityInterest",
            "LongTermDebtAndCapitalLeaseObligation",
            "LongTermDebt",
            "LongTermCapitalLeaseObligation",
            "NonCurrentDeferredRevenue",
            "NonCurrentDeferredTaxesLiabilities",
            "OtherNonCurrentLiabilities",
            "TotalDebt",
            "TotalEquityGrossMinorityInterest",
            "MinorityInterest",
            "StockholdersEquity",
            "CommonStockEquity",
            "PreferredStockEquity",
            "CapitalStock",
            "CommonStock",
            "AdditionalPaidInCapital",
            "RetainedEarnings",
            "TreasuryStock",
            "GainsLossesNotAffectingRetainedEarnings",
            "WorkingCapital",
            "InvestedCapital",
            "TangibleBookValue",
            "NetDebt",
            "OrdinarySharesNumber",
            "ShareIssued",
            "TreasurySharesNumber",
        ),
        StatementType.CASH_FLOW: (
            "NetIncome",
            "DepreciationAndAmortization",
            "StockBasedCompensation",
            "DeferredIncomeTax",
            "OtherNonCashItems",
            "ChangeInWorkingCapital",
            "ChangeInReceivables",
            "ChangeInInventory",
            "ChangeInPayablesAndAccruedExpense",
            "OperatingCashFlow",
            "CapitalExpenditure",
            "NetPPEPurchases",
            "PurchaseOfPPE",
            "NetBusinessPurchases",
            "PurchaseOfBusiness",
            "NetInvestmentPurchases",
            "PurchaseOfInvestment",
            "SaleOfInvestment",
            "FreeCashFlow",
            "InvestingCashFlow",
            "FinancingCashFlow",
            "EndCashPosition",
            "BeginningCashPosition",
            "ChangesInCash",
            "EffectOfExchangeRates",
            "RepurchaseOfCapitalStock",
            "CashDividendsPaid",
            "IssuanceOfDebt",
            "RepaymentOfDebt",
            "IssuanceOfCapitalStock",
        ),
    }
    return fields[statement_type]


async def _fetch_statement_timeseries(
    yahoo_symbol: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Fetch a broad statement schema without exceeding practical URL limits."""
    now = int(datetime.now(timezone.utc).timestamp())
    requests = []
    batch_size = 24
    for start in range(0, len(fields), batch_size):
        batch = fields[start : start + batch_size]
        types = [
            f"{frequency}{field}"
            for frequency in ("annual", "quarterly")
            for field in batch
        ]
        query = urllib.parse.urlencode(
            {
                "symbol": yahoo_symbol,
                "type": ",".join(types),
                "period1": now - 10 * 366 * 24 * 3600,
                "period2": now + 2 * 24 * 3600,
            }
        )
        requests.append(
            _fetch_json(
                "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
                f"{urllib.parse.quote(yahoo_symbol)}?{query}",
                timeout=12,
            )
        )

    responses = await asyncio.gather(*requests, return_exceptions=True)
    result: list[dict[str, Any]] = []
    first_error: Exception | None = None
    for response in responses:
        if isinstance(response, Exception):
            first_error = first_error or response
            continue
        nodes = response.get("timeseries", {}).get("result") or []
        result.extend(node for node in nodes if isinstance(node, dict))
    if not result:
        raise ProviderError(
            f"Yahoo returned no financial statement series for {yahoo_symbol}: {first_error or 'empty response'}"
        )
    return {"timeseries": {"result": result}}


def normalize_yahoo_timeseries_statements(
    request_symbol: str,
    payload: dict[str, Any],
    price: dict[str, Any],
    statement_type: StatementType,
    provider: str = "Yahoo Finance",
) -> FinancialStatements:
    result = payload.get("timeseries", {}).get("result") or []
    annual, annual_currency = _timeseries_periods(result, "annual")
    quarterly, quarterly_currency = _timeseries_periods(result, "quarterly")
    if not annual and not quarterly:
        raise ProviderError(f"Yahoo returned no {statement_type} time series for {request_symbol}")
    return FinancialStatements(
        symbol=request_symbol.upper(),
        name=str(_raw(price.get("longName")) or _raw(price.get("shortName")) or request_symbol.upper()),
        statement_type=statement_type,
        annual=annual,
        quarterly=quarterly,
        currency=str(annual_currency or quarterly_currency or _raw(price.get("currency")) or ""),
        provider=provider,
        quality=DataQuality.DELAYED,
    )


def merge_yahoo_financial_statements(
    first: FinancialStatements,
    second: FinancialStatements,
) -> FinancialStatements:
    if first.statement_type != second.statement_type:
        raise ValueError("Cannot merge different financial statement types")
    return FinancialStatements(
        symbol=second.symbol or first.symbol,
        name=second.name if second.name and second.name != second.symbol else first.name,
        statement_type=second.statement_type,
        annual=_merge_statement_periods(first.annual, second.annual),
        quarterly=_merge_statement_periods(first.quarterly, second.quarterly),
        currency=second.currency or first.currency,
        provider=second.provider or first.provider,
        quality=second.quality,
        metric_labels={**first.metric_labels, **second.metric_labels},
        metric_order=list(dict.fromkeys((*first.metric_order, *second.metric_order))),
        metric_sections={**first.metric_sections, **second.metric_sections},
        source_url=second.source_url or first.source_url,
        timestamp=max(first.timestamp, second.timestamp),
    )


def _merge_statement_periods(
    first: list[FinancialPeriod],
    second: list[FinancialPeriod],
) -> list[FinancialPeriod]:
    periods: dict[tuple[date | None, str], FinancialPeriod] = {}
    for period in (*first, *second):
        key = (period.end_date, period.period if period.end_date is None else "")
        existing = periods.get(key)
        if existing is None:
            periods[key] = FinancialPeriod(
                period=period.period,
                end_date=period.end_date,
                values=dict(period.values),
                source_form=period.source_form,
                filed_date=period.filed_date,
                accession_number=period.accession_number,
                derived=period.derived,
            )
            continue
        # The legacy quote-summary endpoint uses a few older aliases for the
        # same rows exposed by fundamentals-timeseries. Keep legacy-only rows,
        # but avoid displaying two contradictory versions of one line item.
        for legacy_key, canonical_key in _YAHOO_LEGACY_STATEMENT_ALIASES.items():
            if canonical_key in period.values:
                existing.values.pop(legacy_key, None)
        existing.values.update(period.values)
        existing.source_form = period.source_form or existing.source_form
        existing.filed_date = period.filed_date or existing.filed_date
        existing.accession_number = period.accession_number or existing.accession_number
        existing.derived = existing.derived or period.derived
    return sorted(
        periods.values(),
        key=lambda period: period.end_date or date.min,
        reverse=True,
    )


_YAHOO_LEGACY_STATEMENT_ALIASES = {
    "totalOperatingExpenses": "operatingExpense",
    "sellingGeneralAdministrative": "sellingGeneralAndAdministration",
    "totalOtherIncomeExpenseNet": "otherNonOperatingIncomeExpenses",
    "incomeBeforeTax": "pretaxIncome",
    "incomeTaxExpense": "taxProvision",
    "netIncomeApplicableToCommonShares": "netIncomeCommonStockholders",
    "totalCashFromOperatingActivities": "operatingCashFlow",
    "totalCashflowsFromInvestingActivities": "investingCashFlow",
    "totalCashFromFinancingActivities": "financingCashFlow",
    "capitalExpenditures": "capitalExpenditure",
    "dividendsPaid": "cashDividendsPaid",
    "repurchaseOfStock": "repurchaseOfCapitalStock",
}


def _timeseries_periods(
    result: list[dict[str, Any]],
    frequency: str,
) -> tuple[list[FinancialPeriod], str]:
    by_date: dict[date, dict[str, float | None]] = {}
    currency = ""
    for node in result:
        raw_types = node.get("meta", {}).get("type") or []
        series_type = str(raw_types[0]) if raw_types else ""
        if not series_type.startswith(frequency):
            continue
        metric_name = series_type[len(frequency) :]
        if not metric_name:
            continue
        key = metric_name.lower() if metric_name in {"EBIT", "EBITDA"} else metric_name[0].lower() + metric_name[1:]
        for observation in node.get(series_type, []):
            end_date = _date_from_value(observation.get("asOfDate"))
            value = _number(observation.get("reportedValue"))
            if end_date is None or value is None:
                continue
            by_date.setdefault(end_date, {})[key] = value
            currency = currency or str(observation.get("currencyCode") or "")
    periods = []
    for end_date in sorted(by_date, reverse=True):
        label = str(end_date.year)
        if frequency == "quarterly":
            label = f"Q{(end_date.month - 1) // 3 + 1} {end_date.year}"
        periods.append(FinancialPeriod(label, end_date, by_date[end_date]))
    return periods, currency


def _normalize_statement_periods(records: list[dict[str, Any]], quarterly: bool) -> list[FinancialPeriod]:
    periods: list[FinancialPeriod] = []
    for record in records:
        end_date = _statement_date(record.get("endDate"))
        values: dict[str, float | None] = {}
        for key, node in record.items():
            if key in {"maxAge", "endDate"}:
                continue
            value = _raw(node)
            if isinstance(value, (int, float)):
                values[key] = float(value)
        if not values:
            continue
        label = ""
        if end_date is not None:
            if quarterly:
                quarter = (end_date.month - 1) // 3 + 1
                label = f"Q{quarter} {end_date.year}"
            else:
                label = str(end_date.year)
        periods.append(FinancialPeriod(period=label or "--", end_date=end_date, values=values))
    return periods


def _statement_records(module: Any) -> list[dict[str, Any]]:
    if not isinstance(module, dict):
        return []
    preferred = ("incomeStatementHistory", "balanceSheetStatements", "cashflowStatements")
    for key in preferred:
        records = module.get(key)
        if isinstance(records, list):
            return records
    return next((value for value in module.values() if isinstance(value, list)), [])


def _latest_statement_values(module: Any) -> dict[str, float | None]:
    periods = _normalize_statement_periods(_statement_records(module), quarterly=False)
    return periods[0].values if periods else {}


def _value_from_names(values: dict[str, float | None], *names: str) -> float | None:
    return next((values.get(name) for name in names if values.get(name) is not None), None)


def _statement_date(node: Any) -> date | None:
    raw = _raw(node)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, timezone.utc).date()
    formatted = node.get("fmt") if isinstance(node, dict) else None
    if isinstance(formatted, str):
        try:
            return date.fromisoformat(formatted)
        except ValueError:
            return None
    return None


_COOKIE_JAR = http.cookiejar.CookieJar()
_YAHOO_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIE_JAR))
_YAHOO_LOCK = threading.RLock()
_YAHOO_CRUMB: str | None = None
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AJAX-Financial-Terminal/0.1"


async def _fetch_json(url: str, timeout: int = 8, authenticated: bool = False) -> dict[str, Any]:
    safe_url = require_https_url(url, allowed_hosts=("finance.yahoo.com", "yahoo.com"))

    def _read() -> dict[str, Any]:
        if authenticated:
            return _authenticated_json(safe_url, timeout)
        request = urllib.request.Request(safe_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))

    try:
        return await asyncio.to_thread(_read)
    except Exception as exc:  # pragma: no cover - depends on network availability
        raise ProviderError(str(exc)) from exc


async def _post_json(url: str, payload: dict[str, Any], timeout: int = 8) -> dict[str, Any]:
    safe_url = require_https_url(url, allowed_hosts=("finance.yahoo.com", "yahoo.com"))

    def _read() -> dict[str, Any]:
        return _authenticated_json(safe_url, timeout, payload)

    try:
        return await asyncio.to_thread(_read)
    except Exception as exc:  # pragma: no cover - depends on network availability
        raise ProviderError(str(exc)) from exc


def _authenticated_json(url: str, timeout: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    global _YAHOO_CRUMB
    with _YAHOO_LOCK:
        for attempt in range(2):
            if not _YAHOO_CRUMB:
                _refresh_yahoo_session(timeout)
            separator = "&" if "?" in url else "?"
            authenticated_url = f"{url}{separator}crumb={urllib.parse.quote(_YAHOO_CRUMB or '')}"
            headers = {"User-Agent": _USER_AGENT}
            data = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request = urllib.request.Request(authenticated_url, data=data, headers=headers)
            try:
                with _YAHOO_OPENER.open(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in {401, 403} or attempt:
                    raise
                _YAHOO_CRUMB = None
        raise ProviderError("Unable to establish an authenticated Yahoo session")


def _refresh_yahoo_session(timeout: int) -> None:
    global _YAHOO_CRUMB
    cookie_request = urllib.request.Request("https://fc.yahoo.com", headers={"User-Agent": _USER_AGENT})
    try:
        _YAHOO_OPENER.open(cookie_request, timeout=timeout).close()
    except urllib.error.HTTPError:
        pass
    crumb_request = urllib.request.Request(
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
        headers={"User-Agent": _USER_AGENT},
    )
    with _YAHOO_OPENER.open(crumb_request, timeout=timeout) as response:
        crumb = response.read().decode("utf-8").strip()
    if not crumb or crumb.startswith("{"):
        raise ProviderError("Yahoo session crumb unavailable")
    _YAHOO_CRUMB = crumb


def _raw(node: Any) -> float | str | None:
    if isinstance(node, dict):
        value = node.get("raw")
        return value if isinstance(value, (int, float, str)) else None
    return node if isinstance(node, (int, float, str)) else None


_BUSINESS_STOPWORDS = {
    "company", "corporation", "group", "holdings", "industry", "industries", "international",
    "limited", "products", "services", "provides", "engages", "operates", "through", "offers",
    "across", "based", "including", "primarily", "business", "markets", "public", "stock",
}


def _peer_candidate_score(
    target_text: str,
    target_currency: str,
    target_market_cap: float | None,
    candidate: dict[str, Any],
    *,
    recommended: bool,
) -> float:
    name = str(candidate.get("longName") or candidate.get("shortName") or "")
    target_tokens = _business_tokens(target_text)
    candidate_tokens = _business_tokens(name)
    score = 100.0 + min(len(target_tokens & candidate_tokens), 4) * 18.0
    candidate_currency = str(candidate.get("currency") or "")
    if target_currency and candidate_currency == target_currency:
        score += 16.0
        candidate_market_cap = _number(candidate.get("marketCap"))
        if target_market_cap and candidate_market_cap and target_market_cap > 0 and candidate_market_cap > 0:
            distance = abs(math.log(candidate_market_cap / target_market_cap))
            score += max(0.0, 24.0 - distance * 7.0)
    if recommended:
        score += 8.0
    exchange = str(candidate.get("exchange") or "").upper()
    candidate_symbol = str(candidate.get("symbol") or "").upper()
    if exchange in {"FRA", "GER", "DUS", "STU", "IOB", "CXE"} or candidate_symbol.endswith((".F", ".DE", ".DU", ".IL", ".XC")):
        score -= 12.0
    return score


def _business_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 4 and token not in _BUSINESS_STOPWORDS
    }


def _peer_name_key(value: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in {"sa", "plc", "inc", "corp", "corporation", "ag", "nv", "ltd", "ordinary", "shares"}
    ]
    return " ".join(tokens[:5]) or value.casefold()


def _peer_search_terms(company_name: str) -> tuple[str, ...]:
    legal = {
        "company", "corporation", "inc", "incorporated", "group", "holdings", "holding", "limited",
        "plc", "ordinary", "shares", "class", "industry", "industries", "international",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", company_name.casefold())
        if len(token) >= 4 and token not in legal
    ]
    return tuple(dict.fromkeys(tokens[-2:]))


def _peer_regions(country: str) -> tuple[str, ...]:
    country_key = country.casefold().strip()
    groups = (
        (
            {"greece", "france", "germany", "switzerland", "ireland", "netherlands", "italy", "united kingdom", "spain", "belgium", "austria", "denmark", "sweden", "norway", "finland", "portugal"},
            ("gr", "fr", "de", "ch", "ie", "nl", "it", "gb", "es", "be", "at", "dk", "se", "no", "fi", "pt"),
        ),
        ({"united states", "canada"}, ("us", "ca")),
        (
            {"japan", "china", "hong kong", "south korea", "singapore", "taiwan", "india", "indonesia", "thailand", "vietnam", "malaysia"},
            ("jp", "cn", "hk", "kr", "sg", "tw", "in", "id", "th", "vn", "my"),
        ),
        ({"australia", "new zealand"}, ("au", "nz")),
    )
    for countries, regions in groups:
        if country_key in countries:
            return regions
    return ()


def _as_percent(node: Any) -> float | None:
    value = _raw(node)
    return float(value) * 100.0 if isinstance(value, (int, float)) else None


def _net_debt(financial: dict[str, Any]) -> float | None:
    debt = _raw(financial.get("totalDebt"))
    cash = _raw(financial.get("totalCash"))
    if isinstance(debt, (int, float)) and isinstance(cash, (int, float)):
        return float(debt) - float(cash)
    return None


def _at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _last_value(values: list[Any]) -> Any:
    return next((value for value in reversed(values) if value is not None), None)


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _number(value: Any) -> float | None:
    raw = _raw(value)
    return float(raw) if isinstance(raw, (int, float)) else None


def _int_or_none(value: Any) -> int | None:
    raw = _raw(value)
    return int(raw) if isinstance(raw, (int, float)) else None


def _percent(value: Any) -> float | None:
    number = _number(value)
    return number * 100.0 if number is not None else None


def _revision(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return (current / previous - 1.0) * 100.0


def _datetime_from_value(value: Any) -> datetime | None:
    raw = _raw(value)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
        except ValueError:
            return None
    return None


def _date_from_value(value: Any) -> date | None:
    timestamp = _datetime_from_value(value)
    if timestamp is not None:
        return timestamp.date()
    raw = _raw(value)
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _normalize_screener_result(node: dict[str, Any], provider: str) -> ScreenerResult:
    price = _number(node.get("regularMarketPrice"))
    eps = _number(node.get("epsTrailingTwelveMonths"))
    pe = price / eps if price is not None and eps not in {None, 0} and eps > 0 else None
    return ScreenerResult(
        symbol=str(node.get("symbol") or "").upper(),
        name=str(node.get("longName") or node.get("shortName") or node.get("symbol") or ""),
        country=str(node.get("region") or ""),
        price=price,
        change_percent=_number(node.get("regularMarketChangePercent")),
        market_cap=_number(node.get("marketCap")),
        pe=pe,
        forward_pe=_number(node.get("forwardPE")),
        dividend_yield=(_number(node.get("trailingAnnualDividendYield")) or 0.0) * 100.0,
        volume=_number(node.get("regularMarketVolume")),
        provider=provider,
        quality=DataQuality.DELAYED,
    )


def _matches_filter(result: ScreenerResult, item_filter: ScreenerFilter) -> bool:
    fields: dict[str, Any] = {
        "COUNTRY": result.country,
        "SECTOR": result.sector,
        "PRICE": result.price,
        "CHANGE": result.change_percent,
        "MARKETCAP": result.market_cap,
        "PE": result.pe,
        "FORWARDPE": result.forward_pe,
        "DIVYIELD": result.dividend_yield,
        "ROE": result.roe,
        "ROIC": result.roic,
        "REVENUEGROWTH": result.revenue_growth,
        "MARGIN": result.operating_margin,
        "VOLUME": result.volume,
    }
    actual = fields.get(item_filter.field)
    expected = item_filter.value
    if actual is None:
        return False
    if item_filter.operator == "=":
        if item_filter.field == "COUNTRY":
            countries = {"US": "UNITED STATES", "UK": "UNITED KINGDOM", "DE": "GERMANY", "ES": "SPAIN", "FR": "FRANCE", "IT": "ITALY", "JP": "JAPAN"}
            actual_country = countries.get(str(actual).upper(), str(actual).upper())
            expected_country = countries.get(str(expected).upper(), str(expected).upper())
            return actual_country == expected_country
        return str(actual).upper() == str(expected).upper()
    if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return False
    return {
        ">": actual > expected,
        ">=": actual >= expected,
        "<": actual < expected,
        "<=": actual <= expected,
    }.get(item_filter.operator, False)
