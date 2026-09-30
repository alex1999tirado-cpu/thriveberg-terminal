from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone

from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.models.macro import EconomicEvent, MacroIndicator
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import (
    Curve,
    CurvePoint,
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    PriceBar,
    PriceHistory,
    Quote,
    StatementType,
)
from ajax_terminal.utils.periods import (
    mock_point_count,
    normalize_history_interval,
    normalize_history_period,
)
from ajax_terminal.utils.symbols import is_fx_pair


class MockMarketProvider:
    name = "THRIVEBERG Mock Market Data"

    async def quote(self, symbol: str) -> Quote:
        clean = symbol.upper().replace("/", "")
        instrument = INSTRUMENT_REGISTRY.resolve(clean)
        base = _deterministic(clean, 50, 500)
        if is_fx_pair(clean):
            base = _deterministic(clean, 0.75, 1.55)
            if clean.endswith("JPY"):
                base = _deterministic(clean, 105, 165)
        if instrument.asset_class == AssetClass.RATE:
            base = _deterministic(clean, 1.8, 5.2)
        change_pct = _deterministic(clean + "chg", -0.75, 0.75)
        return Quote(
            symbol=clean,
            name=instrument.name,
            price=base,
            change=base * change_pct / 100.0,
            change_percent=change_pct,
            currency=instrument.currency or (clean[3:] if is_fx_pair(clean) else "USD"),
            asset_class=str(instrument.asset_class),
            day_high=base * 1.004,
            day_low=base * 0.996,
            week_52_high=base * 1.18,
            week_52_low=base * 0.82,
            open_price=base * (1.0 - change_pct / 200.0),
            previous_close=base - base * change_pct / 100.0,
            volume=_deterministic(clean + "volume", 800_000, 80_000_000),
            market_status=INSTRUMENT_REGISTRY.market_status(clean),
            provider=self.name,
            quality=DataQuality.MOCK,
        )

    async def fundamentals(self, symbol: str) -> EquityFundamentals:
        clean = symbol.upper()
        revenue = _deterministic(clean + "rev", 45_000_000_000, 420_000_000_000)
        ebitda_margin = _deterministic(clean + "margin", 0.18, 0.42)
        return EquityFundamentals(
            symbol=clean,
            name=f"{clean} Corp. (mock fundamentals)",
            market_cap=_deterministic(clean + "mcap", 80_000_000_000, 3_000_000_000_000),
            enterprise_value=_deterministic(clean + "ev", 90_000_000_000, 3_100_000_000_000),
            pe=_deterministic(clean + "pe", 15, 38),
            forward_pe=_deterministic(clean + "fpe", 13, 32),
            ev_ebitda=_deterministic(clean + "evebitda", 9, 25),
            price_book=_deterministic(clean + "pb", 2, 18),
            dividend_yield=_deterministic(clean + "dy", 0, 2.5),
            revenue=revenue,
            ebitda=revenue * ebitda_margin,
            ebit=revenue * (ebitda_margin - 0.04),
            net_income=revenue * (ebitda_margin - 0.09),
            eps=_deterministic(clean + "eps", 2, 15),
            free_cash_flow=revenue * _deterministic(clean + "fcf", 0.12, 0.29),
            roe=_deterministic(clean + "roe", 12, 55),
            roic=_deterministic(clean + "roic", 8, 38),
            net_debt=_deterministic(clean + "debt", -80_000_000_000, 120_000_000_000),
            gross_profit=revenue * _deterministic(clean + "gross", 0.3, 0.7),
            operating_cash_flow=revenue * _deterministic(clean + "ocf", 0.12, 0.34),
            gross_margin=_deterministic(clean + "gm", 28, 72),
            operating_margin=(ebitda_margin - 0.04) * 100.0,
            profit_margin=(ebitda_margin - 0.09) * 100.0,
            revenue_growth=_deterministic(clean + "growth", -4, 22),
            earnings_growth=_deterministic(clean + "egrowth", -8, 35),
            roa=_deterministic(clean + "roa", 6, 28),
            total_cash=_deterministic(clean + "cash", 8_000_000_000, 180_000_000_000),
            total_debt=_deterministic(clean + "totaldebt", 5_000_000_000, 220_000_000_000),
            beta=_deterministic(clean + "beta", 0.55, 1.85),
            shares_outstanding=_deterministic(clean + "shares", 500_000_000, 16_000_000_000),
            provider=self.name,
            quality=DataQuality.MOCK,
        )

    async def historical(self, symbol: str, period: str = "1Y", interval: str | None = None) -> PriceHistory:
        clean = symbol.upper().replace("/", "")
        normalized = normalize_history_period(period)
        selected_interval = normalize_history_interval(normalized, interval)
        count = mock_point_count(normalized, selected_interval)
        quote = await self.quote(clean)
        target = quote.price or 100.0
        seed = _deterministic(clean + normalized + selected_interval, 0.0, math.tau)
        raw_prices: list[float] = []
        value = 100.0
        for index in range(count):
            drift = _deterministic(f"{clean}:{normalized}:{index}", -0.018, 0.019)
            cycle = math.sin(index / 11.0 + seed) * 0.003
            value = max(1.0, value * (1.0 + drift + cycle))
            raw_prices.append(value)
        scale = target / raw_prices[-1]
        closes = [value * scale for value in raw_prices]
        step = _interval_delta(selected_interval)
        now = datetime.now(timezone.utc)
        bars: list[PriceBar] = []
        for index, close in enumerate(closes):
            open_price = closes[index - 1] if index else close * 0.998
            spread = _deterministic(f"{clean}:range:{index}", 0.001, 0.012)
            bars.append(
                PriceBar(
                    timestamp=now - step * (count - index - 1),
                    open=open_price,
                    high=max(open_price, close) * (1.0 + spread / 2.0),
                    low=min(open_price, close) * (1.0 - spread / 2.0),
                    close=close,
                    volume=_deterministic(f"{clean}:volume:{index}", 500_000, 90_000_000),
                )
            )
        return PriceHistory(
            symbol=clean,
            period=normalized,
            interval=selected_interval,
            bars=bars,
            currency=quote.currency,
            provider=self.name,
            quality=DataQuality.MOCK,
            timestamp=bars[-1].timestamp,
        )

    async def financial_statements(
        self,
        symbol: str,
        statement_type: StatementType,
    ) -> FinancialStatements:
        clean = symbol.upper()
        annual = [
            _mock_financial_period(clean, statement_type, date(datetime.now().year - offset - 1, 12, 31), False)
            for offset in range(4)
        ]
        quarter_ends = _recent_quarter_ends(6)
        quarterly = [
            _mock_financial_period(clean, statement_type, end_date, True)
            for end_date in quarter_ends
        ]
        return FinancialStatements(
            symbol=clean,
            name=f"{clean} Corp. (mock statements)",
            statement_type=statement_type,
            annual=annual,
            quarterly=quarterly,
            currency="USD",
            provider=self.name,
            quality=DataQuality.MOCK,
        )


