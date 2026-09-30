from __future__ import annotations

import urllib.parse
from datetime import date, datetime, timezone
from typing import Any

from ajax_terminal.models.options import OptionChain, OptionContract
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.providers.yahoo import _fetch_json
from ajax_terminal.utils.symbols import canonical_symbol, normalize_symbol


class YahooOptionsProvider:
    name = "Yahoo Finance"

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        canonical = canonical_symbol(symbol)
        yahoo_symbol = normalize_symbol(canonical)
        encoded = urllib.parse.quote(yahoo_symbol, safe="")
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{encoded}"
        if expiry is not None:
            timestamp = int(datetime(expiry.year, expiry.month, expiry.day, tzinfo=timezone.utc).timestamp())
            url = f"{url}?date={timestamp}"
        payload = await _fetch_json(url, authenticated=True)
        chain_node = payload.get("optionChain") if isinstance(payload, dict) else None
        results = chain_node.get("result") if isinstance(chain_node, dict) else None
        if not isinstance(results, list) or not results:
            error = chain_node.get("error") if isinstance(chain_node, dict) else None
            raise ProviderError(f"Yahoo options unavailable for {canonical}: {error or 'empty response'}")
        return normalize_yahoo_option_chain(canonical, results[0])


def normalize_yahoo_option_chain(symbol: str, result: dict[str, Any]) -> OptionChain:
    quote = result.get("quote") if isinstance(result.get("quote"), dict) else {}
    options = result.get("options") if isinstance(result.get("options"), list) else []
    option_set = options[0] if options and isinstance(options[0], dict) else {}
    expiration_timestamps = result.get("expirationDates") if isinstance(result.get("expirationDates"), list) else []
    expirations = sorted(
        {
            datetime.fromtimestamp(float(value), timezone.utc).date()
            for value in expiration_timestamps
            if isinstance(value, (int, float))
        }
    )
    selected_raw = option_set.get("expirationDate")
    selected_expiry = (
        datetime.fromtimestamp(float(selected_raw), timezone.utc).date()
        if isinstance(selected_raw, (int, float))
        else (expirations[0] if expirations else None)
    )
    currency = str(quote.get("currency") or "")
    calls = _contracts(option_set.get("calls"), "call", selected_expiry, currency)
    puts = _contracts(option_set.get("puts"), "put", selected_expiry, currency)
    quote_time = _datetime(quote.get("regularMarketTime")) or datetime.now(timezone.utc)
    dividend_yield = _number(quote.get("trailingAnnualDividendYield"))
    if dividend_yield is None:
        quoted_percent = _number(quote.get("dividendYield"))
        dividend_yield = quoted_percent / 100.0 if quoted_percent is not None else 0.0
    return OptionChain(
        symbol=symbol.upper(),
        name=str(quote.get("longName") or quote.get("shortName") or symbol.upper()),
        spot=_number(quote.get("regularMarketPrice")),
        currency=currency,
        expirations=expirations,
        selected_expiry=selected_expiry,
        calls=calls,
        puts=puts,
        provider="Yahoo Finance",
        quality=DataQuality.DELAYED,
        dividend_yield=max(dividend_yield or 0.0, 0.0),
        underlying_change=_number(quote.get("regularMarketChange")),
        underlying_change_percent=_number(quote.get("regularMarketChangePercent")),
        market_status=str(quote.get("marketState") or ""),
        timestamp=quote_time,
    )


def _contracts(
    raw_contracts: Any,
    option_type: str,
    fallback_expiry: date | None,
    fallback_currency: str,
) -> list[OptionContract]:
    if not isinstance(raw_contracts, list):
        return []
    contracts: list[OptionContract] = []
    for node in raw_contracts:
        if not isinstance(node, dict):
            continue
        strike = _number(node.get("strike"))
        expiry_value = node.get("expiration")
        contract_expiry = (
            datetime.fromtimestamp(float(expiry_value), timezone.utc).date()
            if isinstance(expiry_value, (int, float))
            else fallback_expiry
        )
        if strike is None or contract_expiry is None:
            continue
        contracts.append(
            OptionContract(
                contract_symbol=str(node.get("contractSymbol") or ""),
                option_type=option_type,
                strike=strike,
                expiry=contract_expiry,
                bid=_number(node.get("bid")),
                ask=_number(node.get("ask")),
                last=_number(node.get("lastPrice")),
                change=_number(node.get("change")),
                change_percent=_number(node.get("percentChange")),
                volume=_integer(node.get("volume")),
                open_interest=_integer(node.get("openInterest")),
                vendor_implied_volatility=_number(node.get("impliedVolatility")),
                in_the_money=bool(node.get("inTheMoney", False)),
                last_trade=_datetime(node.get("lastTradeDate")),
                currency=str(node.get("currency") or fallback_currency),
            )
        )
    return sorted(contracts, key=lambda item: item.strike)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _datetime(value: Any) -> datetime | None:
    number = _number(value)
    if number is None:
        return None
    return datetime.fromtimestamp(number, timezone.utc)
