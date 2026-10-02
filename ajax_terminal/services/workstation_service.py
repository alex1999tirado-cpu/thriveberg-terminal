from __future__ import annotations

import asyncio
import hashlib
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ajax_terminal.models.equity import CorporateEvent
from ajax_terminal.models.instrument import AssetClass
from ajax_terminal.models.quote import DataQuality, Quote, StatementType
from ajax_terminal.services.equity_research_service import EquityResearchService
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.portfolio_risk_service import (
    PortfolioRiskPosition,
    load_portfolio_risk,
)
from ajax_terminal.analytics.portfolio_risk import PortfolioRiskReport
from ajax_terminal.storage.cache import WatchlistStore
from ajax_terminal.storage.workstation import (
    AlertRule,
    AlertStore,
    PortfolioCashFlow,
    PortfolioPosition,
    PortfolioStore,
    PortfolioTransaction,
)


EVENT_MARKET_CAP_FILTERS = (
    ("LARGEST", "LARGEST FIRST", 0.0, None),
    ("MEGA", "MEGA 200B+", 200_000_000_000.0, None),
    ("LARGE", "LARGE 10B-200B", 10_000_000_000.0, 200_000_000_000.0),
    ("MID", "MID 2B-10B", 2_000_000_000.0, 10_000_000_000.0),
    ("SMALL", "SMALL 300M-2B", 300_000_000.0, 2_000_000_000.0),
    ("MICRO", "MICRO <300M", 0.0, 300_000_000.0),
)
EVENT_INDUSTRY_FILTERS = (
    ("ALL", "ALL INDUSTRIES", ""),
    ("SEMICONDUCTORS", "SEMICONDUCTORS", "Semiconductors"),
    ("SOFTWARE_INFRASTRUCTURE", "SOFTWARE / INFRASTRUCTURE", "Software - Infrastructure"),
    ("CONSUMER_ELECTRONICS", "CONSUMER ELECTRONICS", "Consumer Electronics"),
    ("BANKS_DIVERSIFIED", "BANKS / DIVERSIFIED", "Banks - Diversified"),
    ("AUTO_MANUFACTURERS", "AUTO MANUFACTURERS", "Auto Manufacturers"),
    ("DRUG_MANUFACTURERS", "DRUG MANUFACTURERS", "Drug Manufacturers - General"),
    ("OIL_GAS_INTEGRATED", "OIL & GAS / INTEGRATED", "Oil & Gas Integrated"),
    ("TELECOM_SERVICES", "TELECOM SERVICES", "Telecom Services"),
    ("AEROSPACE_DEFENSE", "AEROSPACE & DEFENSE", "Aerospace & Defense"),
    ("REGULATED_UTILITIES", "REGULATED UTILITIES", "Utilities - Regulated Electric"),
    ("DIVERSIFIED_INSURANCE", "DIVERSIFIED INSURANCE", "Insurance - Diversified"),
    ("PACKAGED_FOODS", "PACKAGED FOODS", "Packaged Foods"),
    ("SPECIALTY_RETAIL", "SPECIALTY RETAIL", "Specialty Retail"),
)
EVENT_GEOGRAPHY_FILTERS = (
    ("US_LISTED", "US LISTED", ("NMS", "NYQ", "ASE")),
    ("WORLD", "WORLD / LOCAL CAP", ()),
    ("NORTH_AMERICA", "NORTH AMERICA", ("NMS", "NYQ", "ASE", "TOR", "VAN", "CNQ", "MEX")),
    ("EUROPE", "EUROPE", ("LSE", "GER", "FRA", "PAR", "MCE", "MIL", "AMS", "EBS", "STO", "OSL", "CPH", "HEL", "BRU", "VIE", "ISE", "LIS", "WSE")),
    ("ASIA_PACIFIC", "ASIA PACIFIC", ("JPX", "SHH", "SHZ", "HKG", "KSC", "KOE", "NSI", "BSE", "ASX", "NZE", "SES", "TAI", "TWO", "JKT", "SET", "KLS")),
    ("LATIN_AMERICA", "LATIN AMERICA", ("SAO", "BUE", "SGO", "BVC", "BVL", "MEX")),
    ("MIDDLE_EAST_AFRICA", "MIDDLE EAST / AFRICA", ("JNB", "IST", "TLV", "SAU", "DOH", "DFM", "ADS")),
)


