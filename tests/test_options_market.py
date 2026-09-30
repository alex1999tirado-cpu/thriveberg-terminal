from __future__ import annotations

import asyncio
import io
from datetime import date, datetime, timedelta, timezone

from ajax_terminal.analytics.options import black_scholes_price, implied_volatility
from ajax_terminal.app import AjaxTerminalApp
from ajax_terminal.models.options import OptionChain, OptionContract
from ajax_terminal.models.quote import Curve, CurvePoint, DataQuality, Quote
from ajax_terminal.providers.mock import MockMacroProvider, MockMarketProvider, MockNewsProvider
from ajax_terminal.providers.yahoo_options import normalize_yahoo_option_chain
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.options_service import OptionsService, resolve_option_underlying_symbol
from ajax_terminal.storage.cache import SQLiteCache, WatchlistStore
from ajax_terminal.ui.commands import parse_command
from ajax_terminal.ui.options_chart import build_volatility_image
from ajax_terminal.ui.widgets.options import OptionsWorkspace
from rich.console import Console
from textual import events


class StubMarketService:
    def __init__(self, cache: SQLiteCache) -> None:
        self.cache = cache

    async def curve(self, currency: str, *, allow_mock: bool = False) -> Curve:
        return Curve(
            currency,
            f"{currency} TEST CURVE",
            [CurvePoint("1M", 1 / 12, 4.0), CurvePoint("1Y", 1.0, 4.0)],
            "TEST CURVE",
            DataQuality.DELAYED,
        )


class QuoteFallbackMarketService(StubMarketService):
    async def quote(self, symbol: str, *, allow_mock: bool = False) -> Quote:
        return Quote(
            symbol=symbol,
            name="Test Equity",
            price=100.0,
            currency="USD",
            provider="REAL TEST QUOTE",
            quality=DataQuality.DELAYED,
        )


class ModelOptionsProvider:
    name = "MODEL TEST PROVIDER"

    def __init__(self) -> None:
        self.expirations = [date.today() + timedelta(days=days) for days in (30, 90, 180)]

    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        selected = expiry or self.expirations[0]
        time_years = (selected - date.today()).days / 365.0
        calls: list[OptionContract] = []
        puts: list[OptionContract] = []
        for strike in (80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0):
            volatility = 0.20 + ((strike / 100.0) - 1.0) ** 2
            for option_type, destination in (("call", calls), ("put", puts)):
                premium = black_scholes_price(option_type, 100.0, strike, 0.04, volatility, time_years)
                destination.append(
                    OptionContract(
                        contract_symbol=f"TEST-{selected}-{option_type}-{strike:g}",
                        option_type=option_type,
                        strike=strike,
                        expiry=selected,
                        bid=premium,
                        ask=premium,
                        last=premium,
                        volume=100,
                        open_interest=1000,
                        currency="USD",
                    )
                )
        return OptionChain(
            symbol=symbol,
            name="Test Equity",
            spot=100.0,
            currency="USD",
            expirations=self.expirations,
            selected_expiry=selected,
            calls=calls,
            puts=puts,
            provider=self.name,
            quality=DataQuality.DELAYED,
        )


def test_corporate_bond_selection_resolves_to_issuer_equity_for_options(tmp_path) -> None:
    async def run() -> None:
        cache = SQLiteCache(tmp_path / "options-underlying.sqlite3")
        service = OptionsService(StubMarketService(cache), ModelOptionsProvider(), cache)

        chain = await service.chain("AAPL44")

        assert resolve_option_underlying_symbol("AAPL44") == "AAPL"
        assert chain.symbol == "AAPL"
        assert chain.calls and chain.puts

    asyncio.run(run())


def test_non_optionable_registered_security_has_actionable_error(tmp_path) -> None:
    async def run() -> None:
        cache = SQLiteCache(tmp_path / "options-invalid-underlying.sqlite3")
        service = OptionsService(StubMarketService(cache), ModelOptionsProvider(), cache)

        try:
            await service.chain("US10Y")
        except ValueError as exc:
            assert "require an optionable equity" in str(exc)
        else:
            raise AssertionError("Expected a non-optionable security error")

    asyncio.run(run())


class MissingSpotOptionsProvider(ModelOptionsProvider):
    async def option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        chain = await super().option_chain(symbol, expiry)
        chain.spot = None
        chain.currency = ""
        return chain


