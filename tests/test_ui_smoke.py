from __future__ import annotations

import asyncio
import io

import pytest
from rich.console import Console
from textual.widgets import DataTable, Static

from ajax_terminal.app import AjaxTerminalApp
from ajax_terminal.models.quote import DataQuality, PriceHistory, Quote
from ajax_terminal.providers.mock import MockMacroProvider, MockMarketProvider, MockNewsProvider
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.social_service import SocialService
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore
from ajax_terminal.ui.commands import CommandAction, parse_command
from ajax_terminal.ui.screens.renderers import (
    _function_command,
    _function_strip,
    _instrument_link,
    render_equity,
)
from ajax_terminal.ui.widgets.chart import EmbeddedChart
from ajax_terminal.ui.widgets.news import NewsWorkspace


@pytest.mark.parametrize(
    ("function", "context", "expected"),
    (
        ("GP", "AAPL", "GP AAPL"),
        ("CURVE", "US10Y", "CURVE USD"),
        ("GOVT", "USD", "GOVT US"),
        ("GP", "FR", "GP FR10Y"),
        ("ECO", "US", "ECO US"),
        ("ECO", "FED", "ECO"),
        ("MARKETS", "AAPL", "MARKETS"),
    ),
)
def test_function_buttons_resolve_contextual_commands(
    function: str,
    context: str,
    expected: str,
) -> None:
    assert _function_command(function, context) == expected