@dataclass(frozen=True, slots=True)
class DataAuditEntry:
    field: str
    value: str
    provider: str
    quality: DataQuality
    timestamp: datetime
    unit: str = ""
    basis: str = "OBSERVED"
    source_url: str = ""
    search_key: str = ""


@dataclass(frozen=True, slots=True)
class DataAuditLoad:
    symbol: str
    entries: tuple[DataAuditEntry, ...]
    field_filter: str = ""


@dataclass(frozen=True, slots=True)
class WatchlistLoad:
    name: str
    names: tuple[str, ...]
    quotes: tuple[Quote, ...]


@dataclass(frozen=True, slots=True)
class PortfolioLine:
    position: PortfolioPosition
    quote: Quote
    market_value: float | None
    book_value: float
    profit_loss: float | None
    profit_loss_percent: float | None
    weight_percent: float | None
    fx_rate: float | None = 1.0
    native_market_value: float | None = None


@dataclass(frozen=True, slots=True)
class PortfolioAttributionLine:
    symbol: str
    market_value: float
    weight_percent: float | None
    unrealized_pnl: float
    realized_pnl: float
    income: float
    fees: float
    total_pnl: float
    contribution_bp: float | None
    cash_expenses: float = 0.0


@dataclass(frozen=True, slots=True)
class PortfolioLoad:
    name: str
    names: tuple[str, ...]
    base_currency: str
    lines: tuple[PortfolioLine, ...]
    market_value: float
    book_value: float
    profit_loss: float
    transactions: tuple[PortfolioTransaction, ...] = ()
    cash_flows: tuple[PortfolioCashFlow, ...] = ()
    attribution: tuple[PortfolioAttributionLine, ...] = ()
    cash_balance: float = 0.0
    net_asset_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    income: float = 0.0
    fees: float = 0.0
    invested_capital: float = 0.0
    total_return_percent: float | None = None
    cash_expenses: float = 0.0
    net_external_flow: float = 0.0
    risk: PortfolioRiskReport | None = None
    risk_benchmark: str = "SPY"
    risk_period: str = "1Y"


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    rule: AlertRule
    quote: Quote
    value: float | None
    triggered: bool


@dataclass(frozen=True, slots=True)
class AlertsLoad:
    evaluations: tuple[AlertEvaluation, ...]
    refreshed_at: datetime


@dataclass(frozen=True, slots=True)
class EventCalendarLoad:
    events: tuple[CorporateEvent, ...]
    symbols: tuple[str, ...]
    days: int
    universe: str = "ALL EQUITIES"
    scope: str = "ALL"
    selection: str = ""
    page: int = 1
    page_size: int = 20
    total_symbols: int = 0
    watchlists: tuple[str, ...] = ()
    portfolios: tuple[str, ...] = ()
    market_cap_filter: str = "LARGEST"
    industry_filter: str = "ALL"
    geography_filter: str = "US_LISTED"


@dataclass(frozen=True, slots=True)
class BetaRelease:
    version: int
    path: Path
    size_bytes: int
    modified_at: datetime
    sha256: str
    expected_sha256: str = ""

    @property
    def verified(self) -> bool:
        return bool(self.expected_sha256) and self.sha256.upper() == self.expected_sha256.upper()


_BETA_PATTERN = re.compile(r"THRIVEBERG_TERMINAL_BETA_(\d{3})\.EXE$", re.IGNORECASE)
_DEFAULT_EVENT_UNIVERSE = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "JPM",
)