def test_yahoo_option_chain_normalization() -> None:
    expiry = int(datetime(2030, 1, 18, tzinfo=timezone.utc).timestamp())
    payload = {
        "expirationDates": [expiry],
        "quote": {
            "regularMarketPrice": 101.25,
            "regularMarketChange": 1.5,
            "regularMarketChangePercent": 1.503,
            "regularMarketTime": expiry - 1000,
            "currency": "USD",
            "longName": "Example Corp",
            "trailingAnnualDividendYield": 0.012,
            "marketState": "REGULAR",
        },
        "options": [
            {
                "expirationDate": expiry,
                "calls": [
                    {
                        "contractSymbol": "EXAMPLE",
                        "strike": 100,
                        "expiration": expiry,
                        "bid": 4.8,
                        "ask": 5.0,
                        "lastPrice": 4.9,
                        "volume": 50,
                        "openInterest": 900,
                        "impliedVolatility": 0.25,
                    }
                ],
                "puts": [],
            }
        ],
    }

    chain = normalize_yahoo_option_chain("EXM", payload)

    assert chain.spot == 101.25
    assert chain.selected_expiry == date(2030, 1, 18)
    assert chain.dividend_yield == 0.012
    assert chain.calls[0].market_price == 4.9
    assert chain.calls[0].vendor_implied_volatility == 0.25


def test_implied_volatility_rejects_arbitrage_violation() -> None:
    try:
        implied_volatility("call", 150.0, 100.0, 100.0, 0.0, 1.0)
    except ValueError as exc:
        assert "arbitrage bounds" in str(exc)
    else:
        raise AssertionError("Expected an arbitrage-bound validation error")


def test_surface_uses_real_contract_mids_and_renders(tmp_path) -> None:
    async def run() -> None:
        cache = SQLiteCache(tmp_path / "options.sqlite3")
        provider = ModelOptionsProvider()
        service = OptionsService(StubMarketService(cache), provider, cache)

        chain, context = await service.chain_with_context("TEST")
        assert chain.calls[3].calculated_implied_volatility is not None
        assert abs((chain.calls[3].calculated_implied_volatility or 0) - 0.20) < 1e-6
        assert context.rate_source.startswith("TEST CURVE")
        assert context.rate_available

        surface = await service.volatility_surface("TEST")
        assert len(surface.slices) == 3
        assert abs((surface.slices[0].grid[1.0] or 0) - 0.20) < 1e-6
        smile = build_volatility_image(surface, "SMILE")
        surface_image = build_volatility_image(surface, "SURFACE")
        term_image = build_volatility_image(surface, "TERM")
        rotated_image = build_volatility_image(surface, "SURFACE", elevation=40, azimuth=20, zoom=1.4)
        assert smile.width > 800 and smile.height > 400
        assert surface_image.width > 800 and surface_image.height > 400
        assert term_image.width > 800 and term_image.height > 400
        assert surface_image.tobytes() != rotated_image.tobytes()

    asyncio.run(run())


def test_surface_recovers_missing_provider_spot_from_real_quote(tmp_path) -> None:
    async def run() -> None:
        cache = SQLiteCache(tmp_path / "options-spot.sqlite3")
        service = OptionsService(
            QuoteFallbackMarketService(cache),
            MissingSpotOptionsProvider(),
            cache,
        )

        surface = await service.volatility_surface("TEST")

        assert surface.spot == 100.0
        assert surface.currency == "USD"
        assert len(surface.slices) == 3

    asyncio.run(run())


