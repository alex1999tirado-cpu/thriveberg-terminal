from __future__ import annotations

import asyncio

from rich.style import Style
from rich.text import Text
from textual.widgets import Input, OptionList, Static

from ajax_terminal.app import AjaxTerminalApp
from ajax_terminal.instruments import INSTRUMENT_REGISTRY, InstrumentRegistry
from ajax_terminal.models.instrument import AssetClass, Instrument
from ajax_terminal.providers.mock import MockMacroProvider, MockNewsProvider
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore
from ajax_terminal.ui.commands import CommandAction
from ajax_terminal.ui.suggestions import (
    command_suggestions,
    security_search_context,
    security_suggestions,
)


def test_predictor_combines_commands_registry_and_dynamic_equities() -> None:
    fx = command_suggestions("fx eur", INSTRUMENT_REGISTRY)
    command = command_suggestions("cur", INSTRUMENT_REGISTRY)
    dynamic = command_suggestions("eq aapl", INSTRUMENT_REGISTRY)
    ticker = command_suggestions("aapl", INSTRUMENT_REGISTRY)

    assert fx[0].command == "FX EURUSD"
    assert any(item.command == "CURVE EUR" for item in command)
    assert dynamic[0].command == "EQ AAPL"
    assert dynamic[0].description == "Equity overview"
    assert ticker[0].command == "DES AAPL"


def test_registry_search_accepts_company_words_and_typographical_errors() -> None:
    registry = InstrumentRegistry(
        [
            Instrument("AAPL", "Apple Inc.", AssetClass.EQUITY),
            Instrument("MSFT", "Microsoft Corporation", AssetClass.EQUITY),
            Instrument("SAN.MC", "Banco Santander, S.A.", AssetClass.EQUITY),
        ]
    )

    assert registry.search("aple")[0].symbol == "AAPL"
    assert registry.search("micro soft")[0].symbol == "MSFT"
    assert registry.search("banco santander")[0].symbol == "SAN.MC"


def test_security_results_preserve_instrument_then_function_workflow() -> None:
    results = [
        ("AAPL44", "Apple Inc. 4.450% 2044", "BOND"),
        ("AAPL", "Apple Inc.", "EQUITY"),
    ]

    plain = security_suggestions("apple", results)
    chart = security_suggestions("apple gp", results)
    function_first = security_suggestions("des apple", results)

    assert plain[0].symbol == "AAPL"
    assert plain[0].command == "AAPL"
    assert chart[0].command == "AAPL GP"
    assert function_first[0].command == "AAPL DES"
    assert security_search_context("banco santander rv") == ("BANCO SANTANDER", "RV")


def test_command_input_uppercases_and_clicks_suggestions(tmp_path) -> None:
    async def run() -> None:
        database = tmp_path / "suggestions.sqlite3"
        service = MarketService(
            cache=SQLiteCache(database),
            watchlists=WatchlistStore(database),
            market_providers=[],
        )
        app = AjaxTerminalApp(market_service=service)
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            actions = app.query_one("#topbar-actions", Static).content
            assert isinstance(actions, Text)
            click_actions = {
                span.style.meta.get("@click")
                for span in actions.spans
                if isinstance(span.style, Style) and span.style.meta and "@click" in span.style.meta
            }
            clickable_styles = [
                span.style
                for span in actions.spans
                if isinstance(span.style, Style) and span.style.meta and "@click" in span.style.meta
            ]
            assert "app.run_command('HOME')" in click_actions
            assert "app.run_command('NEWS')" in click_actions
            assert "app.focus_command" in click_actions
            assert all(style.bgcolor is None for style in clickable_styles)
            assert all(style.underline is False for style in clickable_styles)

            command = app.query_one("#command", Input)
            command.value = "fx eur"
            await pilot.pause()
            assert command.value == "FX EUR"

            menu = app.query_one("#command-suggestions", OptionList)
            assert menu.display
            assert menu.option_count > 0
            first = menu.get_option_at_index(0).prompt
            assert "FX EURUSD" in first.plain  # type: ignore[union-attr]

            await asyncio.sleep(0.1)
            assert await pilot.click("#command-suggestions", offset=(3, 1))
            await asyncio.sleep(0.2)
            assert app.current_command.action == CommandAction.FX
            assert app.current_command.target == "EURUSD"
            assert not menu.display

            assert await pilot.click("#topbar-actions", offset=(1, 0))
            await asyncio.sleep(0.1)
            assert app.current_command.action == CommandAction.HOME

            await app.action_history_back()
            await pilot.pause()
            assert app.current_command.action == CommandAction.FX
            assert app.current_command.target == "EURUSD"

            await app.action_history_forward()
            await pilot.pause()
            assert app.current_command.action == CommandAction.HOME

    asyncio.run(run())