def load_data_audit(symbol: str, field_filter: str = "") -> DataAuditLoad:
    async def load() -> DataAuditLoad:
        market = MarketService()
        quote, fundamentals, income, balance, cashflow = await asyncio.gather(
            market.quote(symbol, allow_mock=False),
            market.equity_fundamentals(symbol),
            market.financial_statements(symbol, StatementType.INCOME),
            market.financial_statements(symbol, StatementType.BALANCE_SHEET),
            market.financial_statements(symbol, StatementType.CASH_FLOW),
        )
        entries: list[DataAuditEntry] = []
        quote_units = {
            "price": quote.currency,
            "change": quote.currency,
            "change_percent": "%",
            "day_high": quote.currency,
            "day_low": quote.currency,
            "week_52_high": quote.currency,
            "week_52_low": quote.currency,
            "open_price": quote.currency,
            "previous_close": quote.currency,
            "volume": "SHARES",
            "bid": quote.currency,
            "ask": quote.currency,
        }
        excluded = {"symbol", "name", "currency", "asset_class", "provider", "quality", "timestamp", "estimated", "methodology"}
        for item in fields(quote):
            if item.name in excluded:
                continue
            value = getattr(quote, item.name)
            if value is None or value == "":
                continue
            entries.append(
                DataAuditEntry(
                    f"QUOTE.{item.name.upper()}",
                    _display_value(value),
                    quote.provider,
                    quote.quality,
                    quote.timestamp,
                    quote_units.get(item.name, ""),
                    quote.methodology or ("ESTIMATED" if quote.estimated else "OBSERVED"),
                )
            )

        fundamental_excluded = {"symbol", "name", "provider", "quality", "timestamp"}
        percentage_fields = {
            "dividend_yield", "roe", "roic", "gross_margin", "operating_margin",
            "profit_margin", "revenue_growth", "earnings_growth", "roa",
        }
        multiple_fields = {"pe", "forward_pe", "ev_ebitda", "price_book", "beta"}
        for item in fields(fundamentals):
            if item.name in fundamental_excluded:
                continue
            value = getattr(fundamentals, item.name)
            if value is None:
                continue
            unit = "%" if item.name in percentage_fields else "X" if item.name in multiple_fields else quote.currency
            entries.append(
                DataAuditEntry(
                    f"FUNDAMENTALS.{item.name.upper()}",
                    _display_value(value),
                    fundamentals.provider,
                    fundamentals.quality,
                    fundamentals.timestamp,
                    unit,
                )
            )

        statement_codes = {
            StatementType.INCOME: "IS",
            StatementType.BALANCE_SHEET: "BS",
            StatementType.CASH_FLOW: "CF",
        }
        for statement in (income, balance, cashflow):
            periods = statement.annual[:4] or statement.quarterly[:4]
            for period in periods:
                for metric, value in period.values.items():
                    if value is None:
                        continue
                    label = statement.metric_labels.get(metric, metric).upper()
                    entries.append(
                        DataAuditEntry(
                            f"{statement_codes[statement.statement_type]}.{label}.{period.period}",
                            _display_value(value),
                            statement.provider,
                            statement.quality,
                            statement.timestamp,
                            statement.currency,
                            f"{period.source_form or 'PROVIDER'} / {'DERIVED' if period.derived else 'FILED'}",
                            statement.source_url,
                            metric.upper(),
                        )
                    )
        needle = " ".join(field_filter.upper().replace("_", " ").split())
        if needle:
            terms = needle.split()
            entries = [
                entry
                for entry in entries
                if all(
                    term in f"{entry.field} {entry.search_key}".upper().replace("_", " ")
                    or term.replace(" ", "")
                    in f"{entry.field} {entry.search_key}".upper().replace("_", " ").replace(" ", "")
                    for term in terms
                )
            ]
        entries.sort(key=lambda entry: entry.field)
        return DataAuditLoad(symbol.upper(), tuple(entries), needle)

    return asyncio.run(load())