def test_options_workspace_commands_render_headless(tmp_path) -> None:
    async def run() -> None:
        database = tmp_path / "options-ui.sqlite3"
        cache = SQLiteCache(database)
        market_service = MarketService(
            cache=cache,
            watchlists=WatchlistStore(database),
            market_providers=[],
        )
        options_service = OptionsService(StubMarketService(cache), ModelOptionsProvider(), cache)
        app = AjaxTerminalApp(market_service=market_service, options_service=options_service)
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]
        expiry = ModelOptionsProvider().expirations[0]

        async with app.run_test(size=(180, 48)) as pilot:
            await app.execute_command(parse_command("OMON TEST"))
            await pilot.pause()
            workspace = app.query_one("#options-screen", OptionsWorkspace)
            assert workspace.display
            assert workspace.mode == "OMON"
            assert app.query_one("#options-chain-table").row_count == 24
            assert "TEST Equity" in str(app.query_one("#instrument-function").content)
            assert "OPTION MONITOR" in str(app.query_one("#instrument-function").content)
            assert "TEST EQUITY" in str(app.query_one("#options-market-line").content)
            assert app.query_one("#options-chain-controls").region.bottom == app.query_one("#options-chain-summary").region.y
            assert app.query_one("#options-chain-summary").region.bottom == app.query_one("#options-chain-body").region.y
            assert app.query_one("#options-chain-body").region.bottom == app.query_one("#options-chain-footer").region.y
            assert app.query_one("#options-chain-analysis").region.x == app.query_one("#options-chain-table").region.right
            assert not app.query_one("#sidebar").display
            assert len(workspace.query("#options-function-row")) == 0

            await app.execute_command(parse_command(f"OVME TEST C 100 {expiry.isoformat()}"))
            await pilot.pause()
            assert workspace.mode == "OVME"
            console = Console(width=120, record=True, file=io.StringIO())
            console.print(app.query_one("#options-result-grid").content)
            assert "PRICE (SHARE)" in console.export_text()
            assert app.query_one("#option-input-strike").value == "100.0000"
            assert app.query_one("#options-result-grid").region.bottom <= app.query_one("#options-pricer-body").region.bottom

            await app.execute_command(parse_command("OVDV TEST"))
            await pilot.pause()
            assert workspace.mode == "OVDV"
            assert workspace.surface is not None and len(workspace.surface.slices) == 3
            assert len(workspace.query("#options-function-row")) == 0
            assert len(workspace.query("#options-header")) == 0
            assert len(workspace.query("#options-footer")) == 0
            assert app.query_one("#options-vol-image").image is not None
            assert app.query_one("#options-vol-parameters").region.bottom == app.query_one("#options-vol-image").region.y
            assert not app.query_one("#main-scroll").display
            assert workspace.vol_mode == "SURFACE"
            await pilot.click("#options-vol-term-next")
            assert workspace.surface_slice_index == 1

            initial_azimuth = workspace.surface_azimuth
            workspace.focus()
            await pilot.press("right")
            await pilot.pause()
            assert workspace.surface_azimuth == initial_azimuth + 8.0
            assert "DRAG ROTATE" in str(app.query_one("#options-vol-method").content)
            assert await pilot.mouse_down("#options-vol-image", offset=(20, 8))
            dragged_azimuth = workspace.surface_azimuth
            workspace.on_mouse_move(
                events.MouseMove(workspace, 20, 8, 3, -2, 1, False, False, False)
            )
            await pilot.mouse_up("#options-vol-image", offset=(23, 6))
            assert workspace.surface_azimuth != dragged_azimuth
            assert not workspace._surface_dragging
            await pilot.click("#options-vol-reset")
            assert workspace.surface_azimuth == -48.0
            assert workspace.surface_elevation == 14.0

            await pilot.click("#options-vol-skew")
            await pilot.pause()
            assert workspace.vol_mode == "SKEW"
            tracked = workspace.skew_tracked_moneyness
            assert await pilot.click("#options-vol-image", offset=(20, 8))
            assert workspace.skew_tracked_moneyness != tracked

            await pilot.click("#options-vol-term")
            await pilot.pause()
            assert workspace.vol_mode == "TERM"

    asyncio.run(run())


def test_options_company_name_resolves_to_provider_ticker(tmp_path) -> None:
    async def run() -> None:
        database = tmp_path / "options-alias.sqlite3"
        cache = SQLiteCache(database)
        market_service = MarketService(
            cache=cache,
            watchlists=WatchlistStore(database),
            market_providers=[],
        )

        async def search(query: str) -> list[tuple[str, str, str]]:
            assert query == "APPLE"
            return [("AAPL", "Apple Inc.", "EQUITY")]

        market_service.search = search  # type: ignore[method-assign]
        options_service = OptionsService(StubMarketService(cache), ModelOptionsProvider(), cache)
        app = AjaxTerminalApp(market_service=market_service, options_service=options_service)
        app.news_service.providers = [MockNewsProvider()]
        app.macro_service.providers = [MockMacroProvider()]

        async with app.run_test(size=(180, 48)) as pilot:
            await app.execute_command(parse_command("OMON APPLE"))
            await pilot.pause()
            workspace = app.query_one("#options-screen", OptionsWorkspace)
            assert workspace.symbol == "AAPL"
            assert app.current_command.target == "AAPL"
            assert "AAPL Equity" in str(app.query_one("#instrument-function").content)

    asyncio.run(run())
