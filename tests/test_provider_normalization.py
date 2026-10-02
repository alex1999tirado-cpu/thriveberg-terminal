from __future__ import annotations

import asyncio

from ajax_terminal.models.quote import DataQuality, StatementType
from ajax_terminal.providers.yahoo import (
    YahooProvider,
    normalize_yahoo_financial_statements,
    normalize_yahoo_fundamentals,
    normalize_yahoo_history,
    normalize_yahoo_quote,
)
from ajax_terminal.services.market_service import _fundamentals_from_dict
from ajax_terminal.utils.formatting import fmt_money, fmt_number


def test_yahoo_quote_normalization() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "EURUSD=X",
                        "regularMarketPrice": 1.185,
                        "chartPreviousClose": 1.18,
                        "regularMarketDayHigh": 1.19,
                        "regularMarketDayLow": 1.17,
                        "currency": "USD",
                        "regularMarketTime": 1_700_000_000,
                    },
                    "indicators": {"quote": [{"close": [1.18, 1.185]}]},
                }
            ],
            "error": None,
        }
    }

    quote = normalize_yahoo_quote("EURUSD", payload)

    assert quote.symbol == "EURUSD"
    assert quote.name == "EUR/USD"
    assert quote.price == 1.185
    assert quote.change_percent is not None
    assert quote.quality == DataQuality.DELAYED


def test_yahoo_history_normalization_skips_empty_bars() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, None, 102.0],
                                "high": [102.0, None, 104.0],
                                "low": [99.0, None, 101.0],
                                "close": [101.0, None, 103.0],
                                "volume": [1_000_000, None, 1_200_000],
                            }
                        ],
                        "adjclose": [{"adjclose": [100.5, None, 102.5]}],
                    },
                }
            ],
            "error": None,
        }
    }

    history = normalize_yahoo_history("AAPL", payload, "1Y", "1d")

    assert history.symbol == "AAPL"
    assert len(history.bars) == 2
    assert history.bars[-1].close == 103.0
    assert history.bars[-1].adjusted_close == 102.5
    assert history.bars[-1].volume == 1_200_000
    assert history.quality == DataQuality.DELAYED


def test_yahoo_corporate_actions_normalize_dividends_and_splits(monkeypatch) -> None:
    async def fetch(_url: str, **_kwargs):
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "events": {
                            "dividends": {
                                "one": {"date": 1_735_689_600, "amount": 0.25},
                            },
                            "splits": {
                                "two": {
                                    "date": 1_738_281_600,
                                    "numerator": 4.0,
                                    "denominator": 1.0,
                                    "splitRatio": "4:1",
                                }
                            },
                        },
                    }
                ],
                "error": None,
            }
        }

    monkeypatch.setattr("ajax_terminal.providers.yahoo._fetch_json", fetch)

    actions = asyncio.run(YahooProvider().corporate_actions("AAPL"))

    assert [str(item.action_type) for item in actions] == ["DIVIDEND", "SPLIT"]
    assert actions[0].amount == 0.25
    assert actions[0].currency == "USD"
    assert actions[1].split_ratio == 4.0
    assert actions[0].action_id.startswith("YAHOO:AAPL:DIVIDEND:")


def test_yahoo_financial_statement_normalization() -> None:
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "price": {"longName": "Example Corp", "currency": "USD"},
                    "incomeStatementHistory": {
                        "incomeStatementHistory": [
                            {
                                "endDate": {"raw": 1_735_603_200, "fmt": "2024-12-31"},
                                "totalRevenue": {"raw": 100_000_000},
                                "netIncome": {"raw": 20_000_000},
                            }
                        ]
                    },
                    "incomeStatementHistoryQuarterly": {
                        "incomeStatementHistory": [
                            {
                                "endDate": {"raw": 1_743_379_200, "fmt": "2025-03-31"},
                                "totalRevenue": {"raw": 27_000_000},
                                "netIncome": {"raw": 5_500_000},
                            }
                        ]
                    },
                }
            ]
        }
    }

    statements = normalize_yahoo_financial_statements("TEST", payload, StatementType.INCOME)

    assert statements.name == "Example Corp"
    assert statements.annual[0].period == "2024"
    assert statements.quarterly[0].period == "Q1 2025"
    assert statements.quarterly[0].values["netIncome"] == 5_500_000
    assert statements.quality == DataQuality.DELAYED


def test_yahoo_statement_normalization_preserves_every_provider_line_item() -> None:
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "price": {"longName": "Example Corp", "currency": "USD"},
                    "balanceSheetHistory": {
                        "balanceSheetStatements": [
                            {
                                "endDate": {"raw": 1_735_603_200, "fmt": "2024-12-31"},
                                "cash": {"raw": 10.0},
                                "customProviderAsset": {"raw": 20.0},
                                "customProviderLiability": {"raw": 5.0},
                            }
                        ]
                    },
                    "balanceSheetHistoryQuarterly": {"balanceSheetStatements": []},
                }
            ]
        }
    }

    statements = normalize_yahoo_financial_statements(
        "TEST", payload, StatementType.BALANCE_SHEET
    )

    assert statements.annual[0].values == {
        "cash": 10.0,
        "customProviderAsset": 20.0,
        "customProviderLiability": 5.0,
    }