def load_watchlist(args: Iterable[str], store: WatchlistStore | None = None) -> WatchlistLoad:
    watchlists = store or WatchlistStore()
    tokens = [str(item).strip().upper() for item in args if str(item).strip()]
    name = "DEFAULT"
    if tokens:
        action = tokens[0]
        if action in {"ADD", "REMOVE"} and len(tokens) >= 2:
            name = tokens[2] if len(tokens) >= 3 else "DEFAULT"
            if action == "ADD":
                watchlists.add(tokens[1], name)
            else:
                watchlists.remove(tokens[1], name)
        elif action == "NEW" and len(tokens) >= 2:
            name = watchlists.create(" ".join(tokens[1:]))
        elif action == "DELETE" and len(tokens) >= 2:
            watchlists.delete(" ".join(tokens[1:]))
        else:
            name = " ".join(tokens)
    names = watchlists.names()
    if name not in names:
        name = watchlists.create(name)
        names = watchlists.names()

    async def load_quotes() -> tuple[Quote, ...]:
        return tuple(await MarketService(watchlists=watchlists).watchlist_quotes(name))

    return WatchlistLoad(name, tuple(names), asyncio.run(load_quotes()))


def load_portfolio(args: Iterable[str], store: PortfolioStore | None = None) -> PortfolioLoad:
    portfolios = store or PortfolioStore()
    tokens = [str(item).strip().upper() for item in args if str(item).strip()]
    risk_requested = "RISK" in tokens
    risk_benchmark = "SPY"
    risk_period = "1Y"
    if risk_requested:
        risk_index = tokens.index("RISK")
        risk_options = tokens[risk_index + 1:]
        tokens = tokens[:risk_index]
        if risk_options:
            risk_benchmark = risk_options[0]
        if len(risk_options) >= 2:
            risk_period = risk_options[1]
    name = "MAIN"
    if tokens:
        action = tokens[0]
        if action in {"BUY", "SELL"} and len(tokens) >= 4:
            portfolios.record_trade(
                tokens[1],
                action,
                float(tokens[2]),
                float(tokens[3]),
                currency=tokens[4] if len(tokens) >= 5 else "",
                fees=float(tokens[5]) if len(tokens) >= 6 else 0.0,
                trade_date=tokens[6] if len(tokens) >= 7 else None,
                name="MAIN",
            )
        elif action == "CASH" and len(tokens) >= 3:
            portfolios.record_cash_flow(
                tokens[1],
                float(tokens[2]),
                currency=tokens[3] if len(tokens) >= 4 else "",
                flow_date=tokens[4] if len(tokens) >= 5 else None,
                name="MAIN",
            )
        elif action == "ADD" and len(tokens) >= 4:
            portfolios.upsert(
                tokens[1], float(tokens[2]), float(tokens[3]),
                tokens[4] if len(tokens) >= 5 else "", "MAIN",
            )
        elif action == "REMOVE" and len(tokens) >= 2:
            portfolios.remove(tokens[1], "MAIN")
        elif action == "NEW" and len(tokens) >= 2:
            name = portfolios.create(" ".join(tokens[1:]))
        else:
            name = " ".join(tokens)
    names = portfolios.names()
    if name not in names:
        name = portfolios.create(name)
        names = portfolios.names()
    positions = portfolios.positions(name)
    base_currency = portfolios.base_currency(name)

    async def load_market() -> tuple[list[Quote], dict[str, float | None]]:
        market = MarketService()
        quotes = await market.bulk_quotes(
            [position.symbol for position in positions],
            allow_mock=False,
        )
        currencies = {
            (quote.currency or position.currency or base_currency).upper()
            for position, quote in zip(positions, quotes)
        }
        rates = {
            currency: await _portfolio_fx_rate(currency, base_currency, market)
            for currency in sorted(currencies)
        }
        return quotes, rates

    quotes, fx_rates = asyncio.run(load_market()) if positions else ([], {})
    values = [
        (
            position.quantity
            * quote.price
            * fx_rates.get((quote.currency or position.currency or base_currency).upper(), 1.0)
            if quote.price is not None
            and fx_rates.get((quote.currency or position.currency or base_currency).upper(), 1.0)
            is not None
            else None
        )
        for position, quote in zip(positions, quotes)
    ]
    total_market = sum(value for value in values if value is not None)
    lines: list[PortfolioLine] = []
    for position, quote, market_value in zip(positions, quotes, values):
        currency = (quote.currency or position.currency or base_currency).upper()
        fx_rate = fx_rates.get(currency, 1.0 if currency == base_currency else None)
        base_cost = position.cost_basis_base
        if base_cost is None and fx_rate is not None:
            base_cost = position.cost_basis * fx_rate
        book = position.quantity * base_cost if base_cost is not None else 0.0
        profit = market_value - book if market_value is not None else None
        profit_percent = profit / abs(book) * 100.0 if profit is not None and book else None
        weight = market_value / total_market * 100.0 if market_value is not None and total_market else None
        native_value = position.quantity * quote.price if quote.price is not None else None
        lines.append(
            PortfolioLine(
                position,
                quote,
                market_value,
                book,
                profit,
                profit_percent,
                weight,
                fx_rate,
                native_value,
            )
        )
    total_book = sum(line.book_value for line in lines)
    transactions = tuple(portfolios.transactions(name))
    cash_flows = tuple(portfolios.cash_flows(name))
    realized_by_symbol: dict[str, float] = defaultdict(float)
    fee_by_symbol: dict[str, float] = defaultdict(float)
    income_by_symbol: dict[str, float] = defaultdict(float)
    cash_expense_by_symbol: dict[str, float] = defaultdict(float)
    for transaction in transactions:
        realized_by_symbol[transaction.symbol] += transaction.realized_pnl
        fee_by_symbol[transaction.symbol] += transaction.fees * transaction.fx_rate
    for cash_flow in cash_flows:
        if cash_flow.kind in {"DIVIDEND", "INTEREST", "OTHER_IN"}:
            income_by_symbol[cash_flow.symbol or "CASH"] += cash_flow.amount * cash_flow.fx_rate
        elif cash_flow.kind in {"TAX", "FEE", "OTHER_OUT"}:
            symbol = cash_flow.symbol or "CASH"
            cash_expense_by_symbol[symbol] += cash_flow.amount * cash_flow.fx_rate
            if cash_flow.kind == "FEE":
                fee_by_symbol[symbol] += abs(cash_flow.amount * cash_flow.fx_rate)
    unrealized_by_symbol = {
        line.position.symbol: line.profit_loss or 0.0
        for line in lines
    }
    market_by_symbol = {
        line.position.symbol: line.market_value or 0.0
        for line in lines
    }
    weight_by_symbol = {
        line.position.symbol: line.weight_percent
        for line in lines
    }
    bought_symbols = {transaction.symbol for transaction in transactions if transaction.side == "BUY"}
    ledger_capital = portfolios.invested_capital(name)
    legacy_capital = sum(
        line.book_value for line in lines if line.position.symbol not in bought_symbols
    )
    invested_capital = ledger_capital + legacy_capital
    symbols = sorted(
        set(unrealized_by_symbol)
        | set(realized_by_symbol)
        | set(income_by_symbol)
        | set(fee_by_symbol)
        | set(cash_expense_by_symbol)
    )
    attribution: list[PortfolioAttributionLine] = []
    for symbol in symbols:
        unrealized = unrealized_by_symbol.get(symbol, 0.0)
        realized = realized_by_symbol.get(symbol, 0.0)
        income = income_by_symbol.get(symbol, 0.0)
        cash_expenses = cash_expense_by_symbol.get(symbol, 0.0)
        total = unrealized + realized + income + cash_expenses
        attribution.append(
            PortfolioAttributionLine(
                symbol,
                market_by_symbol.get(symbol, 0.0),
                weight_by_symbol.get(symbol),
                unrealized,
                realized,
                income,
                fee_by_symbol.get(symbol, 0.0),
                total,
                total / invested_capital * 10_000.0 if invested_capital else None,
                cash_expenses,
            )
        )
    unrealized_total = sum(unrealized_by_symbol.values())
    realized_total = sum(realized_by_symbol.values())
    income_total = sum(income_by_symbol.values())
    cash_expense_total = sum(cash_expense_by_symbol.values())
    total_profit = unrealized_total + realized_total + income_total + cash_expense_total
    cash_balance = portfolios.cash_balance(name)
    net_external_flow = portfolios.net_external_flow(name)
    net_asset_value = total_market + cash_balance
    risk = None
    if risk_requested:
        risk = load_portfolio_risk(
            tuple(
                PortfolioRiskPosition(
                    line.position.symbol,
                    line.market_value or 0.0,
                    (line.quote.currency or line.position.currency or base_currency).upper(),
                )
                for line in lines
            ),
            net_asset_value=net_asset_value,
            base_currency=base_currency,
            benchmark=risk_benchmark,
            period=risk_period,
        )
    return PortfolioLoad(
        name,
        tuple(names),
        base_currency,
        tuple(lines),
        total_market,
        total_book,
        total_profit,
        transactions,
        cash_flows,
        tuple(attribution),
        cash_balance,
        net_asset_value,
        realized_total,
        unrealized_total,
        income_total,
        sum(transaction.fees * transaction.fx_rate for transaction in transactions),
        invested_capital,
        total_profit / invested_capital * 100.0 if invested_capital else None,
        cash_expense_total,
        net_external_flow,
        risk,
        risk_benchmark,
        risk_period,
    )


