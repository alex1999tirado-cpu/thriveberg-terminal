from __future__ import annotations

import asyncio
import logging
import re
import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from rich.text import Text

from ajax_terminal.analytics.live_bars import TradeTick
from ajax_terminal.analytics.fixed_income import analyze_bond
from ajax_terminal.config import setting
from ajax_terminal.analytics.forwards import DEFAULT_TENORS, build_forward_curve
from ajax_terminal.models.quote import DataQuality, Quote, StatementType
from ajax_terminal.providers.finnhub_stream import FinnhubThreadStream
from ajax_terminal.services.macro_service import MacroService
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.services.options_service import OptionsService
from ajax_terminal.services.equity_research_service import EquityResearchService, parse_screener_filters
from ajax_terminal.services.excel_export_service import ExcelExportService
from ajax_terminal.services.filings_service import FilingsService
from ajax_terminal.services.social_service import SocialService
from ajax_terminal.ui.commands import CommandAction, ParsedCommand, parse_command
from ajax_terminal.ui.screens.renderers import (
    render_calendar,
    render_bond_detail,
    render_chart_context,
    render_corporate_credit,
    render_credit_benchmark,
    render_context,
    render_curve,
    render_equity,
    render_financial_analysis,
    render_financial_statements,
    render_filings,
    render_export_result,
    render_fx,
    render_fx_forward,
    render_fx_matrix,
    render_government_bonds,
    render_help,
    render_home,
    render_instrument_context,
    render_instruments,
    render_macro,
    render_message,
    render_news,
    render_news_context,
    render_analyst,
    render_dividends,
    render_estimates,
    render_events,
    render_relative_valuation,
    render_screener,
    render_search,
    render_watchlist,
    render_wei,
)
from ajax_terminal.ui.widgets.chrome import HotkeyBar, InstrumentStrip, TerminalHeader
from ajax_terminal.ui.widgets.chart import EmbeddedChart
from ajax_terminal.ui.widgets.news import NewsWorkspace
from ajax_terminal.ui.widgets.options import OptionsWorkspace
from ajax_terminal.ui.widgets.social import SocialWorkspace
from ajax_terminal.ui.suggestions import CommandSuggestion, command_suggestions
from ajax_terminal.ui.chart_data import ChartEvent, ChartSupplement
from ajax_terminal.models.instrument import AssetClass, Instrument
from ajax_terminal.charts.launcher import (
    ChartRuntimeError,
    launch_curve_chart,
    launch_price_chart,
    launch_volatility_surface,
)
from ajax_terminal.utils.periods import normalize_history_interval, normalize_history_period
from ajax_terminal.utils.symbols import infer_instrument, is_fx_pair, split_fx_pair


LOGGER = logging.getLogger(__name__)


def _command_key(command: ParsedCommand) -> tuple[CommandAction, tuple[str, ...]]:
    return command.action, tuple(part.upper() for part in command.args)