def test_yahoo_provider_merges_legacy_and_detailed_timeseries(monkeypatch) -> None:
    provider = YahooProvider()

    async def summary(_symbol: str, *_modules: str):
        return {
            "price": {"longName": "Example Corp", "currency": "USD"},
            "incomeStatementHistory": {
                "incomeStatementHistory": [
                    {
                        "endDate": {"raw": 1_735_603_200},
                        "totalRevenue": {"raw": 100.0},
                        "totalOperatingExpenses": {"raw": 0.0},
                        "customLegacyLine": {"raw": 7.0},
                    }
                ]
            },
            "incomeStatementHistoryQuarterly": {"incomeStatementHistory": []},
        }

    async def timeseries(_symbol: str, _fields: tuple[str, ...]):
        return {
            "timeseries": {
                "result": [
                    {
                        "meta": {"type": ["annualTotalRevenue"]},
                        "annualTotalRevenue": [
                            {
                                "asOfDate": "2024-12-31",
                                "reportedValue": {"raw": 110.0},
                                "currencyCode": "USD",
                            }
                        ],
                    },
                    {
                        "meta": {"type": ["annualOperatingIncome"]},
                        "annualOperatingIncome": [
                            {
                                "asOfDate": "2024-12-31",
                                "reportedValue": {"raw": 30.0},
                                "currencyCode": "USD",
                            }
                        ],
                    },
                    {
                        "meta": {"type": ["annualOperatingExpense"]},
                        "annualOperatingExpense": [
                            {
                                "asOfDate": "2024-12-31",
                                "reportedValue": {"raw": 40.0},
                                "currencyCode": "USD",
                            }
                        ],
                    },
                ]
            }
        }

    provider._summary = summary  # type: ignore[method-assign]
    monkeypatch.setattr(
        "ajax_terminal.providers.yahoo._fetch_statement_timeseries",
        timeseries,
    )

    statements = asyncio.run(
        provider.financial_statements("TEST", StatementType.INCOME)
    )

    assert statements.annual[0].values == {
        "totalRevenue": 110.0,
        "customLegacyLine": 7.0,
        "operatingIncome": 30.0,
        "operatingExpense": 40.0,
    }


def test_yahoo_equity_universe_applies_ranking_and_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def post(_url: str, body: dict, timeout: int = 0):
        captured.update(body)
        captured["timeout"] = timeout
        return {
            "finance": {
                "result": [
                    {
                        "total": 81_105,
                        "quotes": [
                            {"symbol": "AAA", "quoteType": "EQUITY"},
                            {"symbol": "BBB", "quoteType": "EQUITY"},
                            {"symbol": "INDEX", "quoteType": "INDEX"},
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr("ajax_terminal.providers.yahoo._post_json", post)

    symbols, total = asyncio.run(
        YahooProvider().equity_universe_page(
            20,
            20,
            minimum_market_cap=10_000_000_000,
            maximum_market_cap=200_000_000_000,
            industry="Semiconductors",
            exchanges=("NMS", "NYQ"),
        )
    )

    assert symbols == ["AAA", "BBB"]
    assert total == 81_105
    assert captured["offset"] == 20
    assert captured["size"] == 20
    assert captured["sortField"] == "intradaymarketcap"
    assert captured["sortType"] == "DESC"
    query = captured["query"]
    assert isinstance(query, dict)
    assert query["operator"] == "AND"
    assert {node["operator"] for node in query["operands"]} == {"GT", "LT", "EQ", "OR"}


def test_etf_fundamentals_treat_empty_yahoo_nodes_as_unavailable() -> None:
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "price": {
                        "longName": {"raw": "T-Rex 2X Inverse Tesla Daily Target ETF"},
                        "marketCap": {},
                    },
                    "summaryDetail": {"forwardPE": {}},
                    "defaultKeyStatistics": {
                        "enterpriseValue": {},
                        "trailingEps": {},
                        "priceToBook": {},
                    },
                    "financialData": {},
                }
            ]
        }
    }

    fundamentals = normalize_yahoo_fundamentals("TSLZ", payload)

    assert fundamentals.name == "T-Rex 2X Inverse Tesla Daily Target ETF"
    assert fundamentals.market_cap is None
    assert fundamentals.enterprise_value is None
    assert fundamentals.forward_pe is None
    assert fundamentals.eps is None
    assert fundamentals.price_book is None


def test_malformed_cached_fundamentals_and_formatting_degrade_to_na() -> None:
    fundamentals = _fundamentals_from_dict(
        {
            "symbol": "TSLZ",
            "name": "Inverse Tesla ETF",
            "market_cap": {},
            "enterprise_value": [],
            "quality": "DELAYED",
        },
        cached_quality=False,
    )

    assert fundamentals.market_cap is None
    assert fundamentals.enterprise_value is None
    assert fmt_money({}) == "--"  # type: ignore[arg-type]
    assert fmt_number([]) == "--"  # type: ignore[arg-type]