def test_main_screens_render_headless(tmp_path) -> None:
    pytest.importorskip("textual")

    async def run() -> None:
        database = tmp_path / "ui.sqlite3"
        service = MarketService(
            cache=SQLiteCache(database),
            watchlists=WatchlistStore(database),
            market_providers=[MockMarketProvider()],
        )
        app = AjaxTerminalApp(
            market_service=service,
            social_service=SocialService(config_path=tmp_path / "social.json"),
        )
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            strip = app.query_one("#instrument-strip")
            sidebar = app.query_one("#sidebar")
            context = app.query_one("#context", Static)
            watchlist = app.query_one("#watchlist", Static)
            main_pane = app.query_one("#main-pane")
            topbar = app.query_one("#topbar")
            assert strip.display
            assert topbar.region.height == 2
            assert "THRIVEBERG PROFESSIONAL" in str(app.query_one("#topbar-actions", Static).content)
            assert "NO INSTRUMENT" in str(app.query_one("#instrument-function", Static).content)
            assert sidebar.display
            assert sidebar.region.width == 38
            assert main_pane.region.right <= sidebar.region.x
            assert main_pane.region.width >= 110
            assert context.region.x == watchlist.region.x
            assert context.region.bottom <= watchlist.region.y
            assert watchlist.region.bottom <= sidebar.region.bottom

            home_console = Console(width=160, record=True, file=io.StringIO())
            home_console.print(app.query_one("#main", Static).content)
            home_lines = home_console.export_text().splitlines()
            for section in ("RATES", "COMMODITIES"):
                section_index = next(index for index, line in enumerate(home_lines) if section in line)
                assert not home_lines[section_index - 1].strip(" |")

            rate_quote = Quote(
                symbol="US10Y",
                name="US Treasury 10Y Yield",
                price=4.321,
                change=0.012,
                change_percent=0.28,
                currency="USD",
                asset_class="RATES",
                quality=DataQuality.CACHED,
            )
            strip.set_quote(rate_quote)
            rate_market_line = str(app.query_one("#instrument-market", Static).content)
            assert "4.321 %" in rate_market_line
            assert "4.321 USD" not in rate_market_line
            rate_screen = render_equity(
                rate_quote,
                None,
                PriceHistory("US10Y", "1Y", "1d", [], "USD", "TEST", DataQuality.CACHED),
                [],
            )
            console = Console(width=160, record=True, file=io.StringIO())
            console.print(rate_screen)
            rate_screen_text = console.export_text()
            assert "4.321 %" in rate_screen_text
            assert "4.321 USD" not in rate_screen_text
            snapshot_line = next(
                line for line in rate_screen_text.splitlines() if "LAST" in line and "CHANGE" in line
            )
            last_value_end = snapshot_line.index("4.321 %") + len("4.321 %")
            separator_index = snapshot_line.index("|", last_value_end)
            change_index = snapshot_line.index("CHANGE")
            assert separator_index - last_value_end <= 3
            assert change_index - separator_index <= 4

            assert "PERIOD SUMMARY" in rate_screen_text
            summary_header = next(
                line for line in rate_screen_text.splitlines() if "RANGE" in line and "NET CHG" in line
            )
            assert all(label in summary_header for label in ("% CHG", "HIGH", "LOW", "AVG PX", "LAST VOL"))

            ohlc_header = next(
                line for line in rate_screen_text.splitlines() if "DATE" in line and "OPEN" in line and "CLOSE" in line
            )
            assert all(label in ohlc_header for label in ("HIGH", "LOW", "NET CHG", "% CHG", "VOLUME"))
            assert ohlc_header.index("OPEN") - ohlc_header.index("DATE") <= 24
            assert ohlc_header.index("NET CHG") - ohlc_header.index("CLOSE") <= 15

            horizon_header = next(
                line for line in rate_screen_text.splitlines() if "HORIZON" in line and "1W" in line
            )
            assert all(label in horizon_header for label in ("1M", "3M", "6M", "1Y"))

            risk_line = next(
                line for line in rate_screen_text.splitlines() if "ANN. VOL" in line and "EXP. SHORTFALL" in line
            )
            risk_value_end = risk_line.index("--", risk_line.index("ANN. VOL")) + len("--")
            risk_separator_index = risk_line.index("|", risk_value_end)
            atr_index = risk_line.index("EXP. SHORTFALL")
            assert risk_separator_index - risk_value_end <= 3
            assert atr_index - risk_separator_index <= 4
            checks = [
                ("HOME", "MARKET MONITOR"),
                ("FX EURUSD", "SPOT MARKET"),
                ("FWD EURUSD 3M", "FORWARD MONITOR / 3M"),
                ("CURVE USD", "NO LIVE CURVE DATA"),
                ("GOVT", "GOVERNMENT BONDS / GLOBAL 10Y"),
                ("GOVT US", "GOVERNMENT BONDS / US"),
                ("CORP", "CORPORATE BONDS / US CREDIT"),
                ("CORP AAPL", "AAPL44"),
                ("BOND AAPL44", "TRACE FEED NOT CONFIGURED"),
                ("BOND AAPL44 PRICE 92.50", "YIELD / RISK ANALYTICS"),
                ("BOND 4.25 2034-05-15 98.50", "GENERIC-4.25-2034"),
                ("ECO US", "MACRO MONITOR"),
                ("NEWS FED", "NEWS FED"),
                ("EQ AAPL 3M", "PRICE HISTORY [3M]"),
                ("INDEX SPX 1Y", "PRICE HISTORY [1Y]"),
                ("WEI", "WORLD EQUITY INDICES"),
                ("INSTRUMENTS FX", "45 registered instruments"),
                ("FX", "G10 FX MATRIX"),
                ("FX EURJPY", "EUR/JPY"),
                ("IS AAPL", "ANNUAL HISTORY"),
                ("BS MSFT", "BALANCE SHEET"),
                ("CF SAN.MC", "CASH FLOW STATEMENT"),
                ("FA AAPL", "No mock values are shown"),
                ("EE AAPL", "No mock values are shown"),
                ("ANR AAPL", "No mock values are shown"),
                ("DVD AAPL", "No mock values are shown"),
                ("RV AAPL", "No mock values are shown"),
                ("EVT AAPL", "NO EVENTS"),
                ("EQS PE<25", "Screener provider unavailable"),
            ]
            for command, marker in checks:
                await app.execute_command(parse_command(command))
                await pilot.pause()
                renderable = app.query_one("#main", Static).content
                console = Console(width=160, record=True, file=io.StringIO())
                console.print(renderable)
                assert marker in console.export_text()
            await app.execute_command(parse_command("CHART AAPL 5D 15M"))
            await pilot.pause()
            chart = app.query_one("#chart-screen", EmbeddedChart)
            assert chart.display
            assert not app.query_one("#main-scroll").display
            assert chart.symbol == "AAPL"
            assert chart.period == "5D"
            assert chart.interval == "15m"
            assert chart.history is not None
            assert app.query_one("#chart-image").image is not None
            assert app.query_one("#chart-range-row").size.height == 1
            assert app.query_one("#chart-tools-row").size.height == 1
            assert len(chart.query("#chart-header")) == 0
            assert app.query_one("#chart-analytics").size.height == 4
            assert app.query_one("#chart-footer").size.height == 2
            assert app.query_one("#chart-controls").region.bottom == app.query_one("#chart-image").region.y
            assert app.query_one("#chart-image").region.bottom == app.query_one("#chart-analytics").region.y
            for row_id in ("#chart-range-row", "#chart-tools-row"):
                row = app.query_one(row_id)
                assert all(child.region.right <= row.region.right for child in row.children if child.display)
            assert "QUICK ANALYTICS / EQUITY" in str(app.query_one("#chart-analytics-title", Static).content)
            context_console = Console(width=42, record=True, file=io.StringIO())
            context_console.print(app.query_one("#context", Static).content)
            context_text = context_console.export_text()
            assert "GP CONTEXT / AAPL" in context_text
            assert "QUICK STATS" in context_text
            assert "EVENTS / UPCOMING" in context_text
            assert app.query_one("#instrument-strip").display
            assert "AAPL Equity" in str(app.query_one("#instrument-function", Static).content)
            assert "PRICE CHART" in str(app.query_one("#instrument-function", Static).content)
            assert "5D / 15M" in str(app.query_one("#instrument-function", Static).content)
            market_line = str(app.query_one("#instrument-market", Static).content)
            assert "AAPL" in market_line
            assert "--" in market_line

            await pilot.press("l")
            assert chart.chart_type == "line"
            await pilot.press("v")
            assert not chart.show_volume
            await pilot.press("w")
            assert chart.show_vwap
            chart.drawings.append(("HLINE", 0.1, 0.5, 0.9, 0.5))
            await pilot.press("x")
            assert not chart.drawings
            await pilot.press("0")
            assert chart.chart_type == "candle"
            assert chart.show_volume and chart.show_sma and chart.show_ema
            assert not chart.show_vwap
            await pilot.press("7")
            await pilot.pause()
            assert chart.period == "1Y"
            assert chart.interval == "1d"
            await pilot.press("r")
            await pilot.pause()
            assert chart.display and app.query_one("#chart-image").image is not None
            await pilot.press("n")
            await pilot.pause()
            assert not chart.display
            assert not app.query_one("#main-scroll").display
            news_screen = app.query_one("#news-screen", NewsWorkspace)
            assert news_screen.display
            assert len(news_screen.items) == 3
            assert app.query_one("#news-table", DataTable).row_count == 3
            assert "NEWS | AAPL" in str(app.query_one("#news-wire", Static).content)
            assert len(news_screen.query("#news-header")) == 0
            assert len(news_screen.query("#news-footer")) == 0
            assert app.query_one("#news-detail", Static).display
            topic_row = app.query_one("#news-topic-row")
            assert all(child.region.right <= topic_row.region.right for child in topic_row.children if child.display)

            await app.execute_command(parse_command("FA AAPL"))
            assert app.query_one("#instrument-strip").display
            assert "AAPL Equity" in str(app.query_one("#instrument-function", Static).content)
            assert "FINANCIAL ANALYSIS" in str(app.query_one("#instrument-function", Static).content)

            await app.execute_command(parse_command("FX EURJPY"))
            assert app.query_one("#instrument-strip").display
            assert "EURJPY Curncy" in str(app.query_one("#instrument-function", Static).content)
            assert "SPOT MARKET" in str(app.query_one("#instrument-function", Static).content)
            spot_console = Console(width=160, record=True, file=io.StringIO())
            spot_console.print(app.query_one("#main", Static).content)
            spot_text = spot_console.export_text()
            assert "PRICE HISTORY" in spot_text
            assert "FORWARD OUTRIGHTS / CARRY LADDER" not in spot_text

            await app.execute_command(parse_command("FWD EURJPY 3M"))
            assert "EURJPY Curncy" in str(app.query_one("#instrument-function", Static).content)
            assert "FORWARD MONITOR" in str(app.query_one("#instrument-function", Static).content)
            forward_console = Console(width=160, record=True, file=io.StringIO())
            forward_console.print(app.query_one("#main", Static).content)
            forward_text = forward_console.export_text()
            assert "FORWARD OUTRIGHTS / CARRY LADDER" in forward_text
            assert "PRICE HISTORY" not in forward_text
            assert "PIPS" in forward_text
            assert "FORWARD DATA UNAVAILABLE" in forward_text

            await app.execute_command(parse_command("HOME"))
            assert app.query_one("#instrument-strip").display
            assert "NO INSTRUMENT" in str(app.query_one("#instrument-function", Static).content)
            assert "--" in str(app.query_one("#instrument-market", Static).content)

            function_strip = _function_strip(("MARKETS", "WEI", "FXC"), "MARKETS")
            app.query_one("#main", Static).update(function_strip)
            await pilot.pause()
            assert await pilot.click("#main", offset=(17, 0))
            await pilot.pause()
            assert app.current_command.action == CommandAction.WEI
            function_console = Console(width=160, record=True, file=io.StringIO())
            function_console.print(app.query_one("#main", Static).content)
            assert "WORLD EQUITY INDICES" in function_console.export_text()

            instrument_link = _instrument_link("msft")
            assert instrument_link.plain == "MSFT"
            assert instrument_link.style.meta["@click"] == "app.open_instrument('MSFT')"
            assert instrument_link.style.underline is False
            app.query_one("#main", Static).update(instrument_link)
            await pilot.pause()
            assert await pilot.click("#main", offset=(1, 0))
            await pilot.pause()
            assert app.current_command.action == CommandAction.INSTRUMENT
            assert app.current_command.target == "MSFT"
            assert "MSFT Equity" in str(app.query_one("#instrument-function", Static).content)
            assert "SECURITY DESCRIPTION" in str(app.query_one("#instrument-function", Static).content)

            await app.execute_command(parse_command("GP"))
            assert app.current_command.target == "MSFT"
            assert app.query_one("#chart-screen", EmbeddedChart).symbol == "MSFT"

            await app.execute_command(parse_command("HOME"))
            await app.execute_command(parse_command("GP"))
            assert app.current_command.target == "MSFT"
            assert app.query_one("#chart-screen", EmbeddedChart).symbol == "MSFT"

            await app.execute_command(parse_command("NEWS AAPL"))
            assert app.query_one("#instrument-strip").display
            assert "AAPL Equity" in str(app.query_one("#instrument-function", Static).content)
            assert "SECURITY NEWS" in str(app.query_one("#instrument-function", Static).content)
            assert app.query_one("#news-screen", NewsWorkspace).display
            assert app.query_one("#news-table", DataTable).row_count == 3

            await app.execute_command(parse_command("NEWS FED"))
            assert app.query_one("#instrument-strip").display
            assert "NO INSTRUMENT" in str(app.query_one("#instrument-function", Static).content)
            assert "NEWS | FED" in str(app.query_one("#news-wire", Static).content)
            news_screen = app.query_one("#news-screen", NewsWorkspace)
            news_screen.focus_table()
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            assert news_screen.selected_index == 1
            await pilot.click("#news-topic-economy")
            await pilot.pause()
            assert app.current_command.args == ("ECONOMY",)
            assert "NEWS | ECONOMY" in str(app.query_one("#news-wire", Static).content)

            await app.execute_command(parse_command("SOCIAL"))
            social_screen = app.query_one("#social-screen")
            assert social_screen.display
            social_setup = app.query_one("#social-setup")
            social_connect = app.query_one("#social-connect-server")
            assert not social_setup.display
            assert social_connect.display
            assert social_connect.region.bottom <= social_setup.region.bottom
            assert app.query_one("#social-auth").display
            assert "SIGN IN OR CREATE AN ACCOUNT" in str(
                app.query_one("#social-status", Static).content
            )
            assert len(social_screen.query("#social-header")) == 0
            assert len(social_screen.query("#social-footer")) == 0

            async def broken_instrument(_command) -> None:
                raise TypeError("malformed provider payload")

            app._show_instrument = broken_instrument
            await app.execute_command(parse_command("EQ TSLZ"))
            console = Console(width=160, record=True, file=io.StringIO())
            console.print(app.query_one("#main", Static).content)
            assert "COMMAND ERROR" in console.export_text()
            assert app.query_one("#instrument-strip").display
            assert "UNAVAILABLE" in str(app.query_one("#instrument-function", Static).content)

    asyncio.run(run())


