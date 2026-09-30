from __future__ import annotations

import math

import pytest

from ajax_terminal.analytics.fundamentals import (
    cagr,
    enterprise_value,
    free_cash_flow,
    free_cash_flow_yield,
    growth,
    margin,
    net_debt,
    return_on_assets,
    return_on_equity,
    return_on_invested_capital,
    safe_divide,
)
from ajax_terminal.services.equity_research_service import parse_screener_filters
from ajax_terminal.services.equity_research_service import _curated_peer_candidates, _peer_profile_score
from ajax_terminal.models.equity import CompanyProfile
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.ui.commands import CommandAction, parse_command


def test_equity_research_command_aliases() -> None:
    aliases = {
        "FA AAPL": CommandAction.FINANCIAL_ANALYSIS,
        "FINANCIALS AAPL": CommandAction.FINANCIAL_ANALYSIS,
        "RV AAPL MSFT": CommandAction.RELATIVE_VALUATION,
        "EE NVDA": CommandAction.ESTIMATES,
        "ANR SAN.MC": CommandAction.ANALYST,
        "DVD MSFT": CommandAction.DIVIDENDS,
        "EVT": CommandAction.EVENTS,
        "EQS PE<25": CommandAction.SCREENER,
    }
    for command, expected in aliases.items():
        assert parse_command(command).action == expected


def test_screener_filter_parser_supports_scaled_numbers() -> None:
    filters = parse_screener_filters(("COUNTRY=US", "MARKETCAP>10B", "PE<25", "ROIC>=15"))

    assert filters[0].value == "US"
    assert filters[1].value == 10_000_000_000
    assert filters[2].value == 25
    assert filters[3].operator == ">="


def test_screener_filter_parser_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Unsupported filter"):
        parse_screener_filters(("MAGIC>10",))


def test_fundamental_calculations() -> None:
    assert safe_divide(10, 2) == 5
    assert safe_divide(10, 0) is None
    assert margin(25, 100) == 25
    assert growth(120, 100) == pytest.approx(20)
    assert free_cash_flow(50, -10) == 40
    assert free_cash_flow(50, 10) == 40
    assert free_cash_flow_yield(5, 100) == 5
    assert net_debt(60, 20) == 40
    assert enterprise_value(100, 60, 20) == 140
    assert return_on_equity(10, 50) == 20
    assert return_on_assets(10, 100) == 10
    assert return_on_invested_capital(20, 0.25, 30, 50, 5) == pytest.approx(20)


def test_dividend_cagr_handles_valid_and_invalid_inputs() -> None:
    assert cagr(1, 2, 5) == pytest.approx((math.pow(2, 0.2) - 1) * 100)
    assert cagr(0, 2, 5) is None
    assert cagr(1, 2, 0) is None


def test_relative_valuation_rejects_same_market_wrong_industry() -> None:
    target = CompanyProfile(
        "KRI.AT",
        "Kri-Kri Milk",
        exchange="Athens",
        sector="Consumer Defensive",
        industry="Packaged Foods",
        country="Greece",
        quality=DataQuality.DELAYED,
    )
    dairy = CompanyProfile(
        "BN.PA",
        "Danone",
        exchange="Paris",
        sector="Consumer Defensive",
        industry="Packaged Foods",
        country="France",
        quality=DataQuality.DELAYED,
    )
    oil = CompanyProfile(
        "MOH.AT",
        "Motor Oil",
        exchange="Athens",
        sector="Energy",
        industry="Oil & Gas Refining & Marketing",
        country="Greece",
        quality=DataQuality.DELAYED,
    )

    assert _peer_profile_score(target, dairy) >= 100
    assert _peer_profile_score(target, oil) == 0
    assert "BN.PA" in _curated_peer_candidates(target)
    assert "MOH.AT" not in _curated_peer_candidates(target)