class MockCurveProvider:
    name = "THRIVEBERG Mock Curves"

    async def curve(self, currency: str) -> Curve:
        ccy = currency.upper()
        if ccy == "EUR":
            base = {"1M": 2.85, "3M": 2.72, "6M": 2.55, "1Y": 2.35, "2Y": 2.21, "3Y": 2.24, "5Y": 2.37, "7Y": 2.48, "10Y": 2.61, "20Y": 2.82, "30Y": 2.91}
        else:
            base = {"1M": 4.92, "3M": 4.78, "6M": 4.52, "1Y": 4.12, "2Y": 3.82, "3Y": 3.74, "5Y": 3.86, "7Y": 4.02, "10Y": 4.18, "20Y": 4.55, "30Y": 4.42}
        return Curve(
            currency=ccy,
            name=f"{ccy} ZERO / GOVERNMENT CURVE",
            points=[
                CurvePoint(tenor=tenor, years=_tenor_years(tenor), yield_pct=value, change_bp=_deterministic(ccy + tenor, -4.0, 4.0))
                for tenor, value in base.items()
            ],
            provider=self.name,
            quality=DataQuality.MOCK,
        )


class MockMacroProvider:
    name = "THRIVEBERG Mock Macro"

    async def indicators(self, country: str) -> list[MacroIndicator]:
        c = country.upper()
        labels = [
            ("GDP", "GDP YoY", 2.4, "%"),
            ("CPI", "CPI YoY", 2.8, "%"),
            ("CORE_CPI", "Core CPI", 3.0, "%"),
            ("UNEMP", "Unemployment", 4.1, "%"),
            ("NFP", "NFP", 172, "K"),
            ("POLICY", "Policy Rate", 4.25, "%"),
            ("PMI_MFG", "PMI Manufacturing", 50.8, "idx"),
            ("PMI_SVC", "PMI Services", 52.4, "idx"),
            ("RETAIL", "Retail Sales", 0.6, "% m/m"),
        ]
        if c in {"EZ", "EUR", "EUROZONE"}:
            labels = [
                ("GDP", "GDP YoY", 1.1, "%"),
                ("CPI", "HICP YoY", 2.2, "%"),
                ("CORE_CPI", "Core HICP", 2.4, "%"),
                ("UNEMP", "Unemployment", 6.4, "%"),
                ("POLICY", "Deposit Rate", 2.0, "%"),
                ("PMI_MFG", "PMI Manufacturing", 49.8, "idx"),
                ("PMI_SVC", "PMI Services", 51.2, "idx"),
            ]
        return [
            MacroIndicator(
                code=code,
                country=c,
                name=name,
                value=value,
                unit=unit,
                period="MOCK",
                previous=value - _deterministic(code + c, -0.4, 0.4),
                provider=self.name,
                quality=DataQuality.MOCK,
            )
            for code, name, value, unit in labels
        ]

    async def calendar(self, country: str | None = None) -> list[EconomicEvent]:
        now = datetime.now(timezone.utc)
        selected = (country or "US").upper()
        events = [
            ("US", "CPI YoY", "SEP", "", "2.7%", "2.6%"),
            ("US", "Core CPI", "SEP", "", "3.0%", "3.1%"),
            ("US", "Consumer Confidence", "OCT", "", "104.0", "103.3"),
            ("EZ", "ECB President Speech", "", "", "", ""),
        ]
        return [
            EconomicEvent(
                time=now + timedelta(hours=index + 1),
                country=item_country,
                event=event,
                period=period,
                actual=actual,
                consensus=consensus,
                previous=previous,
                provider=self.name,
                quality=DataQuality.MOCK,
            )
            for index, (item_country, event, period, actual, consensus, previous) in enumerate(events)
            if selected in {"TODAY", "WEEK", "ALL"} or item_country == selected
        ]