def test_requested_chart_cases_render_for_every_asset_class(tmp_path) -> None:
    pytest.importorskip("textual")

    async def run() -> None:
        database = tmp_path / "chart-cases.sqlite3"
        service = MarketService(
            cache=SQLiteCache(database),
            watchlists=WatchlistStore(database),
            market_providers=[MockMarketProvider()],
        )
        app = AjaxTerminalApp(market_service=service)
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]
        cases = (
            ("GP AAPL 1D 5M", "AAPL", "1D", "5m"),
            ("GP AAPL 1Y 1D", "AAPL", "1Y", "1d"),
            ("GP MSFT 5D 15M", "MSFT", "5D", "15m"),
            ("GP EURUSD 5D 15M", "EURUSD", "5D", "15m"),
            ("GP GBPJPY 1Y 1D", "GBPJPY", "1Y", "1d"),
            ("GP US10Y 1Y 1D", "US10Y", "1Y", "1d"),
            ("GP DE10Y 5Y 1W", "DE10Y", "5Y", "1wk"),
            ("GP BRENT 6M 1D", "BRENT", "6M", "1d"),
            ("GP XAUUSD 1Y 1D", "XAUUSD", "1Y", "1d"),
        )
        async with app.run_test(size=(180, 48)):
            await asyncio.sleep(0.2)
            chart = app.query_one("#chart-screen", EmbeddedChart)
            for command, symbol, period, interval in cases:
                await app.execute_command(parse_command(command))
                assert chart.symbol == symbol
                assert chart.period == period
                assert chart.interval == interval
                assert chart.history is not None
                assert app.query_one("#chart-image").image is not None
                assert "COMMAND ERROR" not in str(app.query_one("#main", Static).content)
            instrument_header = str(app.query_one("#instrument-function", Static).content)
            assert "XAUUSD" in instrument_header

    asyncio.run(run())


