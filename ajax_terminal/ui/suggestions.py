from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from ajax_terminal.instruments import InstrumentRegistry


@dataclass(frozen=True, slots=True)
class CommandSuggestion:
    command: str
    description: str


@dataclass(frozen=True, slots=True)
class SecuritySuggestion:
    command: str
    symbol: str
    name: str
    security_type: str
    source: str = "AUTO"


COMMANDS = (
    CommandSuggestion("MARKETS", "Multi-asset market monitor"),
    CommandSuggestion("WEI", "World equity indices"),
    CommandSuggestion("FX", "G10 spot matrix"),
    CommandSuggestion("FWD EURUSD", "FX forward monitor"),
    CommandSuggestion("GOVT", "Government bond monitor"),
    CommandSuggestion("CORP", "Corporate credit monitor"),
    CommandSuggestion("CURVE USD", "US Treasury curve"),
    CommandSuggestion("CURVE EUR", "ECB euro-area zero curve"),
    CommandSuggestion("CURVE JPY", "Japan government zero curve"),
    CommandSuggestion("ECO US", "US macro monitor"),
    CommandSuggestion("MAP", "Interactive global macro map"),
    CommandSuggestion("MAP CPI", "Global inflation choropleth"),
    CommandSuggestion("MAP 10Y", "Global sovereign-yield choropleth"),
    CommandSuggestion("MAP SPAIN", "Open macro map and select a country"),
    CommandSuggestion("CAL", "Economic calendar"),
    CommandSuggestion("NEWS", "News wire"),
    CommandSuggestion("SOCIAL", "Friends, messages and shared THRIVEBERG screens"),
    CommandSuggestion("WATC", "Editable real-time watchlists"),
    CommandSuggestion("PORT", "Portfolio positions, valuation and P&L"),
    CommandSuggestion("ALRT", "Market price and volume alerts"),
    CommandSuggestion("DQM", "Provider health, cache coverage and source comparison"),
    CommandSuggestion("EQS", "Multi-factor equity screener"),
    CommandSuggestion("EVT ALL 30", "Corporate calendar for watchlists and portfolios"),
    CommandSuggestion("WSP", "Save and restore terminal workspaces"),
    CommandSuggestion("UPD", "Install or roll back local beta releases"),
    CommandSuggestion("FILINGS AAPL", "Official filings for the listing jurisdiction"),
    CommandSuggestion("10K AAPL", "Latest annual regulatory filings"),
    CommandSuggestion("10Q AAPL", "Latest SEC quarterly filings"),
    CommandSuggestion("XLS AAPL", "Export financial statements to Excel"),
    CommandSuggestion("OMON AAPL", "Listed option chain and market activity"),
    CommandSuggestion("OVME AAPL", "Black-Scholes option valuation"),
    CommandSuggestion("OVDV AAPL", "Implied-volatility smile and surface"),
    CommandSuggestion("COMP AAPL", "Comparable-company valuation"),
    CommandSuggestion("RISK AAPL", "Price and historical risk analytics"),
    CommandSuggestion("INSTRUMENTS", "Instrument registry"),
    CommandSuggestion("INSTRUMENTS FX", "Registered G10 FX crosses"),
    CommandSuggestion("INSTRUMENTS INDEX", "Registered global indices"),
    CommandSuggestion("INSTRUMENTS RATES", "Registered sovereign yields"),
    CommandSuggestion("INSTRUMENTS CMDTY", "Registered commodities"),
    CommandSuggestion("HELP", "Functions and command guide"),
)

SYMBOL_FUNCTIONS = {
    "DES": "Security description",
    "EQ": "Equity overview",
    "GP": "Price chart",
    "FA": "Financial analysis",
    "IS": "Income statement",
    "BS": "Balance sheet",
    "CF": "Cash-flow statement",
    "EE": "Earnings estimates",
    "ANR": "Analyst recommendations",
    "DVD": "Dividend analysis",
    "EVT": "Corporate events",
    "FILINGS": "Official filings for the listing jurisdiction",
    "10K": "Annual regulatory filings",
    "10Q": "SEC quarterly filings",
    "XLS": "Export financial statements to Excel",
    "EXPORT": "Export financial statements to Excel",
    "RV": "Relative valuation",
    "COMP": "Comparable-company valuation",
    "RISK": "Price and historical risk analytics",
    "NEWS": "Security news",
    "OMON": "Listed option chain",
    "OVME": "Black-Scholes option valuation",
    "OVDV": "Implied-volatility smile and surface",
    "VOL": "Implied-volatility smile and surface",
    "FLDS": "Field value, source, quality and methodology",
}


