from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ajax_terminal.utils.symbols import is_fx_pair


class CommandAction(StrEnum):
    HOME = "HOME"
    WEI = "WEI"
    INSTRUMENTS = "INSTRUMENTS"
    FX = "FX"
    FWD = "FWD"
    CURVE = "CURVE"
    RATES = "RATES"
    GOVERNMENT = "GOVERNMENT"
    CORPORATE = "CORPORATE"
    BOND = "BOND"
    ECO = "ECO"
    MAP = "MAP"
    CAL = "CAL"
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"
    EQUITY = "EQUITY"
    INCOME_STATEMENT = "INCOME_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW = "CASH_FLOW"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    RELATIVE_VALUATION = "RELATIVE_VALUATION"
    ESTIMATES = "ESTIMATES"
    ANALYST = "ANALYST"
    DIVIDENDS = "DIVIDENDS"
    EVENTS = "EVENTS"
    FILINGS = "FILINGS"
    TEN_K = "TEN_K"
    TEN_Q = "TEN_Q"
    EXPORT = "EXPORT"
    SCREENER = "SCREENER"
    CHART = "CHART"
    INSTRUMENT = "INSTRUMENT"
    COMP = "COMP"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"
    OPTIONS = "OPTIONS"
    OPTION_VALUATION = "OPTION_VALUATION"
    VOL = "VOL"
    RISK = "RISK"
    WATCH = "WATCH"
    DATA_AUDIT = "DATA_AUDIT"
    WORKSPACES = "WORKSPACES"
    UPDATES = "UPDATES"
    PORTFOLIO = "PORTFOLIO"
    ALERTS = "ALERTS"
    HELP = "HELP"
    SEARCH = "SEARCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    action: CommandAction
    args: tuple[str, ...]
    raw: str

    @property
    def target(self) -> str | None:
        return self.args[0] if self.args else None