class MockNewsProvider:
    name = "THRIVEBERG Mock News"

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        topic_text = (topic or "markets").upper()
        now = datetime.now(timezone.utc)
        headlines = [
            f"{topic_text}: live RSS/API provider not configured",
            f"{topic_text}: using mock headline to validate terminal layout",
            "Macro calendar and market context panels are ready for real feeds",
        ]
        return [
            NewsItem(
                timestamp=now - timedelta(minutes=index * 7),
                source=self.name,
                headline=headline,
                tags=[topic_text, "MOCK"],
                provider=self.name,
                quality=DataQuality.MOCK,
            )
            for index, headline in enumerate(headlines[:limit])
        ]


def _mock_financial_period(
    symbol: str,
    statement_type: StatementType,
    end_date: date,
    quarterly: bool,
) -> FinancialPeriod:
    scale = 0.24 if quarterly else 1.0
    growth = 1.0 - max(datetime.now().year - end_date.year, 0) * 0.06
    revenue = _deterministic(symbol + "statement-revenue", 40e9, 420e9) * scale * growth
    assets = _deterministic(symbol + "statement-assets", 80e9, 520e9) * growth
    operating_cash = revenue * _deterministic(symbol + "statement-ocf", 0.14, 0.32)
    if statement_type == StatementType.INCOME:
        basic_shares = _deterministic(symbol + "statement-shares", 2e9, 18e9)
        diluted_shares = basic_shares * 1.015
        values = {
            "totalRevenue": revenue,
            "costOfRevenue": revenue * 0.56,
            "grossProfit": revenue * 0.44,
            "researchDevelopment": revenue * 0.08,
            "sellingGeneralAdministrative": revenue * 0.10,
            "operatingExpenses": revenue * 0.18,
            "operatingIncome": revenue * 0.26,
            "ebit": revenue * 0.25,
            "ebitda": revenue * 0.30,
            "interestIncome": revenue * 0.006,
            "interestExpense": revenue * 0.012,
            "incomeBeforeTax": revenue * 0.23,
            "incomeTaxExpense": revenue * 0.045,
            "incomeFromContinuingOperations": revenue * 0.185,
            "netIncome": revenue * 0.185,
            "netIncomeCommonStockholders": revenue * 0.181,
            "basicEPS": revenue * 0.181 / basic_shares,
            "dilutedEPS": revenue * 0.181 / diluted_shares,
            "basicAverageShares": basic_shares,
            "dilutedAverageShares": diluted_shares,
        }
    elif statement_type == StatementType.BALANCE_SHEET:
        current_assets = assets * 0.38
        non_current_assets = assets - current_assets
        current_liabilities = assets * 0.27
        non_current_liabilities = assets * 0.37
        total_liabilities = current_liabilities + non_current_liabilities
        equity = assets - total_liabilities
        total_debt = assets * 0.23
        cash = assets * 0.13
        values = {
            "cashAndCashEquivalents": cash,
            "shortTermInvestments": assets * 0.08,
            "accountsReceivableNetCurrent": assets * 0.10,
            "inventory": assets * 0.04,
            "prepaidExpenseCurrent": assets * 0.01,
            "otherCurrentAssets": assets * 0.02,
            "currentAssets": current_assets,
            "propertyPlantEquipmentGross": assets * 0.41,
            "accumulatedDepreciation": -assets * 0.12,
            "netPPE": assets * 0.29,
            "operatingLeaseRightOfUseAsset": assets * 0.04,
            "goodwill": assets * 0.10,
            "intangibleAssetsNet": assets * 0.04,
            "longTermInvestments": assets * 0.08,
            "otherNonCurrentAssets": assets * 0.07,
            "totalNonCurrentAssets": non_current_assets,
            "totalAssets": assets,
            "accountsPayableCurrent": assets * 0.09,
            "accruedLiabilitiesCurrent": assets * 0.06,
            "currentDebt": assets * 0.04,
            "operatingLeaseLiabilityCurrent": assets * 0.02,
            "deferredRevenueCurrent": assets * 0.025,
            "otherCurrentLiabilities": assets * 0.035,
            "currentLiabilities": current_liabilities,
            "longTermDebt": assets * 0.19,
            "operatingLeaseLiabilityNonCurrent": assets * 0.04,
            "deferredTaxLiabilitiesNonCurrent": assets * 0.03,
            "deferredRevenueNonCurrent": assets * 0.02,
            "otherNonCurrentLiabilities": assets * 0.09,
            "totalNonCurrentLiabilities": non_current_liabilities,
            "totalDebt": total_debt,
            "totalLiabilities": total_liabilities,
            "commonStockValue": assets * 0.03,
            "additionalPaidInCapital": assets * 0.11,
            "retainedEarnings": assets * 0.24,
            "accumulatedOtherComprehensiveIncome": -assets * 0.01,
            "treasuryStockValue": -assets * 0.01,
            "stockholdersEquity": equity,
            "totalEquity": equity,
            "liabilitiesAndEquity": assets,
            "workingCapital": current_assets - current_liabilities,
            "netDebt": total_debt - cash,
            "ordinarySharesNumber": _deterministic(symbol + "statement-shares", 2e9, 18e9),
        }
    else:
        investing_cash = -revenue * 0.09
        financing_cash = -revenue * 0.06
        changes_in_cash = operating_cash + investing_cash + financing_cash
        values = {
            "netIncome": revenue * 0.185,
            "depreciationAndAmortization": revenue * 0.045,
            "stockBasedCompensation": revenue * 0.018,
            "deferredIncomeTax": revenue * 0.006,
            "otherNonCashItems": revenue * 0.004,
            "changeInAccountsReceivable": -revenue * 0.012,
            "changeInInventory": -revenue * 0.006,
            "changeInAccountsPayable": revenue * 0.009,
            "changeInAccruedLiabilities": revenue * 0.004,
            "operatingCashFlow": operating_cash,
            "totalCashFromOperatingActivities": operating_cash,
            "capitalExpenditures": -revenue * 0.055,
            "acquisitions": -revenue * 0.012,
            "purchasesOfInvestments": -revenue * 0.05,
            "proceedsFromInvestments": revenue * 0.027,
            "investingCashFlow": investing_cash,
            "issuanceOfDebt": revenue * 0.012,
            "repaymentOfDebt": -revenue * 0.018,
            "issuanceOfCommonStock": revenue * 0.003,
            "dividendsPaid": -revenue * 0.025,
            "repurchaseOfStock": -revenue * 0.035,
            "financingCashFlow": financing_cash,
            "effectOfExchangeRate": revenue * 0.001,
            "changesInCash": changes_in_cash,
            "endCashPosition": assets * 0.13,
            "freeCashFlow": operating_cash - revenue * 0.055,
        }
    quarter = (end_date.month - 1) // 3 + 1
    label = f"Q{quarter} {end_date.year}" if quarterly else str(end_date.year)
    return FinancialPeriod(period=label, end_date=end_date, values=values)


def _recent_quarter_ends(count: int) -> list[date]:
    today = datetime.now().date()
    current_quarter = (today.month - 1) // 3
    year = today.year
    month = current_quarter * 3
    if month == 0:
        year -= 1
        month = 12
    ends: list[date] = []
    for _ in range(count):
        day = 31 if month in {3, 12} else 30
        ends.append(date(year, month, day))
        month -= 3
        if month <= 0:
            month += 12
            year -= 1
    return ends


def _deterministic(key: str, low: float, high: float) -> float:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    integer = int(digest[:12], 16)
    ratio = integer / float(0xFFFFFFFFFFFF)
    return low + ratio * (high - low)


def _tenor_years(tenor: str) -> float:
    if tenor.endswith("M"):
        return int(tenor[:-1]) / 12
    if tenor.endswith("Y"):
        return int(tenor[:-1])
    return 0.0


def _interval_delta(interval: str) -> timedelta:
    if interval.endswith("m"):
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h"):
        return timedelta(hours=int(interval[:-1]))
    if interval.endswith("wk"):
        return timedelta(weeks=int(interval[:-2]))
    return timedelta(days=1)