async def _portfolio_fx_rate(
    currency: str,
    base_currency: str,
    market: MarketService,
) -> float | None:
    source = currency.strip().upper()
    target = base_currency.strip().upper()
    if not source or source == target:
        return 1.0

    async def usd_value(code: str) -> float | None:
        if code == "USD":
            return 1.0
        direct = await market.quote(f"{code}USD", allow_mock=False)
        if direct.price is not None and math.isfinite(direct.price) and direct.price > 0:
            return direct.price
        inverse = await market.quote(f"USD{code}", allow_mock=False)
        if inverse.price is not None and math.isfinite(inverse.price) and inverse.price > 0:
            return 1.0 / inverse.price
        return None

    source_usd, target_usd = await asyncio.gather(usd_value(source), usd_value(target))
    if source_usd is None or target_usd is None or target_usd == 0:
        return None
    return source_usd / target_usd


def load_alerts(args: Iterable[str], store: AlertStore | None = None) -> AlertsLoad:
    alerts = store or AlertStore()
    tokens = [str(item).strip().upper() for item in args if str(item).strip()]
    if tokens and tokens[0] == "ADD" and len(tokens) >= 5:
        alerts.add(tokens[1], tokens[2], tokens[3], float(tokens[4]))
    elif tokens and tokens[0] == "DELETE" and len(tokens) >= 2:
        alerts.delete(int(tokens[1]))
    rules = alerts.list()

    async def load_quotes() -> list[Quote]:
        symbols = list(dict.fromkeys(rule.symbol for rule in rules))
        return await MarketService().bulk_quotes(symbols, allow_mock=False)

    quotes = asyncio.run(load_quotes()) if rules else []
    by_symbol = {quote.symbol: quote for quote in quotes}
    evaluations: list[AlertEvaluation] = []
    for rule in rules:
        quote = by_symbol.get(rule.symbol) or Quote(rule.symbol, rule.symbol, None)
        value = _alert_value(quote, rule.field)
        triggered = bool(rule.enabled and value is not None and _compare(value, rule.operator, rule.threshold))
        triggered_at = datetime.now().astimezone().isoformat() if triggered else rule.last_triggered_at
        if rule.id is not None:
            alerts.record_evaluation(rule.id, value, triggered)
        evaluated_rule = AlertRule(
            rule.id,
            rule.symbol,
            rule.field,
            rule.operator,
            rule.threshold,
            rule.enabled,
            value,
            triggered_at,
            rule.created_at,
            datetime.now().astimezone().isoformat(),
        )
        evaluations.append(AlertEvaluation(evaluated_rule, quote, value, triggered))
    return AlertsLoad(tuple(evaluations), datetime.now().astimezone())