ALIASES = {
    "": CommandAction.HOME,
    "HOME": CommandAction.HOME,
    "MKT": CommandAction.HOME,
    "MARKET": CommandAction.HOME,
    "MARKETS": CommandAction.HOME,
    "MONITOR": CommandAction.HOME,
    "MAIN": CommandAction.HOME,
    "FAVE": CommandAction.HOME,
    "WEI": CommandAction.WEI,
    "MAP": CommandAction.MAP,
    "WORLD": CommandAction.MAP,
    "WORLDMAP": CommandAction.MAP,
    "ECONMAP": CommandAction.MAP,
    "GMAP": CommandAction.MAP,
    "INSTRUMENTS": CommandAction.INSTRUMENTS,
    "SECLIST": CommandAction.INSTRUMENTS,
    "FX": CommandAction.FX,
    "FXC": CommandAction.FX,
    "FWD": CommandAction.FWD,
    "FORWARD": CommandAction.FWD,
    "FORWARDS": CommandAction.FWD,
    "CURVE": CommandAction.CURVE,
    "YC": CommandAction.CURVE,
    "RATES": CommandAction.RATES,
    "GOVT": CommandAction.GOVERNMENT,
    "BTMM": CommandAction.GOVERNMENT,
    "WB": CommandAction.GOVERNMENT,
    "GOV": CommandAction.GOVERNMENT,
    "GOVIE": CommandAction.GOVERNMENT,
    "GOVIES": CommandAction.GOVERNMENT,
    "CORP": CommandAction.CORPORATE,
    "CORPORATE": CommandAction.CORPORATE,
    "CREDIT": CommandAction.CORPORATE,
    "BOND": CommandAction.BOND,
    "BONDS": CommandAction.BOND,
    "FI": CommandAction.BOND,
    "ECO": CommandAction.ECO,
    "MACRO": CommandAction.ECO,
    "CAL": CommandAction.CAL,
    "CALENDAR": CommandAction.CAL,
    "NEWS": CommandAction.NEWS,
    "N": CommandAction.NEWS,
    "CN": CommandAction.NEWS,
    "SOCIAL": CommandAction.SOCIAL,
    "CHAT": CommandAction.SOCIAL,
    "FRIENDS": CommandAction.SOCIAL,
    "EQ": CommandAction.EQUITY,
    "EQUITY": CommandAction.EQUITY,
    "STOCK": CommandAction.EQUITY,
    "IS": CommandAction.INCOME_STATEMENT,
    "BS": CommandAction.BALANCE_SHEET,
    "CF": CommandAction.CASH_FLOW,
    "FA": CommandAction.FINANCIAL_ANALYSIS,
    "FINANCIAL": CommandAction.FINANCIAL_ANALYSIS,
    "FINANCIALS": CommandAction.FINANCIAL_ANALYSIS,
    "ANALYSIS": CommandAction.FINANCIAL_ANALYSIS,
    "RV": CommandAction.RELATIVE_VALUATION,
    "RELVAL": CommandAction.RELATIVE_VALUATION,
    "RELATIVE": CommandAction.RELATIVE_VALUATION,
    "EE": CommandAction.ESTIMATES,
    "EST": CommandAction.ESTIMATES,
    "ESTIMATES": CommandAction.ESTIMATES,
    "EARNINGS": CommandAction.ESTIMATES,
    "ANR": CommandAction.ANALYST,
    "ANALYST": CommandAction.ANALYST,
    "RECOMMENDATIONS": CommandAction.ANALYST,
    "REC": CommandAction.ANALYST,
    "DVD": CommandAction.DIVIDENDS,
    "DIV": CommandAction.DIVIDENDS,
    "DIVIDEND": CommandAction.DIVIDENDS,
    "DIVIDENDS": CommandAction.DIVIDENDS,
    "EVT": CommandAction.EVENTS,
    "EVENT": CommandAction.EVENTS,
    "EVENTS": CommandAction.EVENTS,
    "FILINGS": CommandAction.FILINGS,
    "FILING": CommandAction.FILINGS,
    "SEC": CommandAction.FILINGS,
    "10K": CommandAction.TEN_K,
    "10-K": CommandAction.TEN_K,
    "10Q": CommandAction.TEN_Q,
    "10-Q": CommandAction.TEN_Q,
    "EXPORT": CommandAction.EXPORT,
    "EXCEL": CommandAction.EXPORT,
    "XLS": CommandAction.EXPORT,
    "EQS": CommandAction.SCREENER,
    "SCREENER": CommandAction.SCREENER,
    "DES": CommandAction.INSTRUMENT,
    "DESCRIPTION": CommandAction.INSTRUMENT,
    "QUOTE": CommandAction.INSTRUMENT,
    "Q": CommandAction.INSTRUMENT,
    "CHART": CommandAction.CHART,
    "GP": CommandAction.CHART,
    "HP": CommandAction.CHART,
    "GIP": CommandAction.CHART,
    "COMP": CommandAction.COMP,
    "COMPARE": CommandAction.COMP,
    "INDEX": CommandAction.INDEX,
    "CMDTY": CommandAction.COMMODITY,
    "COMMODITY": CommandAction.COMMODITY,
    "OPT": CommandAction.OPTIONS,
    "OPTION": CommandAction.OPTIONS,
    "OPTIONS": CommandAction.OPTIONS,
    "OMON": CommandAction.OPTIONS,
    "OVME": CommandAction.OPTION_VALUATION,
    "OVDV": CommandAction.VOL,
    "VOL": CommandAction.VOL,
    "VS": CommandAction.VOL,
    "VOLSURF": CommandAction.VOL,
    "VOL3D": CommandAction.VOL,
    "RISK": CommandAction.RISK,
    "WATCH": CommandAction.WATCH,
    "WL": CommandAction.WATCH,
    "WATC": CommandAction.WATCH,
    "FLDS": CommandAction.DATA_AUDIT,
    "FIELD": CommandAction.DATA_AUDIT,
    "FIELDS": CommandAction.DATA_AUDIT,
    "PROVENANCE": CommandAction.DATA_AUDIT,
    "WSP": CommandAction.WORKSPACES,
    "WORKSPACE": CommandAction.WORKSPACES,
    "WORKSPACES": CommandAction.WORKSPACES,
    "UPD": CommandAction.UPDATES,
    "UPDATE": CommandAction.UPDATES,
    "UPDATES": CommandAction.UPDATES,
    "PORT": CommandAction.PORTFOLIO,
    "PORTFOLIO": CommandAction.PORTFOLIO,
    "ALRT": CommandAction.ALERTS,
    "ALERT": CommandAction.ALERTS,
    "ALERTS": CommandAction.ALERTS,
    "HELP": CommandAction.HELP,
    "?": CommandAction.HELP,
}


