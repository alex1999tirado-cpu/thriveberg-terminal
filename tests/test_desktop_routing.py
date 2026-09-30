from ajax_terminal.desktop_app import resolve_desktop_command


def test_desktop_starts_without_an_implicit_security() -> None:
    home = resolve_desktop_command("")
    chart = resolve_desktop_command("GP")

    assert (home.kind, home.target) == ("home", "")
    assert (chart.kind, chart.target) == ("security-required", "")


def test_desktop_instrument_then_function_workflow() -> None:
    selected = resolve_desktop_command("META", "AAPL")
    assert selected.kind == "select"
    assert selected.target == "META"

    chart = resolve_desktop_command("GP", selected.target)
    assert chart.kind == "price"
    assert chart.target == "META"
    assert chart.period == "1Y"


def test_desktop_security_first_routes_to_native_engines() -> None:
    price = resolve_desktop_command("AAPL GP 5D 15m")
    surface = resolve_desktop_command("NVDA OVDV")
    curve = resolve_desktop_command("CURVE USD")

    assert (price.kind, price.target, price.period, price.interval) == ("price", "AAPL", "5D", "15m")
    assert (surface.kind, surface.target) == ("ovdv", "NVDA")
    assert (curve.kind, curve.target) == ("curve", "USD")


def test_options_route_to_all_three_native_desktop_functions() -> None:
    monitor = resolve_desktop_command("AAPL OMON")
    valuation = resolve_desktop_command("OVME AAPL C 220 2027-01-15")
    surface = resolve_desktop_command("AAPL OVDV")

    assert (monitor.kind, monitor.target) == ("option-monitor", "AAPL")
    assert (valuation.kind, valuation.target) == ("option-valuation", "AAPL")
    assert (surface.kind, surface.target) == ("ovdv", "AAPL")


def test_bond_option_routes_switch_to_the_issuer_equity_underlying() -> None:
    monitor = resolve_desktop_command("OMON", "AAPL44")
    valuation = resolve_desktop_command("AAPL44 OVME")
    surface = resolve_desktop_command("OVDV AAPL44")

    assert (monitor.kind, monitor.target) == ("option-monitor", "AAPL")
    assert (valuation.kind, valuation.target) == ("option-valuation", "AAPL")
    assert (surface.kind, surface.target) == ("ovdv", "AAPL")


def test_risk_routes_to_native_price_analytics() -> None:
    route = resolve_desktop_command("AAPL RISK", "MSFT")

    assert route.kind == "price"
    assert route.target == "AAPL"
    assert route.period == "1Y"
    assert route.interval == "1d"


def test_social_routes_to_internal_workspace() -> None:
    route = resolve_desktop_command("SOCIAL", "AAPL")

    assert route.kind == "social"
    assert route.target == "AAPL"


def test_macro_map_routes_to_native_workspace() -> None:
    route = resolve_desktop_command("MAP CPI SPAIN", "AAPL")

    assert route.kind == "macro-map"
    assert route.raw == "MAP CPI SPAIN"


def test_description_and_financials_route_to_native_workspaces() -> None:
    description = resolve_desktop_command("KRI.AT DES", "AAPL")
    equity = resolve_desktop_command("KRI.AT EQUITY", "AAPL")
    analysis = resolve_desktop_command("KRI.AT FA", "AAPL")
    income = resolve_desktop_command("IS", "KRI.AT")
    balance = resolve_desktop_command("KRI.AT BS", "AAPL")
    cashflow = resolve_desktop_command("CF KRI.AT", "AAPL")
    export = resolve_desktop_command("KRI.AT XLS", "AAPL")

    assert (description.kind, description.target) == ("description", "KRI.AT")
    assert (equity.kind, equity.target) == ("description", "KRI.AT")
    assert (analysis.kind, analysis.target) == ("financial-analysis", "KRI.AT")
    assert (income.kind, income.target) == ("financial-income", "KRI.AT")
    assert (balance.kind, balance.target) == ("financial-balance", "KRI.AT")
    assert (cashflow.kind, cashflow.target) == ("financial-cashflow", "KRI.AT")
    assert (export.kind, export.target) == ("financial-export", "KRI.AT")


def test_financial_refresh_command_preserves_the_security_target() -> None:
    route = resolve_desktop_command("AAPL IS REFRESH", "MSFT")

    assert (route.kind, route.target, route.raw) == (
        "financial-income",
        "AAPL",
        "AAPL IS REFRESH",
    )


def test_equity_research_commands_route_to_native_workspaces() -> None:
    expected = {
        "KRI.AT RV": "relative-valuation",
        "KRI.AT COMP BN.PA": "relative-valuation",
        "KRI.AT EE": "estimates",
        "KRI.AT ANR": "analyst",
        "KRI.AT DVD": "dividends",
        "KRI.AT EVT": "events",
        "KRI.AT FILINGS": "filings",
        "KRI.AT 10K": "filings-10k",
        "KRI.AT 10Q": "filings-10q",
        "EQS MARKETCAP>10B": "screener",
    }

    for command, kind in expected.items():
        route = resolve_desktop_command(command, "AAPL")
        assert route.kind == kind
        if kind != "screener":
            assert route.target == "KRI.AT"


def test_workstation_commands_route_to_native_workspaces() -> None:
    expected = {
        "WATC": "watchlist",
        "PORT": "portfolio",
        "ALRT": "alerts",
        "WSP": "workspaces",
        "UPD": "updates",
        "AAPL FLDS PRICE": "data-audit",
        "EVT ALL 90": "event-calendar",
    }

    for command, kind in expected.items():
        assert resolve_desktop_command(command).kind == kind

    assert resolve_desktop_command("EVT").kind == "event-calendar"
    assert resolve_desktop_command("EVT", "AAPL").kind == "events"
    watchlist = resolve_desktop_command("EVT WATC:TECH%20STOCKS 30 2")
    portfolio = resolve_desktop_command("EVT PORT:RETIREMENT 90 3")
    assert (watchlist.kind, watchlist.target, watchlist.period, watchlist.interval) == (
        "event-calendar", "WATC:TECH%20STOCKS", "30", "2"
    )
    assert (portfolio.kind, portfolio.target, portfolio.period, portfolio.interval) == (
        "event-calendar", "PORT:RETIREMENT", "90", "3"
    )
