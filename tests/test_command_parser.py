from __future__ import annotations

from ajax_terminal.ui.commands.parser import CommandAction, parse_command


def test_fx_pair_shortcut_routes_to_fx() -> None:
    parsed = parse_command("eurusd")

    assert parsed.action == CommandAction.FX
    assert parsed.args == ("EURUSD",)


def test_colon_alias_routes_to_fx() -> None:
    parsed = parse_command("FX:EURUSD")

    assert parsed.action == CommandAction.FX
    assert parsed.target == "EURUSD"


def test_rates_alias_routes_to_curve() -> None:
    parsed = parse_command("rates usd")

    assert parsed.action == CommandAction.CURVE
    assert parsed.target == "USD"

    country = parse_command("rates es")
    assert country.action == CommandAction.GOVERNMENT
    assert country.target == "ES"


def test_macro_map_commands_and_aliases() -> None:
    assert parse_command("MAP").action == CommandAction.MAP
    assert parse_command("WORLD").action == CommandAction.MAP
    assert parse_command("WORLDMAP CPI").args == ("CPI",)
    assert parse_command("ECONMAP SPAIN").args == ("SPAIN",)


def test_unknown_text_routes_to_search() -> None:
    parsed = parse_command("apple")

    assert parsed.action == CommandAction.SEARCH
    assert parsed.target == "APPLE"


def test_watch_command_preserves_args() -> None:
    parsed = parse_command("watch add aapl")

    assert parsed.action == CommandAction.WATCH
    assert parsed.args == ("ADD", "AAPL")


def test_description_command_routes_to_instrument_with_period() -> None:
    parsed = parse_command("des nvda 5y")

    assert parsed.action == CommandAction.INSTRUMENT
    assert parsed.args == ("NVDA", "5Y")


def test_registry_and_wei_commands() -> None:
    assert parse_command("wei").action == CommandAction.WEI
    assert parse_command("fxc").action == CommandAction.FX
    instruments = parse_command("instruments rates")
    assert instruments.action == CommandAction.INSTRUMENTS
    assert instruments.target == "RATES"


def test_fixed_income_commands_route_to_dedicated_screens() -> None:
    assert parse_command("govt us").action == CommandAction.GOVERNMENT
    assert parse_command("btmm us").action == CommandAction.GOVERNMENT
    assert parse_command("wb").action == CommandAction.GOVERNMENT
    assert parse_command("govies de").action == CommandAction.GOVERNMENT
    assert parse_command("corp aapl").action == CommandAction.CORPORATE
    assert parse_command("credit uscorpig").action == CommandAction.CORPORATE
    bond = parse_command("bond aapl44 price 98.50")
    assert bond.action == CommandAction.BOND
    assert bond.args == ("AAPL44", "PRICE", "98.50")


def test_financial_statement_commands() -> None:
    assert parse_command("is san.mc").action == CommandAction.INCOME_STATEMENT
    assert parse_command("bs aapl").action == CommandAction.BALANCE_SHEET
    assert parse_command("cf msft").action == CommandAction.CASH_FLOW


def test_filings_and_excel_commands() -> None:
    assert parse_command("filings aapl").action == CommandAction.FILINGS
    assert parse_command("10-k msft").action == CommandAction.TEN_K
    assert parse_command("10q nvda").action == CommandAction.TEN_Q
    exported = parse_command("xls san.mc")
    assert exported.action == CommandAction.EXPORT
    assert exported.target == "SAN.MC"


def test_chart_command_preserves_range_and_interval() -> None:
    parsed = parse_command("gp eurjpy 5d 15m")

    assert parsed.action == CommandAction.CHART
    assert parsed.args == ("EURJPY", "5D", "15M")


def test_security_can_precede_function_like_a_terminal_workflow() -> None:
    chart = parse_command("aapl gp 5d 15m")
    relative_value = parse_command("kri.at equity rv")

    assert chart.action == CommandAction.CHART
    assert chart.args == ("AAPL", "5D", "15M")
    assert relative_value.action == CommandAction.RELATIVE_VALUATION
    assert relative_value.args == ("KRI.AT",)


def test_terminal_function_aliases_map_to_existing_ajax_views() -> None:
    assert parse_command("main").action == CommandAction.HOME
    assert parse_command("watc").action == CommandAction.WATCH
    assert parse_command("aapl cn").action == CommandAction.NEWS
    assert parse_command("aapl hp").action == CommandAction.CHART


def test_options_commands_route_to_bloomberg_style_functions() -> None:
    chain = parse_command("omon aapl 2026-12-18")
    valuation = parse_command("ovme aapl c 350 2026-12-18")
    surface = parse_command("ovdv aapl")

    assert chain.action == CommandAction.OPTIONS
    assert chain.args == ("AAPL", "2026-12-18")
    assert valuation.action == CommandAction.OPTION_VALUATION
    assert valuation.args == ("AAPL", "C", "350", "2026-12-18")
    assert surface.action == CommandAction.VOL


def test_equity_research_commands_preserve_symbols_and_peers() -> None:
    assert parse_command("fa san.mc").args == ("SAN.MC",)
    assert parse_command("ee nvda").action == CommandAction.ESTIMATES
    relative = parse_command("rv aapl msft goog")
    assert relative.action == CommandAction.RELATIVE_VALUATION
    assert relative.args == ("AAPL", "MSFT", "GOOG")


def test_workstation_commands_are_first_class_actions() -> None:
    assert parse_command("flds aapl price").action == CommandAction.DATA_AUDIT
    assert parse_command("aapl flds revenue").args == ("AAPL", "REVENUE")
    assert parse_command("wsp").action == CommandAction.WORKSPACES
    assert parse_command("upd").action == CommandAction.UPDATES
    assert parse_command("port").action == CommandAction.PORTFOLIO
    assert parse_command("alrt").action == CommandAction.ALERTS