SECURITY_FUNCTIONS = {
    CommandAction.EQUITY,
    CommandAction.INSTRUMENT,
    CommandAction.INDEX,
    CommandAction.COMMODITY,
    CommandAction.FX,
    CommandAction.FWD,
    CommandAction.BOND,
    CommandAction.NEWS,
    CommandAction.INCOME_STATEMENT,
    CommandAction.BALANCE_SHEET,
    CommandAction.CASH_FLOW,
    CommandAction.FINANCIAL_ANALYSIS,
    CommandAction.RELATIVE_VALUATION,
    CommandAction.ESTIMATES,
    CommandAction.ANALYST,
    CommandAction.DIVIDENDS,
    CommandAction.EVENTS,
    CommandAction.FILINGS,
    CommandAction.TEN_K,
    CommandAction.TEN_Q,
    CommandAction.EXPORT,
    CommandAction.CHART,
    CommandAction.OPTIONS,
    CommandAction.OPTION_VALUATION,
    CommandAction.VOL,
    CommandAction.COMP,
    CommandAction.RISK,
    CommandAction.DATA_AUDIT,
}

MARKET_SECTOR_WORDS = {"EQUITY", "INDEX", "CMDTY", "COMDTY", "CURNCY", "CORP", "GOVT"}
COUNTRY_RATE_TARGETS = {
    "US", "USA", "CA", "CAN", "MX", "MEX", "BR", "BRA", "GB", "GBR", "UK",
    "DE", "DEU", "FR", "FRA", "ES", "ESP", "IT", "ITA", "CH", "CHE", "SE", "SWE",
    "NO", "NOR", "PL", "POL", "JP", "JPN", "CN", "CHN", "HK", "HKG", "KR", "KOR",
    "IN", "IND", "AU", "AUS", "NZ", "NZL", "SG", "SGP", "ZA", "ZAF", "TR", "TUR",
}


def parse_command(raw: str) -> ParsedCommand:
    clean = " ".join(raw.strip().upper().split())
    if clean.startswith(">"):
        clean = clean[1:].strip()
    if ":" in clean and " " not in clean:
        prefix, value = clean.split(":", 1)
        action = ALIASES.get(prefix, CommandAction.SEARCH)
        return ParsedCommand(action=action, args=(value,), raw=raw)
    if not clean:
        return ParsedCommand(action=CommandAction.HOME, args=(), raw=raw)
    parts = tuple(clean.split())
    security_first = _security_first_command(parts)
    if security_first is not None:
        return ParsedCommand(action=security_first[0], args=security_first[1], raw=raw)
    first = parts[0]
    if is_fx_pair(first):
        return ParsedCommand(action=CommandAction.FX, args=(first,), raw=raw)
    action = ALIASES.get(first)
    if action is None:
        return ParsedCommand(action=CommandAction.SEARCH, args=parts, raw=raw)
    args = parts[1:]
    if action == CommandAction.RATES:
        if args and args[0] in COUNTRY_RATE_TARGETS:
            return ParsedCommand(action=CommandAction.GOVERNMENT, args=args, raw=raw)
        return ParsedCommand(action=CommandAction.CURVE, args=args, raw=raw)
    return ParsedCommand(action=action, args=args, raw=raw)


def _security_first_command(parts: tuple[str, ...]) -> tuple[CommandAction, tuple[str, ...]] | None:
    if len(parts) < 2 or parts[0] in ALIASES:
        return None
    function_index = 1
    if parts[1] in MARKET_SECTOR_WORDS:
        if len(parts) == 2:
            action = ALIASES.get(parts[1])
            if action in SECURITY_FUNCTIONS:
                return action, (parts[0],)
            return None
        function_index = 2
    action = ALIASES.get(parts[function_index])
    if action not in SECURITY_FUNCTIONS:
        return None
    return action, (parts[0], *parts[function_index + 1 :])
