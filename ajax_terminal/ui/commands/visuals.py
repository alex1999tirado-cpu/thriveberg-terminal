from __future__ import annotations

from enum import StrEnum

from ajax_terminal.ui.commands.parser import CommandAction


class VisualFamily(StrEnum):
    MARKET_MONITOR = "market_monitor"
    SECURITY = "security"
    FIXED_INCOME = "fixed_income"
    MACRO_NEWS = "macro_news"
    COLLABORATION = "collaboration"
    FUNDAMENTALS = "fundamentals"
    PRICE_CHART = "price_chart"
    DERIVATIVES = "derivatives"
    SUPPORT = "support"


COMMAND_VISUAL_FAMILY: dict[CommandAction, VisualFamily] = {
    CommandAction.HOME: VisualFamily.MARKET_MONITOR,
    CommandAction.WEI: VisualFamily.MARKET_MONITOR,
    CommandAction.INSTRUMENTS: VisualFamily.MARKET_MONITOR,
    CommandAction.WATCH: VisualFamily.MARKET_MONITOR,
    CommandAction.PORTFOLIO: VisualFamily.MARKET_MONITOR,
    CommandAction.ALERTS: VisualFamily.MARKET_MONITOR,
    CommandAction.EQUITY: VisualFamily.SECURITY,
    CommandAction.INSTRUMENT: VisualFamily.SECURITY,
    CommandAction.INDEX: VisualFamily.SECURITY,
    CommandAction.COMMODITY: VisualFamily.SECURITY,
    CommandAction.FX: VisualFamily.FIXED_INCOME,
    CommandAction.FWD: VisualFamily.FIXED_INCOME,
    CommandAction.CURVE: VisualFamily.FIXED_INCOME,
    CommandAction.RATES: VisualFamily.FIXED_INCOME,
    CommandAction.GOVERNMENT: VisualFamily.FIXED_INCOME,
    CommandAction.CORPORATE: VisualFamily.FIXED_INCOME,
    CommandAction.BOND: VisualFamily.FIXED_INCOME,
    CommandAction.ECO: VisualFamily.MACRO_NEWS,
    CommandAction.MAP: VisualFamily.MACRO_NEWS,
    CommandAction.CAL: VisualFamily.MACRO_NEWS,
    CommandAction.NEWS: VisualFamily.MACRO_NEWS,
    CommandAction.SOCIAL: VisualFamily.COLLABORATION,
    CommandAction.INCOME_STATEMENT: VisualFamily.FUNDAMENTALS,
    CommandAction.BALANCE_SHEET: VisualFamily.FUNDAMENTALS,
    CommandAction.CASH_FLOW: VisualFamily.FUNDAMENTALS,
    CommandAction.FINANCIAL_ANALYSIS: VisualFamily.FUNDAMENTALS,
    CommandAction.RELATIVE_VALUATION: VisualFamily.FUNDAMENTALS,
    CommandAction.COMP: VisualFamily.FUNDAMENTALS,
    CommandAction.ESTIMATES: VisualFamily.FUNDAMENTALS,
    CommandAction.ANALYST: VisualFamily.FUNDAMENTALS,
    CommandAction.DIVIDENDS: VisualFamily.FUNDAMENTALS,
    CommandAction.EVENTS: VisualFamily.FUNDAMENTALS,
    CommandAction.FILINGS: VisualFamily.FUNDAMENTALS,
    CommandAction.TEN_K: VisualFamily.FUNDAMENTALS,
    CommandAction.TEN_Q: VisualFamily.FUNDAMENTALS,
    CommandAction.EXPORT: VisualFamily.FUNDAMENTALS,
    CommandAction.SCREENER: VisualFamily.FUNDAMENTALS,
    CommandAction.DATA_AUDIT: VisualFamily.FUNDAMENTALS,
    CommandAction.DATA_QUALITY: VisualFamily.SUPPORT,
    CommandAction.CHART: VisualFamily.PRICE_CHART,
    CommandAction.RISK: VisualFamily.PRICE_CHART,
    CommandAction.OPTIONS: VisualFamily.DERIVATIVES,
    CommandAction.OPTION_VALUATION: VisualFamily.DERIVATIVES,
    CommandAction.VOL: VisualFamily.DERIVATIVES,
    CommandAction.HELP: VisualFamily.SUPPORT,
    CommandAction.WORKSPACES: VisualFamily.SUPPORT,
    CommandAction.UPDATES: VisualFamily.SUPPORT,
    CommandAction.DIAGNOSTICS: VisualFamily.SUPPORT,
    CommandAction.SEARCH: VisualFamily.SUPPORT,
    CommandAction.UNKNOWN: VisualFamily.SUPPORT,
}


def visual_family_for(action: CommandAction) -> VisualFamily:
    return COMMAND_VISUAL_FAMILY[action]