def test_narrow_layout_prioritizes_main_panel(tmp_path) -> None:
    pytest.importorskip("textual")

    async def run() -> None:
        database = tmp_path / "narrow.sqlite3"
        service = MarketService(
            cache=SQLiteCache(database),
            watchlists=WatchlistStore(database),
            market_providers=[MockMarketProvider()],
        )
        app = AjaxTerminalApp(market_service=service)
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]
        async with app.run_test(size=(90, 35)) as pilot:
            await asyncio.sleep(0.2)
            assert not app.query_one("#sidebar").display
            assert not app.query_one("#watchlist", Static).display
            assert not app.query_one("#context", Static).display
            assert app.query_one("#main", Static).display
            await app.execute_command(parse_command("GP AAPL 1D 5M"))
            await pilot.pause()
            for row_id in ("#chart-range-row", "#chart-tools-row"):
                row = app.query_one(row_id)
                assert all(child.region.right <= row.region.right for child in row.children if child.display)
            assert not app.query_one("#chart-vwap").display
            assert not app.query_one("#chart-trend").display
            assert app.query_one("#chart-image").size.height >= 10
            await app.execute_command(parse_command("NEWS"))
            await pilot.pause()
            assert app.query_one("#news-screen", NewsWorkspace).display
            assert not app.query_one("#news-detail", Static).display
            assert not app.query_one("#news-topic-companies").display
            topic_row = app.query_one("#news-topic-row")
            assert all(child.region.right <= topic_row.region.right for child in topic_row.children if child.display)

    asyncio.run(run())