def security_search_context(query: str) -> tuple[str, str | None]:
    """Extract a fuzzy security query and an optional Bloomberg-style function."""
    clean = " ".join(query.strip().upper().split())
    if not clean:
        return "", None
    parts = clean.split()
    if len(parts) > 1 and parts[0] in SYMBOL_FUNCTIONS:
        return " ".join(parts[1:]), parts[0]
    if len(parts) > 1 and parts[-1] in SYMBOL_FUNCTIONS:
        return " ".join(parts[:-1]), parts[-1]
    if len(parts) == 1 and parts[0] in SYMBOL_FUNCTIONS:
        return "", parts[0]
    return clean, None


def security_suggestions(
    raw_query: str,
    results: Iterable[tuple[str, str, str]],
    *,
    source: str = "AUTO",
    limit: int = 8,
) -> list[SecuritySuggestion]:
    search_query, function = security_search_context(raw_query)
    if not search_query:
        return []
    ranked: list[tuple[float, int, SecuritySuggestion]] = []
    seen: set[str] = set()
    for index, (symbol, name, security_type) in enumerate(results):
        clean_symbol = symbol.strip().upper()
        if not clean_symbol or clean_symbol in seen:
            continue
        seen.add(clean_symbol)
        command = f"{clean_symbol} {function}" if function else clean_symbol
        suggestion = SecuritySuggestion(
            command=command,
            symbol=clean_symbol,
            name=name.strip() or clean_symbol,
            security_type=_display_security_type(security_type),
            source=source,
        )
        ranked.append((_security_match_score(search_query, suggestion), index, suggestion))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [suggestion for _score, _index, suggestion in ranked[:limit]]


def _display_security_type(value: str) -> str:
    clean = value.strip().upper()
    if "." in clean:
        clean = clean.rsplit(".", 1)[-1]
    return clean.replace("MUTUALFUND", "FUND") or "MARKET"


def _normalized_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[A-Z0-9]+", ascii_text.upper()))


def _security_match_score(query: str, suggestion: SecuritySuggestion) -> float:
    needle = _normalized_search_text(query)
    symbol = _normalized_search_text(suggestion.symbol)
    name = _normalized_search_text(suggestion.name)
    compact = needle.replace(" ", "")
    compact_symbol = symbol.replace(" ", "")
    compact_name = name.replace(" ", "")
    tokens = needle.split()

    if compact == compact_symbol:
        score = 1_000.0
    elif compact_symbol.startswith(compact):
        score = 930.0
    elif needle == name:
        score = 910.0
    elif all(token in f"{symbol} {name}" for token in tokens):
        score = 850.0
    elif compact in compact_name:
        score = 810.0
    else:
        score = max(
            SequenceMatcher(None, compact, compact_symbol).ratio(),
            SequenceMatcher(None, compact, compact_name).ratio(),
        ) * 650.0
    if suggestion.security_type in {"EQUITY", "ETF"}:
        score += 25.0
    return score


def command_suggestions(
    query: str,
    registry: InstrumentRegistry,
    limit: int = 7,
) -> list[CommandSuggestion]:
    clean = " ".join(query.strip().upper().split())
    if not clean:
        return []

    suggestions: list[CommandSuggestion] = []
    parts = clean.split(maxsplit=1)
    function = parts[0]
    tail = parts[1] if len(parts) > 1 else ""

    if tail and function in SYMBOL_FUNCTIONS:
        suggestions.append(CommandSuggestion(f"{function} {tail}", SYMBOL_FUNCTIONS[function]))
        suggestions.extend(
            CommandSuggestion(f"{function} {item.symbol}", item.name)
            for item in registry.search(tail, limit=limit)
        )
    elif tail and function in {"FX", "FWD"}:
        suggestions.extend(
            CommandSuggestion(f"{function} {item.symbol}", item.name)
            for item in registry.fx_pairs()
            if tail in item.symbol
        )
    else:
        suggestions.extend(
            item
            for item in COMMANDS
            if item.command.startswith(clean) or clean in item.description.upper()
        )
        exact_instrument = registry.get(clean)
        if exact_instrument is not None:
            suggestions.append(
                CommandSuggestion(
                    f"DES {exact_instrument.symbol}",
                    f"{exact_instrument.name}  [{exact_instrument.asset_class}]",
                )
            )
        elif len(parts) == 1 and clean.isalnum() and clean not in {item.command for item in COMMANDS}:
            suggestions.append(CommandSuggestion(f"DES {clean}", "Resolve ticker dynamically"))
        suggestions.extend(
            CommandSuggestion(f"DES {item.symbol}", f"{item.name}  [{item.asset_class}]")
            for item in registry.search(clean, limit=limit)
        )
        if function in SYMBOL_FUNCTIONS and not tail:
            suggestions.append(CommandSuggestion(f"{function} ", SYMBOL_FUNCTIONS[function]))

    unique: list[CommandSuggestion] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        if suggestion.command in seen:
            continue
        seen.add(suggestion.command)
        unique.append(suggestion)
        if len(unique) >= limit:
            break
    return unique