class AjaxTerminalApp(App):
    TITLE = "THRIVEBERG Terminal"
    SUB_TITLE = "Markets. Data. Analytics."
    CSS_PATH = Path("ui/themes/ajax.tcss")

    BINDINGS = [
        ("f1", "help", "Help"),
        ("f2", "markets", "Markets"),
        ("f3", "fx", "FX"),
        ("f4", "rates", "Government bonds"),
        ("f5", "equity", "Equity"),
        ("f6", "macro", "Macro"),
        ("f7", "news", "News"),
        ("f8", "chart", "Chart"),
        ("f9", "social", "Social"),
        ("f10", "options", "Options"),
        ("ctrl+r", "refresh", "Refresh"),
        ("ctrl+k", "focus_command", "Search"),
        ("alt+left", "history_back", "Previous screen"),
        ("alt+right", "history_forward", "Next screen"),
        ("slash", "focus_command", "Command"),
        ("escape", "markets", "Back"),
        ("pageup", "scroll_up", "Scroll up"),
        ("pagedown", "scroll_down", "Scroll down"),
        ("alt+1", "equity_overview", "EQ overview"),
        ("alt+2", "financial_analysis", "Financial analysis"),
        ("alt+3", "income_statement", "Income statement"),
        ("alt+4", "balance_sheet", "Balance sheet"),
        ("alt+5", "cash_flow", "Cash flow"),
        ("alt+6", "estimates", "Estimates"),
        ("alt+7", "relative_valuation", "Relative valuation"),
        ("alt+8", "equity_news", "Equity news"),
    ]

    def __init__(
        self,
        market_service: MarketService | None = None,
        research_service: EquityResearchService | None = None,
        filings_service: FilingsService | None = None,
        export_service: ExcelExportService | None = None,
        social_service: SocialService | None = None,
        options_service: OptionsService | None = None,
        startup_command: str | None = None,
    ) -> None:
        super().__init__()
        self.market_service = market_service or MarketService()
        self.research_service = research_service or EquityResearchService(self.market_service)
        self.filings_service = filings_service or FilingsService(self.market_service.cache)
        self.export_service = export_service or ExcelExportService(self.market_service)
        self.social_service = social_service or SocialService()
        self.options_service = options_service or OptionsService(self.market_service)
        self.registry = self.market_service.registry
        self.macro_service = MacroService()
        self.news_service = NewsService()
        self.current_command = ParsedCommand(CommandAction.HOME, (), "HOME")
        self._back_history: list[ParsedCommand] = []
        self._forward_history: list[ParsedCommand] = []
        self._chart_request_id = 0
        self._loaded_symbol: str | None = None
        self._suggestions: list[CommandSuggestion] = []
        self._last_shareable_command = "MARKETS"
        self._active_quote: Quote | None = None
        self._active_stream: FinnhubThreadStream | None = None
        self._active_ticks: list[TradeTick] = []
        self._auto_refreshing = False
        self._startup_command = startup_command

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield TerminalHeader(id="topbar")
            yield InstrumentStrip(id="instrument-strip")
            yield Input(placeholder="> type command, e.g. FX EURUSD, CURVE USD, EQ AAPL", id="command")
            yield OptionList(id="command-suggestions")
            with Horizontal(id="body"):
                with Vertical(id="main-pane"):
                    with VerticalScroll(id="main-scroll"):
                        yield Static("Loading THRIVEBERG...", id="main")
                    yield EmbeddedChart(id="chart-screen")
                    yield NewsWorkspace(id="news-screen")
                    yield OptionsWorkspace(id="options-screen")
                    yield SocialWorkspace(self.social_service, id="social-screen")
                with Vertical(id="sidebar"):
                    yield Static("Loading context...", id="context")
                    yield Static("Loading watchlist...", id="watchlist")
            yield HotkeyBar(id="hotkeys")

    async def on_mount(self) -> None:
        self.set_interval(0.5, self._flush_active_ticks)
        self.set_interval(30.0, self._auto_refresh_visible_market_data)
        self.query_one("#command", Input).focus()
        await self.refresh_sidebars()
        command = parse_command(self._startup_command) if self._startup_command else self.current_command
        await self.execute_command(command)

    def on_unmount(self) -> None:
        self._stop_active_stream()

    def on_resize(self, event: events.Resize) -> None:
        if not self.is_mounted:
            return
        options_full_width = self.current_command.action in {
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        }
        self.query_one("#sidebar", Vertical).display = event.size.width >= 100 and not options_full_width
        self.query_one("#watchlist", Static).display = event.size.width >= 100
        self.query_one("#context", Static).display = event.size.width >= 145

    @on(Input.Submitted, "#command")
    async def command_submitted(self, event: Input.Submitted) -> None:
        parsed = parse_command(event.value)
        self.query_one("#command", Input).value = ""
        self._hide_suggestions()
        await self.execute_command(parsed)

    @on(Input.Changed, "#command")
    def command_changed(self, event: Input.Changed) -> None:
        uppercase = event.value.upper()
        if event.value != uppercase:
            cursor = event.input.cursor_position
            event.input.value = uppercase
            event.input.cursor_position = cursor
            return
        self._suggestions = command_suggestions(uppercase, self.registry)
        menu = self.query_one("#command-suggestions", OptionList)
        menu.clear_options()
        if not self._suggestions:
            menu.display = False
            return
        for index, suggestion in enumerate(self._suggestions):
            label = Text()
            label.append(f"{suggestion.command:<24}", style="bold cyan")
            label.append(suggestion.description, style="white")
            menu.add_option(Option(label, id=f"command-suggestion-{index}"))
        menu.highlighted = 0
        menu.display = True

    @on(OptionList.OptionSelected, "#command-suggestions")
    async def suggestion_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if not 0 <= event.option_index < len(self._suggestions):
            return
        suggestion = self._suggestions[event.option_index]
        command = self.query_one("#command", Input)
        command.value = ""
        self._hide_suggestions()
        await self.execute_command(parse_command(suggestion.command))
        command.focus()

    def action_focus_command(self) -> None:
        command = self.query_one("#command", Input)
        command.focus()

    def _hide_suggestions(self) -> None:
        self._suggestions = []
        menu = self.query_one("#command-suggestions", OptionList)
        menu.clear_options()
        menu.display = False

    async def action_open_instrument(self, symbol: str) -> None:
        clean_symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.^=_/-]{1,32}", clean_symbol):
            self.notify("Invalid instrument symbol", severity="warning")
            return
        await self.execute_command(parse_command(f"DES {clean_symbol}"))

    async def action_open_methodology(self, symbol: str) -> None:
        await self.action_open_instrument(symbol)

    async def action_run_command(self, command: str) -> None:
        clean_command = " ".join(command.strip().upper().split())
        if not clean_command or len(clean_command) > 96:
            self.notify("Invalid terminal command", severity="warning")
            return
        self._hide_suggestions()
        await self.execute_command(parse_command(clean_command))

    async def action_history_back(self) -> None:
        if not self._back_history:
            return
        target = self._back_history.pop()
        self._forward_history.append(self.current_command)
        await self.execute_command(target, record_history=False)

    async def action_history_forward(self) -> None:
        if not self._forward_history:
            return
        target = self._forward_history.pop()
        self._back_history.append(self.current_command)
        await self.execute_command(target, record_history=False)

    async def action_help(self) -> None:
        await self.execute_command(parse_command("HELP"))

    async def action_markets(self) -> None:
        await self.execute_command(parse_command("MARKETS"))

    async def action_fx(self) -> None:
        await self.execute_command(parse_command("FX"))

    async def action_rates(self) -> None:
        await self.execute_command(parse_command("GOVT"))

    async def action_equity(self) -> None:
        await self.execute_command(parse_command("EQ AAPL"))

    async def action_macro(self) -> None:
        await self.execute_command(parse_command("ECO US"))

    async def action_news(self) -> None:
        await self.execute_command(parse_command("NEWS"))

    async def action_social(self) -> None:
        await self.execute_command(parse_command("SOCIAL"))

    async def action_options(self) -> None:
        await self.execute_command(parse_command(f"OMON {self._current_equity_symbol()}"))

    async def action_chart(self) -> None:
        symbol = self.current_command.target or "AAPL"
        period = _command_period(self.current_command)
        await self.execute_command(parse_command(f"CHART {symbol} {period}"))

    async def action_equity_overview(self) -> None:
        await self.execute_command(parse_command(f"EQ {self._current_equity_symbol()}"))

    async def action_financial_analysis(self) -> None:
        await self.execute_command(parse_command(f"FA {self._current_equity_symbol()}"))

    async def action_income_statement(self) -> None:
        await self.execute_command(parse_command(f"IS {self._current_equity_symbol()}"))

    async def action_balance_sheet(self) -> None:
        await self.execute_command(parse_command(f"BS {self._current_equity_symbol()}"))

    async def action_cash_flow(self) -> None:
        await self.execute_command(parse_command(f"CF {self._current_equity_symbol()}"))

    async def action_estimates(self) -> None:
        await self.execute_command(parse_command(f"EE {self._current_equity_symbol()}"))

    async def action_relative_valuation(self) -> None:
        await self.execute_command(parse_command(f"RV {self._current_equity_symbol()}"))

    async def action_equity_news(self) -> None:
        await self.execute_command(parse_command(f"NEWS {self._current_equity_symbol()}"))

    async def action_open_url(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        trusted_hosts = (
            "sec.gov",
            "filings.xbrl.org",
            "company-information.service.gov.uk",
            "edinet-fsa.go.jp",
            "sedarplus.ca",
            "hkexnews.hk",
            "asic.gov.au",
            "ser-ag.com",
            "iosco.org",
        )
        if not url.startswith("https://") or not any(
            host == domain or host.endswith(f".{domain}") for domain in trusted_hosts
        ):
            self.notify("Blocked untrusted external URL", severity="warning")
            return
        await asyncio.to_thread(webbrowser.open, url)

    async def action_open_export(self, path: str) -> None:
        workbook = Path(path).resolve()
        if workbook.suffix.lower() != ".xlsx" or not workbook.is_file():
            self.notify("Exported workbook is no longer available", severity="warning")
            return
        await asyncio.to_thread(webbrowser.open, workbook.as_uri())

    async def action_refresh(self) -> None:
        await self.refresh_sidebars()
        await self.execute_command(self.current_command)

    def action_scroll_up(self) -> None:
        main_scroll = self.query_one("#main-scroll", VerticalScroll)
        if main_scroll.display:
            main_scroll.scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        main_scroll = self.query_one("#main-scroll", VerticalScroll)
        if main_scroll.display:
            main_scroll.scroll_page_down(animate=False)

    async def refresh_sidebars(self) -> None:
        watchlist, headlines, events = await asyncio.gather(
            self.market_service.watchlist_quotes(),
            self.news_service.headlines(limit=8),
            self.macro_service.calendar("TODAY"),
        )
        self.query_one("#watchlist", Static).update(render_watchlist(watchlist))
        self.query_one("#context", Static).update(render_context(headlines, events))

    async def execute_command(self, command: ParsedCommand, *, record_history: bool = True) -> None:
        self._stop_active_stream()
        self._active_quote = None
        command = self._apply_loaded_instrument(command)
        command = await self._canonicalize_options_command(command)
        if record_history and _command_key(command) != _command_key(self.current_command):
            self._back_history.append(self.current_command)
            self._back_history = self._back_history[-100:]
            self._forward_history.clear()
        if command.action != CommandAction.SOCIAL:
            self._last_shareable_command = " ".join((command.raw or str(command.action)).strip().upper().split())
        header_spec = self._instrument_header_spec(command)
        self.current_command = command
        self.query_one("#topbar", TerminalHeader).set_navigation_state(
            can_go_back=bool(self._back_history),
            can_go_forward=bool(self._forward_history),
        )
        strip = self.query_one("#instrument-strip", InstrumentStrip)
        if header_spec is None:
            strip.clear()
        else:
            function, symbol, period, interval = header_spec
            strip.prepare(function, symbol, period, interval)
            self._loaded_symbol = symbol
        main_scroll = self.query_one("#main-scroll", VerticalScroll)
        chart_screen = self.query_one("#chart-screen", EmbeddedChart)
        news_screen = self.query_one("#news-screen", NewsWorkspace)
        options_screen = self.query_one("#options-screen", OptionsWorkspace)
        social_screen = self.query_one("#social-screen", SocialWorkspace)
        headless_charts = self._headless_chart_fallback()
        showing_chart = command.action == CommandAction.CHART
        if not showing_chart:
            chart_screen.deactivate_stream()
        showing_news = command.action == CommandAction.NEWS
        showing_options = command.action in {
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        }
        showing_social = command.action == CommandAction.SOCIAL
        self.query_one("#sidebar", Vertical).display = self.size.width >= 100 and not showing_options
        main_scroll.display = not showing_chart and not showing_news and not showing_options and not showing_social
        chart_screen.display = showing_chart
        news_screen.display = showing_news
        options_screen.display = showing_options
        social_screen.display = showing_social
        if showing_social:
            social_screen.set_share_context(self._last_shareable_command)
        if showing_news:
            news_screen.set_loading(" ".join(command.args) if command.args else None)
        if showing_options:
            mode = {
                CommandAction.OPTIONS: "OMON",
                CommandAction.OPTION_VALUATION: "OVME",
                CommandAction.VOL: "OVDV",
            }[command.action]
            options_screen.set_loading(mode, command.target or "AAPL")
        if not showing_chart and not showing_news and not showing_options and not showing_social:
            main_scroll.scroll_home(animate=False)
        main = self.query_one("#main", Static)
        main.update(render_message("LOADING", command.raw or "MARKETS"))
        try:
            await self._dispatch_command(command, main)
        except Exception:
            LOGGER.exception("command failed action=%s raw=%s", command.action, command.raw)
            main_scroll.display = True
            chart_screen.display = False
            news_screen.display = False
            options_screen.display = False
            social_screen.display = False
            if header_spec is not None:
                strip.set_unavailable()
            main.update(
                render_message(
                    "COMMAND ERROR",
                    f"Could not load {command.raw or command.action}. No substitute data was shown. See logs/ajax.log.",
                )
            )

    async def _dispatch_command(self, command: ParsedCommand, main: Static) -> None:
        action = command.action
        if action == CommandAction.HOME:
            await self._show_home()
        elif action == CommandAction.WEI:
            await self._show_wei()
        elif action == CommandAction.INSTRUMENTS:
            await self._show_instruments(command)
        elif action == CommandAction.FX:
            await self._show_fx(command)
        elif action == CommandAction.FWD:
            await self._show_fx(command, forwards_only=True)
        elif action == CommandAction.CURVE:
            await self._show_curve(command)
        elif action == CommandAction.GOVERNMENT:
            await self._show_government(command)
        elif action == CommandAction.CORPORATE:
            await self._show_corporate(command)
        elif action == CommandAction.BOND:
            await self._show_bond(command)
        elif action == CommandAction.ECO:
            await self._show_macro(command)
        elif action == CommandAction.MAP:
            main.update(render_message("MAP / GLOBAL ECONOMIC MAP", "Open the desktop edition for the interactive ECharts world map."))
        elif action == CommandAction.CAL:
            await self._show_calendar(command)
        elif action == CommandAction.NEWS:
            await self._show_news(command)
        elif action == CommandAction.SOCIAL:
            await self.query_one("#social-screen", SocialWorkspace).activate()
        elif action == CommandAction.DOOM:
            main.update(render_message("DOOM / FREEDOOM", "Open the desktop edition to run the embedded game."))
        elif action in {CommandAction.OPTIONS, CommandAction.OPTION_VALUATION, CommandAction.VOL}:
            await self._show_options(command)
        elif action == CommandAction.INCOME_STATEMENT:
            await self._show_statement(command, StatementType.INCOME)
        elif action == CommandAction.BALANCE_SHEET:
            await self._show_statement(command, StatementType.BALANCE_SHEET)
        elif action == CommandAction.CASH_FLOW:
            await self._show_statement(command, StatementType.CASH_FLOW)
        elif action in {CommandAction.FILINGS, CommandAction.TEN_K, CommandAction.TEN_Q}:
            await self._show_filings(command)
        elif action == CommandAction.EXPORT:
            await self._show_export(command)
        elif action == CommandAction.FINANCIAL_ANALYSIS:
            await self._show_financial_analysis(command)
        elif action == CommandAction.RELATIVE_VALUATION:
            await self._show_relative_valuation(command)
        elif action == CommandAction.COMP:
            await self._show_relative_valuation(
                ParsedCommand(CommandAction.RELATIVE_VALUATION, command.args, command.raw)
            )
        elif action == CommandAction.ESTIMATES:
            await self._show_estimates(command)
        elif action == CommandAction.ANALYST:
            await self._show_analyst(command)
        elif action == CommandAction.DIVIDENDS:
            await self._show_dividends(command)
        elif action == CommandAction.EVENTS:
            await self._show_events(command)
        elif action == CommandAction.SCREENER:
            await self._show_screener(command)
        elif action == CommandAction.CHART:
            await self._show_chart(command)
        elif action == CommandAction.RISK:
            await self._show_chart(ParsedCommand(CommandAction.CHART, command.args, command.raw))
        elif action in {CommandAction.EQUITY, CommandAction.INSTRUMENT, CommandAction.INDEX, CommandAction.COMMODITY}:
            await self._show_instrument(command)
        elif action == CommandAction.WATCH:
            await self._handle_watch(command)
        elif action == CommandAction.HELP:
            main.update(render_help())
        elif action == CommandAction.SEARCH:
            await self._show_search(command)
        else:
            main.update(render_message(str(action), "Phase 2 shell is ready; provider and analytics interfaces are in place."))

    async def _show_home(self) -> None:
        definitions = self.registry.home_groups()
        quote_tasks = {
            group: asyncio.create_task(
                self.market_service.government_quotes([item.symbol for item in instruments])
                if group == "RATES"
                else self.market_service.bulk_quotes([item.symbol for item in instruments])
            )
            for group, instruments in definitions.items()
        }
        events_task = asyncio.create_task(self.macro_service.calendar("TODAY"))
        news_task = asyncio.create_task(self.news_service.headlines(limit=6))
        groups = {group: await task for group, task in quote_tasks.items()}
        self.query_one("#main", Static).update(render_home(groups, await events_task, await news_task))

    async def _show_wei(self) -> None:
        definitions = self.registry.index_regions()
        tasks = {
            region: asyncio.create_task(
                self.market_service.market_snapshots([instrument.symbol for instrument in instruments])
            )
            for region, instruments in definitions.items()
        }
        groups = {region: await task for region, task in tasks.items()}
        self.query_one("#main", Static).update(render_wei(groups))

    async def _show_instruments(self, command: ParsedCommand) -> None:
        selected_filter = command.target
        instruments = self.registry.list_filter(selected_filter)
        if instruments is None:
            self.query_one("#main", Static).update(
                render_message(
                    "INSTRUMENT REGISTRY",
                    "Use FX, INDEX, RATES, GOVT, CORP, BOND or CMDTY as filter.",
                )
            )
            return
        self.query_one("#main", Static).update(render_instruments(instruments, selected_filter))

    async def _show_fx(self, command: ParsedCommand, forwards_only: bool = False) -> None:
        if not forwards_only and not command.args:
            quotes = await self.market_service.bulk_quotes(
                [instrument.symbol for instrument in self.registry.fx_pairs()]
            )
            self.query_one("#main", Static).update(render_fx_matrix(quotes, self.registry.g10_currencies))
            return
        pair = command.target or "EURUSD"
        period = "1Y" if forwards_only else _command_period(command)
        quote_task = asyncio.create_task(self.market_service.quote(pair))
        history_task = asyncio.create_task(self.market_service.history(pair, period))
        news_task = asyncio.create_task(self.news_service.headlines(pair, limit=8))
        quote = await quote_task
        forwards = await self._forward_curve(pair, quote.price or 1.0)
        if forwards_only and len(command.args) > 1:
            tenor = command.args[1].upper()
            forwards = [point for point in forwards if point.tenor == tenor] or forwards
        history = await history_task
        news = await news_task
        self._set_instrument_header(quote)
        if forwards_only:
            selected_tenor = command.args[1].upper() if len(command.args) > 1 else None
            self.query_one("#main", Static).update(
                render_fx_forward(quote, forwards, history, selected_tenor)
            )
        else:
            self.query_one("#main", Static).update(render_fx(quote, forwards, history))
        self.query_one("#context", Static).update(render_instrument_context(quote, history, news))

    async def _forward_curve(self, pair: str, spot: float):
        base, quote_ccy = split_fx_pair(pair)
        domestic_curve, foreign_curve = await asyncio.gather(
            self.market_service.curve(quote_ccy, allow_mock=False),
            self.market_service.curve(base, allow_mock=False),
        )
        if any(
            curve.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE} or not curve.points
            for curve in (domestic_curve, foreign_curve)
        ):
            return []
        if any(
            min(point.years for point in curve.points) > 0.25
            or max(point.years for point in curve.points) < 2.0
            for curve in (domestic_curve, foreign_curve)
        ):
            return []
        domestic_rates = _forward_rate_map(domestic_curve)
        foreign_rates = _forward_rate_map(foreign_curve)
        return build_forward_curve(pair, spot, domestic_rates, foreign_rates, tenors=list(DEFAULT_TENORS))

    async def _show_curve(self, command: ParsedCommand) -> None:
        currency = _normalize_curve_currency(command.target or "USD")
        curve = await self.market_service.curve(currency, allow_mock=False)
        self.query_one("#main", Static).update(render_curve(curve))
        if (
            not self._headless_chart_fallback()
            and curve.points
            and curve.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ):
            try:
                launch_curve_chart(currency)
            except ChartRuntimeError as exc:
                self.notify(str(exc), severity="error", timeout=8)

    async def _show_government(self, command: ParsedCommand) -> None:
        target = command.target
        registered = self.registry.get(target) if target else None
        if registered is not None and registered.instrument_type == "GOVT_BENCHMARK":
            instruments = [registered]
            label = registered.symbol
        else:
            country = _normalize_govie_country(target) if target else None
            instruments = self.registry.government_benchmarks(country)
            if country is None:
                instruments = [item for item in instruments if item.symbol.endswith("10Y")]
            label = country or "GLOBAL 10Y"
        if not instruments:
            self.query_one("#main", Static).update(
                render_message("GOVERNMENT BONDS", f"No sovereign benchmarks registered for {target or '--'}.")
            )
            return
        quotes = await self.market_service.government_quotes([item.symbol for item in instruments])
        if len(quotes) == 1:
            self._set_instrument_header(quotes[0])
        self.query_one("#main", Static).update(render_government_bonds(instruments, quotes, label))

    async def _show_corporate(self, command: ParsedCommand) -> None:
        target = command.target
        registered = self.registry.get(target) if target else None
        if registered is not None and registered.instrument_type == "CORPORATE_BOND":
            await self._show_bond(ParsedCommand(CommandAction.BOND, command.args, command.raw))
            return
        if registered is not None and registered.instrument_type == "CREDIT_BENCHMARK":
            benchmark_task = asyncio.create_task(self.market_service.credit_benchmark(registered.symbol))
            history_task = asyncio.create_task(
                self.market_service.history(registered.symbol, "1Y", allow_mock=False)
            )
            benchmark, history = await asyncio.gather(benchmark_task, history_task)
            change = benchmark.yield_change_bp / 100.0 if benchmark.yield_change_bp is not None else None
            self._set_instrument_header(
                Quote(
                    symbol=benchmark.symbol,
                    name=benchmark.name,
                    price=benchmark.effective_yield_pct,
                    change=change,
                    currency="%",
                    asset_class="RATE",
                    provider=benchmark.provider,
                    quality=benchmark.quality,
                    timestamp=benchmark.timestamp,
                )
            )
            self.query_one("#main", Static).update(render_credit_benchmark(benchmark, history))
            return
        benchmarks = await self.market_service.credit_benchmarks()
        bonds = self.registry.corporate_bonds(target)
        self.query_one("#main", Static).update(
            render_corporate_credit(benchmarks, bonds, target or "US CREDIT")
        )

    async def _show_bond(self, command: ParsedCommand) -> None:
        if not command.args:
            await self._show_corporate(ParsedCommand(CommandAction.CORPORATE, (), command.raw))
            return
        target = command.args[0]
        registered = self.registry.get(target)
        if registered is not None and registered.instrument_type == "GOVT_BENCHMARK":
            await self._show_government(ParsedCommand(CommandAction.GOVERNMENT, (registered.symbol,), command.raw))
            return
        if registered is not None and registered.instrument_type == "CREDIT_BENCHMARK":
            await self._show_corporate(ParsedCommand(CommandAction.CORPORATE, (registered.symbol,), command.raw))
            return
        if registered is not None and registered.instrument_type == "CORPORATE_BOND":
            try:
                price = _bond_price(command.args[1:])
            except ValueError as exc:
                self.query_one("#main", Static).update(render_message("BOND", f"Invalid clean price: {exc}."))
                return
            analytics = None
            if price is not None and registered.coupon is not None and registered.maturity is not None:
                analytics = analyze_bond(
                    price,
                    registered.coupon / 100.0,
                    date.today(),
                    registered.maturity,
                )
            self.query_one("#instrument-strip", InstrumentStrip).set_unavailable()
            self.query_one("#main", Static).update(render_bond_detail(registered, analytics, price))
            return
        try:
            coupon = float(target)
            maturity = date.fromisoformat(command.args[1])
            if maturity <= date.today():
                raise ValueError("maturity must be after settlement")
            price = _bond_price(command.args[2:])
            price_source = "USER INPUT" if price is not None else "PAR ASSUMPTION"
            price = price if price is not None else 100.0
            instrument = Instrument(
                symbol=f"GENERIC-{coupon:g}-{maturity.year}",
                name="Generic Fixed-Rate Bond",
                asset_class=AssetClass.BOND,
                currency="USD",
                instrument_type="USER_DEFINED_BOND",
                issuer="User-defined",
                coupon=coupon,
                maturity=maturity,
                seniority="--",
                source="User-defined terms; clean price defaults to par when omitted",
            )
            analytics = analyze_bond(price, coupon / 100.0, date.today(), maturity)
            self.query_one("#main", Static).update(
                render_bond_detail(instrument, analytics, price, price_source)
            )
        except (IndexError, ValueError) as exc:
            self.query_one("#main", Static).update(
                render_message(
                    "BOND",
                    f"Unknown bond or invalid terms ({exc}). Use BOND AAPL44 [PRICE 98.50] "
                    "or BOND 4.25 2034-05-15 [98.50].",
                )
            )

    async def _show_macro(self, command: ParsedCommand) -> None:
        if len(command.args) >= 2:
            indicator_code, country = command.args[0], command.args[1]
            indicators = await self.macro_service.monitor(country)
            selected = await self.macro_service.indicator(indicator_code, country)
            self.query_one("#main", Static).update(render_macro(country, indicators, selected))
            return
        country = command.target or "US"
        indicators = await self.macro_service.monitor(country)
        self.query_one("#main", Static).update(render_macro(country, indicators))

    async def _show_calendar(self, command: ParsedCommand) -> None:
        events = await self.macro_service.calendar(command.target)
        self.query_one("#main", Static).update(render_calendar(events))

    async def _show_news(self, command: ParsedCommand) -> None:
        topic = " ".join(command.args) if command.args else None
        if topic and self._loaded_symbol == topic:
            items, quote = await asyncio.gather(
                self.news_service.headlines(topic, limit=20),
                self.market_service.quote(topic),
            )
            self._set_instrument_header(quote)
        else:
            items = await self.news_service.headlines(topic, limit=20)
        self.query_one("#main", Static).update(render_news(items, topic))
        news_screen = self.query_one("#news-screen", NewsWorkspace)
        news_screen.set_items(items, topic)
        self.query_one("#context", Static).update(render_news_context(items, topic))
        news_screen.focus_table()

    async def _show_options(self, command: ParsedCommand) -> None:
        symbol = command.target or self._current_equity_symbol()
        instrument = self.registry.resolve(symbol)
        workspace = self.query_one("#options-screen", OptionsWorkspace)
        if instrument.asset_class != AssetClass.EQUITY:
            message = f"{symbol} is not an equity or ETF ticker."
            if command.action == CommandAction.VOL:
                self.query_one("#main", Static).update(render_message("OPTIONS UNAVAILABLE", message))
            else:
                workspace.query_one("#options-market-line", Static).update(
                    f"[bold red]OPTIONS UNAVAILABLE[/]  {message}"
                )
            self.query_one("#instrument-strip", InstrumentStrip).set_unavailable()
            return

        expiry_text = None
        if command.action == CommandAction.OPTIONS and len(command.args) > 1:
            expiry_text = command.args[1]
        elif command.action == CommandAction.OPTION_VALUATION and len(command.args) > 3:
            expiry_text = command.args[3]
        try:
            expiry = date.fromisoformat(expiry_text) if expiry_text else None
        except ValueError:
            workspace.query_one("#options-market-line", Static).update(
                "[bold red]INVALID EXPIRY[/]  Use YYYY-MM-DD."
            )
            return

        if command.action == CommandAction.VOL:
            surface = await self.options_service.volatility_surface(symbol)
            self._set_options_instrument_header(
                surface.symbol,
                surface.name,
                surface.spot,
                surface.currency,
                surface.provider,
                surface.quality,
                surface.timestamp,
            )
            self.query_one("#context", Static).update(
                render_message(
                    f"OVDV / {surface.symbol}",
                    f"{len(surface.slices)} real expiries | BS IV | interpolation only inside observed strikes",
                )
            )
            if not surface.slices or surface.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}:
                workspace.query_one("#options-market-line", Static).update(
                    f"[bold red]OVDV / {surface.symbol} UNAVAILABLE[/]  "
                    f"{surface.message or 'No supported real option-chain observations are available.'}"
                )
                return
            workspace.set_surface(surface)
            return

        if command.action == CommandAction.OPTIONS:
            chains, context = await self.options_service.option_monitor(symbol, expiry)
            chain = chains[0]
        else:
            chain, context = await self.options_service.chain_with_context(symbol, expiry)
            chains = [chain]
        self._set_options_instrument_header(
            chain.symbol,
            chain.name,
            chain.spot,
            chain.currency,
            chain.provider,
            chain.quality,
            chain.timestamp,
            chain.underlying_change,
            chain.underlying_change_percent,
        )
        if command.action == CommandAction.OPTION_VALUATION:
            side_arg = command.args[1].upper() if len(command.args) > 1 else "C"
            option_type = "put" if side_arg in {"P", "PUT"} else "call"
            strike = None
            if len(command.args) > 2:
                try:
                    strike = float(command.args[2])
                except ValueError:
                    workspace.query_one("#options-market-line", Static).update(
                        "[bold red]INVALID STRIKE[/]  Use OVME AAPL C 350 2026-12-18."
                    )
                    return
            workspace.set_pricer(chain, context, option_type, strike)
        else:
            workspace.set_chain(chain, context, chains)
        self.query_one("#context", Static).update(
            render_message(
                f"OPTIONS / {chain.symbol}",
                f"{sum(len(item.calls) for item in chains)} calls | "
                f"{sum(len(item.puts) for item in chains)} puts | "
                f"{len(chains)} expiries | {chain.provider} {chain.quality}",
            )
        )

    async def _canonicalize_options_command(self, command: ParsedCommand) -> ParsedCommand:
        if command.action not in {
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        } or not command.target:
            return command
        query = command.target.strip().upper()
        if not query or not hasattr(self.market_service, "search"):
            return command
        try:
            results = await self.market_service.search(query)
        except Exception:
            LOGGER.exception("option underlying search failed query=%s", query)
            return command
        equity_results = [
            item for item in results
            if str(item[2]).upper() in {"EQUITY", "ETF", "AssetClass.EQUITY".upper()}
        ]
        exact = next((item for item in equity_results if item[0].upper() == query), None)
        named = next(
            (
                item for item in equity_results
                if query in re.sub(r"[^A-Z0-9]", "", item[1].upper())
                or query in item[1].upper().split()
            ),
            None,
        )
        match = exact or named
        if match is None or match[0].upper() == query:
            return command
        args = (match[0].upper(), *command.args[1:])
        aliases = {
            CommandAction.OPTIONS: "OMON",
            CommandAction.OPTION_VALUATION: "OVME",
            CommandAction.VOL: "OVDV",
        }
        return ParsedCommand(command.action, args, " ".join((aliases[command.action], *args)))

    def _set_options_instrument_header(
        self,
        symbol: str,
        name: str,
        price: float | None,
        currency: str,
        provider: str,
        quality: DataQuality,
        timestamp,
        change: float | None = None,
        change_percent: float | None = None,
    ) -> None:
        self._set_instrument_header(
            Quote(
                symbol=symbol,
                name=name,
                price=price,
                change=change,
                change_percent=change_percent,
                currency=currency,
                asset_class="EQUITY",
                provider=provider,
                quality=quality,
                timestamp=timestamp,
            )
        )

    async def _show_statement(self, command: ParsedCommand, statement_type: StatementType) -> None:
        symbol = command.target or "AAPL"
        instrument = self.registry.resolve(symbol)
        if instrument.asset_class != AssetClass.EQUITY:
            self._set_instrument_header(await self.market_service.quote(symbol))
            self.query_one("#main", Static).update(
                render_message("FINANCIAL STATEMENTS", f"{symbol} is not an equity ticker.")
            )
            return
        statements, quote = await asyncio.gather(
            self.market_service.financial_statements(symbol, statement_type),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_financial_statements(statements))

    async def _show_filings(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        forms = {
            CommandAction.TEN_K: ("10-K",),
            CommandAction.TEN_Q: ("10-Q",),
        }.get(command.action, ("10-K", "10-Q"))
        active = {
            CommandAction.TEN_K: "10K",
            CommandAction.TEN_Q: "10Q",
        }.get(command.action, "FILINGS")
        filings, quote = await asyncio.gather(
            self.filings_service.filings(symbol, forms=forms),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_filings(filings, active))

    async def _show_export(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        quote = await self.market_service.quote(symbol)
        self._set_instrument_header(quote)
        try:
            result = await self.export_service.export_financials(symbol)
        except ValueError as exc:
            self.query_one("#main", Static).update(render_message("XLS EXPORT", str(exc)))
            return
        self.query_one("#main", Static).update(
            render_export_result(
                result.symbol,
                str(result.path),
                result.sheet_names,
                result.skipped,
            )
        )

    async def _show_financial_analysis(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        analysis, quote = await asyncio.gather(
            self.research_service.financial_analysis(symbol),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_financial_analysis(analysis))

    async def _show_relative_valuation(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        peers = list(command.args[1:]) if len(command.args) > 1 else None
        valuation, quote = await asyncio.gather(
            self.research_service.relative_valuation(symbol, peers),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_relative_valuation(valuation))

    async def _show_estimates(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        estimates, quote = await asyncio.gather(
            self.research_service.estimates(symbol),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_estimates(estimates))

    async def _show_analyst(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        consensus, quote = await asyncio.gather(
            self.research_service.analyst_consensus(symbol),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_analyst(consensus))

    async def _show_dividends(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        dividends, quote = await asyncio.gather(
            self.research_service.dividends(symbol),
            self.market_service.quote(symbol),
        )
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(render_dividends(dividends))

    async def _show_events(self, command: ParsedCommand) -> None:
        if command.target:
            events, quote = await asyncio.gather(
                self.research_service.events(command.target),
                self.market_service.quote(command.target),
            )
            self._set_instrument_header(quote)
            self.query_one("#main", Static).update(render_events(events, command.target))
            return
        major_indices = [
            item.symbol
            for instruments in self.registry.index_regions().values()
            for item in instruments[:3]
        ]
        symbols = [*self.market_service.watchlists.symbols(), *major_indices]
        events = await self.research_service.event_schedule(symbols, days=7)
        self.query_one("#main", Static).update(render_events(events))

    async def _show_screener(self, command: ParsedCommand) -> None:
        try:
            filters = parse_screener_filters(command.args)
        except ValueError as exc:
            self.query_one("#main", Static).update(render_message("EQS FILTER ERROR", str(exc)))
            return
        page = await self.research_service.screener(filters)
        self.query_one("#main", Static).update(render_screener(page))

    async def _show_chart(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        period = normalize_history_period(command.args[1] if len(command.args) > 1 else None)
        interval = normalize_history_interval(period, command.args[2] if len(command.args) > 2 else None)
        instrument = self.registry.resolve(symbol)
        headless_fallback = self._headless_chart_fallback()
        chart = self.query_one("#chart-screen", EmbeddedChart)
        chart.prepare(symbol, period, interval)
        chart.set_streaming_enabled(not headless_fallback)
        self._chart_request_id += 1
        request_id = self._chart_request_id
        try:
            history_task = asyncio.create_task(
                self.market_service.history(symbol, period, interval, allow_mock=False)
            )
            quote_task = asyncio.create_task(
                self.market_service.quote(symbol, allow_mock=False)
            )
            news_task = asyncio.create_task(self.news_service.headlines(symbol, limit=8))
            supplement_task = asyncio.create_task(self._load_chart_supplement(symbol, instrument))
            history, quote, news, supplement = await asyncio.gather(
                history_task,
                quote_task,
                news_task,
                supplement_task,
            )
            if not history.bars or (
                not headless_fallback
                and history.quality in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
            ):
                raise ValueError("No real price/yield history is available for this instrument")
            if instrument.asset_class == AssetClass.FX and quote.price:
                supplement.forwards = await self._forward_curve(symbol, quote.price)
        except Exception as exc:
            if request_id == self._chart_request_id:
                chart.set_error(f"Unable to load chart: {exc}")
                self.query_one("#instrument-strip", InstrumentStrip).set_unavailable()
            return
        if request_id != self._chart_request_id:
            return
        self._set_instrument_header(quote)
        self.query_one("#context", Static).update(render_chart_context(quote, history, news, supplement))
        chart.set_market_data(quote, supplement)
        chart.set_history(history)
        chart.focus()

    def _headless_chart_fallback(self) -> bool:
        driver = getattr(self, "_driver", None)
        return driver is not None and type(driver).__name__ == "HeadlessDriver"

    async def _load_chart_supplement(self, symbol: str, instrument: Instrument) -> ChartSupplement:
        supplement = ChartSupplement(instrument)
        if instrument.asset_class == AssetClass.EQUITY:
            fundamentals_task = asyncio.create_task(self.market_service.equity_fundamentals(symbol))
            profile_task = asyncio.create_task(self.research_service.company_profile(symbol))
            estimates_task = asyncio.create_task(self.research_service.estimates(symbol))
            events_task = asyncio.create_task(self.research_service.events(symbol))
            fundamentals, profile, estimates, events = await asyncio.gather(
                fundamentals_task,
                profile_task,
                estimates_task,
                events_task,
            )
            supplement.fundamentals = fundamentals
            supplement.profile = profile
            supplement.estimates = estimates
            if estimates.earnings_date is not None:
                supplement.events.append(
                    ChartEvent(
                        estimates.earnings_date.strftime("%d %b"),
                        "EARNINGS",
                        estimates.earnings_date.strftime("%H:%M UTC"),
                        estimates.quality,
                    )
                )
            supplement.events.extend(
                ChartEvent(
                    item.event_date.strftime("%d %b"),
                    item.event_type,
                    item.detail,
                    item.quality,
                )
                for item in events[:3]
            )
            return supplement

        if instrument.asset_class in {AssetClass.FX, AssetClass.RATE, AssetClass.COMMODITY}:
            country = instrument.country if instrument.asset_class == AssetClass.RATE else "TODAY"
            events = await self.macro_service.calendar(country or "TODAY")
            supplement.events.extend(
                ChartEvent(
                    item.time.strftime("%d %b %H:%M") if item.time else "--",
                    f"{item.country} {item.event}",
                    item.consensus,
                    item.quality,
                )
                for item in events[:3]
            )
        return supplement

    @on(EmbeddedChart.SelectionChanged)
    async def chart_selection_changed(self, event: EmbeddedChart.SelectionChanged) -> None:
        await self.execute_command(parse_command(f"GP {event.symbol} {event.period} {event.interval}"))

    @on(EmbeddedChart.RefreshRequested)
    async def chart_refresh_requested(self, event: EmbeddedChart.RefreshRequested) -> None:
        await self.execute_command(parse_command(f"GP {event.symbol} {event.period} {event.interval}"))

    @on(EmbeddedChart.NewsRequested)
    async def chart_news_requested(self, event: EmbeddedChart.NewsRequested) -> None:
        await self.execute_command(parse_command(f"NEWS {event.symbol}"))

    @on(EmbeddedChart.PopOutRequested)
    def chart_popout_requested(self, event: EmbeddedChart.PopOutRequested) -> None:
        chart = self.query_one("#chart-screen", EmbeddedChart)
        chart.deactivate_stream("STREAM TRANSFERRED TO POP OUT")
        try:
            process = launch_price_chart(event.symbol, event.period, event.interval)
        except ChartRuntimeError as exc:
            chart.activate_stream()
            self.notify(str(exc), severity="error")
            return
        self.set_timer(
            2.0,
            lambda: self._report_chart_launch_failure(process, f"GP {event.symbol}"),
        )
        self.notify(f"Interactive GP opened for {event.symbol}", title="POP OUT")

    @on(EmbeddedChart.QuoteChanged)
    def chart_quote_changed(self, event: EmbeddedChart.QuoteChanged) -> None:
        if self.current_command.action in {CommandAction.CHART, CommandAction.RISK}:
            self.query_one("#instrument-strip", InstrumentStrip).set_quote(event.quote)

    @on(NewsWorkspace.TopicRequested)
    async def news_topic_requested(self, event: NewsWorkspace.TopicRequested) -> None:
        command = "NEWS" if event.topic is None else f"NEWS {event.topic}"
        await self.execute_command(parse_command(command))

    @on(NewsWorkspace.RefreshRequested)
    async def news_refresh_requested(self, _event: NewsWorkspace.RefreshRequested) -> None:
        await self.execute_command(self.current_command)

    @on(NewsWorkspace.OpenRequested)
    async def news_open_requested(self, event: NewsWorkspace.OpenRequested) -> None:
        link = event.item.link.strip()
        if not link.lower().startswith(("https://", "http://")):
            self.notify("This story has no external source link", severity="warning")
            return
        opened = await asyncio.to_thread(webbrowser.open, link, 2)
        if not opened:
            self.notify("Windows could not open the source link", severity="warning")

    @on(OptionsWorkspace.FunctionRequested)
    async def options_function_requested(self, event: OptionsWorkspace.FunctionRequested) -> None:
        suffix = " ".join(value for value in event.args if value)
        command = f"{event.function} {event.symbol}"
        if suffix:
            command = f"{command} {suffix}"
        await self.execute_command(parse_command(command))

    @on(OptionsWorkspace.PopOutRequested)
    def options_popout_requested(self, event: OptionsWorkspace.PopOutRequested) -> None:
        try:
            process = launch_volatility_surface(event.symbol)
        except ChartRuntimeError as exc:
            self.notify(str(exc), severity="error")
            return
        self.set_timer(
            2.0,
            lambda: self._report_chart_launch_failure(process, f"OVDV {event.symbol}"),
        )
        self.notify(f"Interactive OVDV opened for {event.symbol}", title="POP OUT")

    def _report_chart_launch_failure(self, process, label: str) -> None:
        exit_code = process.poll()
        if exit_code is not None:
            self.notify(
                f"{label} could not start (exit code {exit_code}).",
                title="CHART RUNTIME",
                severity="error",
            )

    async def _show_instrument(self, command: ParsedCommand) -> None:
        symbol = command.target or "AAPL"
        if is_fx_pair(symbol):
            await self._show_fx(ParsedCommand(CommandAction.FX, command.args, command.raw))
            return
        registered = self.registry.get(symbol)
        if registered is not None and registered.instrument_type in {
            "GOVT_BENCHMARK",
            "CREDIT_BENCHMARK",
            "CORPORATE_BOND",
        }:
            await self._show_bond(ParsedCommand(CommandAction.BOND, command.args, command.raw))
            return
        period = _command_period(command)
        instrument = infer_instrument(symbol)
        quote_task = asyncio.create_task(self.market_service.quote(symbol))
        history_task = asyncio.create_task(self.market_service.history(symbol, period))
        news_task = asyncio.create_task(self.news_service.headlines(symbol, limit=8))
        fundamentals_task = (
            asyncio.create_task(self.market_service.equity_fundamentals(symbol))
            if instrument.asset_class == AssetClass.EQUITY
            else None
        )
        profile_task = asyncio.create_task(self.research_service.company_profile(symbol)) if fundamentals_task else None
        analyst_task = asyncio.create_task(self.research_service.analyst_consensus(symbol)) if fundamentals_task else None
        estimates_task = asyncio.create_task(self.research_service.estimates(symbol)) if fundamentals_task else None
        quote, history, news = await asyncio.gather(quote_task, history_task, news_task)
        fundamentals = await fundamentals_task if fundamentals_task is not None else None
        profile = await profile_task if profile_task is not None else None
        analyst = await analyst_task if analyst_task is not None else None
        estimates = await estimates_task if estimates_task is not None else None
        self._set_instrument_header(quote)
        self.query_one("#main", Static).update(
            render_equity(
                quote,
                fundamentals,
                history,
                news,
                profile,
                analyst,
                estimates,
                active_function="DES",
            )
        )
        self.query_one("#context", Static).update(render_instrument_context(quote, history, news))

    async def _handle_watch(self, command: ParsedCommand) -> None:
        if not command.args:
            quotes = await self.market_service.watchlist_quotes()
            self.query_one("#main", Static).update(render_watchlist(quotes))
            return
        verb = command.args[0]
        symbol = command.args[1] if len(command.args) > 1 else ""
        if verb == "ADD" and symbol:
            self.market_service.watchlists.add(symbol)
            await self.refresh_sidebars()
            self.query_one("#main", Static).update(render_message("WATCHLIST", f"Added {symbol.upper()}"))
            return
        if verb == "REMOVE" and symbol:
            self.market_service.watchlists.remove(symbol)
            await self.refresh_sidebars()
            self.query_one("#main", Static).update(render_message("WATCHLIST", f"Removed {symbol.upper()}"))
            return
        quotes = await self.market_service.watchlist_quotes(verb)
        self.query_one("#main", Static).update(render_watchlist(quotes))

    async def _show_search(self, command: ParsedCommand) -> None:
        query = " ".join(command.args)
        results = await self.market_service.search(query)
        self.query_one("#main", Static).update(render_search(query, results))

    def _current_equity_symbol(self) -> str:
        if self.current_command.target and self.current_command.action in {
            CommandAction.EQUITY,
            CommandAction.INSTRUMENT,
            CommandAction.FINANCIAL_ANALYSIS,
            CommandAction.RELATIVE_VALUATION,
            CommandAction.COMP,
            CommandAction.ESTIMATES,
            CommandAction.ANALYST,
            CommandAction.DIVIDENDS,
            CommandAction.EVENTS,
            CommandAction.INCOME_STATEMENT,
            CommandAction.BALANCE_SHEET,
            CommandAction.CASH_FLOW,
            CommandAction.FILINGS,
            CommandAction.TEN_K,
            CommandAction.TEN_Q,
            CommandAction.EXPORT,
            CommandAction.CHART,
            CommandAction.RISK,
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        }:
            return self.current_command.target
        if self._loaded_symbol:
            instrument = self.registry.resolve(self._loaded_symbol)
            if instrument.asset_class == AssetClass.EQUITY:
                return instrument.symbol
        return "AAPL"

    def _apply_loaded_instrument(self, command: ParsedCommand) -> ParsedCommand:
        if command.args or not self._loaded_symbol:
            return command
        contextual_actions = {
            CommandAction.INSTRUMENT,
            CommandAction.EQUITY,
            CommandAction.INCOME_STATEMENT,
            CommandAction.BALANCE_SHEET,
            CommandAction.CASH_FLOW,
            CommandAction.FINANCIAL_ANALYSIS,
            CommandAction.RELATIVE_VALUATION,
            CommandAction.COMP,
            CommandAction.ESTIMATES,
            CommandAction.ANALYST,
            CommandAction.DIVIDENDS,
            CommandAction.EVENTS,
            CommandAction.FILINGS,
            CommandAction.TEN_K,
            CommandAction.TEN_Q,
            CommandAction.EXPORT,
            CommandAction.CHART,
            CommandAction.RISK,
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        }
        if command.action == CommandAction.NEWS and command.raw.strip().upper().split()[:1] == ["CN"]:
            return ParsedCommand(command.action, (self._loaded_symbol,), command.raw)
        if command.action not in contextual_actions:
            return command
        return ParsedCommand(command.action, (self._loaded_symbol,), command.raw)

    def _instrument_header_spec(
        self, command: ParsedCommand
    ) -> tuple[str, str, str | None, str | None] | None:
        action = command.action
        labels = {
            CommandAction.EQUITY: "DES",
            CommandAction.INSTRUMENT: "DES",
            CommandAction.INDEX: "DES",
            CommandAction.COMMODITY: "DES",
            CommandAction.FX: "FX",
            CommandAction.FWD: "FWD",
            CommandAction.GOVERNMENT: "GOVT",
            CommandAction.CORPORATE: "CORP",
            CommandAction.BOND: "BOND",
            CommandAction.INCOME_STATEMENT: "IS",
            CommandAction.BALANCE_SHEET: "BS",
            CommandAction.CASH_FLOW: "CF",
            CommandAction.FILINGS: "FILINGS",
            CommandAction.TEN_K: "10K",
            CommandAction.TEN_Q: "10Q",
            CommandAction.EXPORT: "XLS",
            CommandAction.FINANCIAL_ANALYSIS: "FA",
            CommandAction.RELATIVE_VALUATION: "RV",
            CommandAction.COMP: "RV",
            CommandAction.ESTIMATES: "EE",
            CommandAction.ANALYST: "ANR",
            CommandAction.DIVIDENDS: "DVD",
            CommandAction.EVENTS: "EVT",
            CommandAction.CHART: "GP",
            CommandAction.RISK: "RISK",
            CommandAction.NEWS: "NEWS",
            CommandAction.OPTIONS: "OMON",
            CommandAction.OPTION_VALUATION: "OVME",
            CommandAction.VOL: "OVDV",
        }
        if action == CommandAction.FX and not command.args:
            return None
        if action == CommandAction.EVENTS and not command.target:
            return None
        if action == CommandAction.NEWS:
            target = command.target
            if target is None or not self._looks_like_news_symbol(command):
                return None
            return labels[action], target, None, None
        if action in {CommandAction.GOVERNMENT, CommandAction.CORPORATE, CommandAction.BOND}:
            target = command.target
            instrument = self.registry.get(target) if target else None
            if instrument is None or instrument.instrument_type not in {
                "GOVT_BENCHMARK",
                "CREDIT_BENCHMARK",
                "CORPORATE_BOND",
            }:
                return None
            return labels[action], instrument.symbol, None, None
        if action not in labels:
            return None

        symbol = command.target or ("EURUSD" if action == CommandAction.FWD else "AAPL")
        if action in {
            CommandAction.EQUITY,
            CommandAction.INSTRUMENT,
            CommandAction.INDEX,
            CommandAction.COMMODITY,
            CommandAction.FX,
            CommandAction.FWD,
            CommandAction.CHART,
            CommandAction.OPTIONS,
            CommandAction.OPTION_VALUATION,
            CommandAction.VOL,
        }:
            if action in {CommandAction.OPTIONS, CommandAction.OPTION_VALUATION, CommandAction.VOL}:
                return labels[action], symbol, None, None
            period = "1Y" if action == CommandAction.FWD else _command_period(command)
            interval_arg = command.args[2] if action == CommandAction.CHART and len(command.args) > 2 else None
            interval = normalize_history_interval(period, interval_arg)
            return labels[action], symbol, period, interval
        return labels[action], symbol, None, None

    def _looks_like_news_symbol(self, command: ParsedCommand) -> bool:
        if len(command.args) != 1:
            return False
        target = command.args[0]
        if target == self._loaded_symbol or self.registry.get(target) is not None or is_fx_pair(target):
            return True
        topics = {
            "TOP",
            "FED",
            "ECB",
            "BOE",
            "BOJ",
            "MACRO",
            "MARKET",
            "MARKETS",
            "ECONOMY",
            "COMPANIES",
            "TECH",
            "POLITICS",
            "US",
            "EU",
            "UK",
            "CHINA",
        }
        return target not in topics and ("." in target or target.isalnum() and len(target) <= 5)

    def _set_instrument_header(self, quote: Quote) -> None:
        self.query_one("#instrument-strip", InstrumentStrip).set_quote(quote)
        self._active_quote = quote
        if self.current_command.action != CommandAction.CHART:
            self._start_active_stream(quote)

    def _start_active_stream(self, quote: Quote) -> None:
        self._stop_active_stream()
        if self._headless_chart_fallback() or quote.asset_class.upper() != str(AssetClass.EQUITY):
            return
        api_key = setting("FINNHUB_KEY")
        if not api_key:
            return

        def on_trade(tick: TradeTick) -> None:
            try:
                self.call_from_thread(self._queue_active_tick, tick)
            except RuntimeError:
                return

        def on_status(_status: str) -> None:
            return

        self._active_stream = FinnhubThreadStream(api_key, quote.symbol, on_trade, on_status)
        self._active_stream.start()

    def _stop_active_stream(self) -> None:
        stream = self._active_stream
        self._active_stream = None
        if stream is not None:
            stream.stop()
        self._active_ticks.clear()

    def _queue_active_tick(self, tick: TradeTick) -> None:
        if self._active_quote is not None and tick.symbol.upper() == self._active_quote.symbol.upper():
            self._active_ticks.append(tick)

    def _flush_active_ticks(self) -> None:
        quote = self._active_quote
        if quote is None or not self._active_ticks:
            return
        ticks, self._active_ticks = self._active_ticks, []
        matching = [tick for tick in ticks if tick.symbol.upper() == quote.symbol.upper()]
        if not matching:
            return
        latest = max(matching, key=lambda tick: tick.timestamp_ms)
        quote.price = latest.price
        quote.day_high = max(value for value in (quote.day_high, latest.price) if value is not None)
        quote.day_low = min(value for value in (quote.day_low, latest.price) if value is not None)
        if quote.previous_close:
            quote.change = latest.price - quote.previous_close
            quote.change_percent = quote.change / quote.previous_close * 100.0
        quote.provider = "Finnhub WebSocket"
        quote.quality = DataQuality.REALTIME
        quote.timestamp = datetime.fromtimestamp(latest.timestamp_ms / 1000.0, timezone.utc)
        self.query_one("#instrument-strip", InstrumentStrip).set_quote(quote)

    async def _auto_refresh_visible_market_data(self) -> None:
        if self._auto_refreshing:
            return
        self._auto_refreshing = True
        try:
            await self.refresh_sidebars()
            if self.current_command.action not in {
                CommandAction.SOCIAL,
                CommandAction.NEWS,
                CommandAction.OPTIONS,
                CommandAction.OPTION_VALUATION,
                CommandAction.VOL,
                CommandAction.CHART,
                CommandAction.EXPORT,
            }:
                await self.execute_command(self.current_command, record_history=False)
        finally:
            self._auto_refreshing = False


def _forward_rate_map(curve) -> dict[str, float]:
    by_tenor = {point.tenor: point.yield_pct / 100.0 for point in curve.points}
    one_month = by_tenor.get("1M", next(iter(by_tenor.values()), 0.03))
    return {
        "ON": one_month,
        "TN": one_month,
        "1W": one_month,
        "1M": by_tenor.get("1M", one_month),
        "3M": by_tenor.get("3M", one_month),
        "6M": by_tenor.get("6M", one_month),
        "9M": by_tenor.get("1Y", by_tenor.get("6M", one_month)),
        "1Y": by_tenor.get("1Y", one_month),
        "2Y": by_tenor.get("2Y", by_tenor.get("1Y", one_month)),
    }


def _normalize_curve_currency(value: str) -> str:
    normalized = value.upper()
    mapping = {
        "US": "USD",
        "USA": "USD",
        "USD": "USD",
        "EU": "EUR",
        "EZ": "EUR",
        "EUR": "EUR",
        "EURO": "EUR",
    }
    return mapping.get(normalized, normalized)


def _normalize_govie_country(value: str) -> str:
    normalized = value.upper()
    mapping = {
        "USA": "US",
        "UNITEDSTATES": "US",
        "GERMANY": "DE",
        "GER": "DE",
        "UK": "GB",
        "UNITEDKINGDOM": "GB",
        "JAPAN": "JP",
        "FRANCE": "FR",
        "ITALY": "IT",
        "SPAIN": "ES",
    }
    return mapping.get(normalized.replace(" ", ""), normalized)


def _bond_price(args: tuple[str, ...]) -> float | None:
    if not args:
        return None
    raw = args[1] if args[0].upper() == "PRICE" and len(args) > 1 else args[0]
    value = float(raw)
    if value <= 0:
        raise ValueError("clean price must be positive")
    return value


def _command_period(command: ParsedCommand) -> str:
    return normalize_history_period(command.args[1] if len(command.args) > 1 else None)