def load_event_calendar(
    days: int = 30,
    scope: str = "ALL",
    selection: str = "",
    page: int = 1,
    page_size: int = 20,
    market_cap_filter: str = "LARGEST",
    industry_filter: str = "ALL",
    geography_filter: str = "US_LISTED",
) -> EventCalendarLoad:
    watchlists = WatchlistStore()
    portfolios = PortfolioStore()
    market = MarketService(watchlists=watchlists)
    watchlist_names = tuple(watchlists.names())
    portfolio_names = tuple(portfolios.names())
    clean_scope = scope.strip().upper() or "ALL"
    clean_page = max(1, int(page))
    clean_page_size = max(1, min(100, int(page_size)))
    clean_days = max(1, min(365, int(days)))
    market_cap = next(
        (item for item in EVENT_MARKET_CAP_FILTERS if item[0] == market_cap_filter.upper()),
        EVENT_MARKET_CAP_FILTERS[0],
    )
    industry = next(
        (item for item in EVENT_INDUSTRY_FILTERS if item[0] == industry_filter.upper()),
        EVENT_INDUSTRY_FILTERS[0],
    )
    geography = next(
        (item for item in EVENT_GEOGRAPHY_FILTERS if item[0] == geography_filter.upper()),
        EVENT_GEOGRAPHY_FILTERS[0],
    )

    def equities(values: Iterable[str]) -> list[str]:
        unique = dict.fromkeys(value.strip().upper() for value in values if value.strip())
        return [
            symbol
            for symbol in unique
            if market.registry.resolve(symbol).asset_class == AssetClass.EQUITY
        ]

    async def all_equities(requested_page: int) -> tuple[list[str], int, int, str]:
        universe_label = f"ALL EQUITIES / {market_cap[1]} / {industry[1]} / {geography[1]}"
        offset = (requested_page - 1) * clean_page_size
        key = (
            f"research:event-universe:{clean_page_size}:{requested_page}:"
            f"{market_cap[0]}:{industry[0]}:{geography[0]}"
        )
        cached = market.cache.get_json(key)
        if isinstance(cached, dict) and isinstance(cached.get("symbols"), list):
            return (
                [str(item) for item in cached["symbols"]],
                int(cached.get("total") or 0),
                requested_page,
                universe_label,
            )
        for provider in market.market_providers:
            if not hasattr(provider, "equity_universe_page"):
                continue
            try:
                symbols, total = await provider.equity_universe_page(
                    offset,
                    clean_page_size,
                    minimum_market_cap=market_cap[2],
                    maximum_market_cap=market_cap[3],
                    industry=industry[2],
                    exchanges=geography[2],
                )
                total_pages = max(1, (total + clean_page_size - 1) // clean_page_size)
                actual_page = min(requested_page, total_pages)
                if actual_page != requested_page:
                    return await all_equities(actual_page)
                market.cache.set_json(key, {"symbols": symbols, "total": total}, 24 * 3600)
                return (
                    symbols,
                    total,
                    actual_page,
                    universe_label,
                )
            except Exception:
                continue
        stale = market.cache.get_stale_json(key)
        if isinstance(stale, dict) and isinstance(stale.get("symbols"), list):
            return (
                [str(item) for item in stale["symbols"]],
                int(stale.get("total") or 0),
                requested_page,
                universe_label + " / CACHED",
            )
        fallback = list(_DEFAULT_EVENT_UNIVERSE) if requested_page == 1 else []
        return fallback, len(fallback), 1, "MAJOR EQUITIES / PROVIDER UNAVAILABLE"

    async def load() -> tuple[tuple[CorporateEvent, ...], list[str], int, int, str, str]:
        selected = selection.strip().upper()
        if clean_scope == "WATCHLIST":
            selected = selected if selected in watchlist_names else "DEFAULT"
            all_symbols = equities(watchlists.symbols(selected))
            total = len(all_symbols)
            actual_page = min(clean_page, max(1, (total + clean_page_size - 1) // clean_page_size))
            start = (actual_page - 1) * clean_page_size
            symbols = all_symbols[start : start + clean_page_size]
            universe = f"WATCHLIST / {selected}"
        elif clean_scope == "PORTFOLIO":
            selected = selected if selected in portfolio_names else "MAIN"
            all_symbols = equities(position.symbol for position in portfolios.positions(selected))
            total = len(all_symbols)
            actual_page = min(clean_page, max(1, (total + clean_page_size - 1) // clean_page_size))
            start = (actual_page - 1) * clean_page_size
            symbols = all_symbols[start : start + clean_page_size]
            universe = f"PORTFOLIO / {selected}"
        else:
            selected = ""
            symbols, total, actual_page, universe = await all_equities(clean_page)
        events = await EquityResearchService(market).event_schedule(symbols, days=clean_days)
        return tuple(events), symbols, total, actual_page, universe, selected

    events, symbols, total, actual_page, universe, selected = asyncio.run(load())
    effective_scope = clean_scope if clean_scope in {"ALL", "WATCHLIST", "PORTFOLIO"} else "ALL"
    return EventCalendarLoad(
        events,
        tuple(symbols),
        clean_days,
        universe,
        effective_scope,
        selected,
        actual_page,
        clean_page_size,
        total,
        watchlist_names,
        portfolio_names,
        market_cap[0],
        industry[0],
        geography[0],
    )


def scan_beta_releases(release_dir: Path | None = None) -> tuple[BetaRelease, ...]:
    root = release_dir or _release_directory()
    if not root.exists():
        return ()
    releases: list[BetaRelease] = []
    for path in root.glob("THRIVEBERG_Terminal_BETA_*.exe"):
        match = _BETA_PATTERN.match(path.name)
        if match is None:
            continue
        digest = _sha256(path)
        checksum_path = path.with_suffix(".sha256")
        expected = ""
        if checksum_path.exists():
            expected = checksum_path.read_text(encoding="utf-8", errors="ignore").strip().split()[0]
        stat = path.stat()
        releases.append(
            BetaRelease(
                int(match.group(1)),
                path.resolve(),
                stat.st_size,
                datetime.fromtimestamp(stat.st_mtime).astimezone(),
                digest,
                expected,
            )
        )
    releases.sort(key=lambda item: item.version, reverse=True)
    return tuple(releases)


def _release_directory() -> Path:
    candidates = [Path.cwd() / "releases" / "BETA"]
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates.extend(
            (
                executable.parent / "releases" / "BETA",
                executable.parent.parent / "releases" / "BETA",
                executable.parent,
            )
        )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _display_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _alert_value(quote: Quote, field: str) -> float | None:
    return {
        "PRICE": quote.price,
        "CHANGE_PCT": quote.change_percent,
        "VOLUME": quote.volume,
        "BID": quote.bid,
        "ASK": quote.ask,
    }.get(field)


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    return value == threshold
