from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ajax_terminal.analytics.fixed_income import BondAnalytics
from ajax_terminal.analytics.forwards import ForwardPoint
from ajax_terminal.analytics.fundamentals import cagr, mean, median
from ajax_terminal.analytics.market_stats import calculate_market_statistics, horizon_returns
from ajax_terminal.models.equity import (
    AnalystConsensus,
    CompanyProfile,
    CorporateEvent,
    DividendAnalysis,
    EstimateSet,
    FinancialAnalysis,
    FinancialMetric,
    RelativeValuation,
    ScreenerPage,
)
from ajax_terminal.models.fixed_income import CreditBenchmark
from ajax_terminal.models.filing import FilingCollection
from ajax_terminal.models.instrument import Instrument
from ajax_terminal.models.macro import EconomicEvent, MacroIndicator
from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import (
    Curve,
    DataQuality,
    EquityFundamentals,
    FinancialPeriod,
    FinancialStatements,
    MarketSnapshot,
    PriceHistory,
    Quote,
    StatementType,
)
from ajax_terminal.ui.chart_data import (
    ChartSupplement,
    build_chart_metrics,
    format_quote_value,
    normalized_asset_class,
)
from ajax_terminal.utils.financials import (
    grouped_statement_metrics,
    is_expense_or_outflow_metric,
    ordered_statement_metrics,
)
from ajax_terminal.utils.formatting import fmt_bp, fmt_money, fmt_number, fmt_percent, fmt_timestamp


def render_watchlist(quotes: Iterable[Quote]) -> Panel:
    table = _terminal_table(padding=(0, 0))
    table.add_column("SECURITY", width=9, no_wrap=True)
    table.add_column("LAST", justify="right", width=10, no_wrap=True)
    table.add_column("CHG%", justify="right", width=8, no_wrap=True)
    table.add_column("Q", justify="right", width=4, no_wrap=True)
    rows = list(quotes)
    for quote in rows:
        style = _change_style(quote.change_percent)
        table.add_row(
            _instrument_link(quote.symbol),
            _price(quote),
            f"[{style}]{fmt_percent(quote.change_percent, signed=True)}[/]",
            _quality_label(quote.quality, compact=True),
        )
    if not rows:
        table.add_row("[dim]No watchlist symbols[/]", "", "", "")
    return Panel(table, title="[bright_yellow]WATCHLIST[/]", border_style="grey35", box=box.SIMPLE)


def render_context(news: list[NewsItem], events: list[EconomicEvent]) -> Panel:
    headlines = Table.grid(expand=True)
    headlines.add_column("time", width=7)
    headlines.add_column("headline", ratio=1)
    for item in news[:6]:
        headlines.add_row(item.timestamp.strftime("%H:%M"), f"[white]{item.headline}[/]\n[dim]{item.source} {item.quality}[/]")
    event_table = Table.grid(expand=True)
    event_table.add_column("time", width=7)
    event_table.add_column("event", ratio=1)
    for event in events[:4]:
        when = event.time.strftime("%H:%M") if event.time else "--"
        event_table.add_row(when, f"[yellow]{event.country}[/] {event.event} [dim]{event.consensus}[/]")
    return Panel(Group(_section("HEADLINES"), headlines, _section("MACRO EVENTS"), event_table), title="CONTEXT", border_style="grey35", box=box.SIMPLE)


def render_home(groups: dict[str, list[Quote]], events: list[EconomicEvent], news: list[NewsItem]) -> Panel:
    blocks = [_quote_block(name, quotes) for name, quotes in groups.items()]
    market_rows = [
        _two_columns(blocks[index], blocks[index + 1] if index + 1 < len(blocks) else Text(""))
        for index in range(0, len(blocks), 2)
    ]
    macro = Table.grid(expand=True)
    macro.add_column("macro")
    for event in events[:3]:
        when = event.time.strftime("%H:%M") if event.time else "--"
        macro.add_row(f"[cyan]{when}[/] [yellow]{event.country}[/] {event.event} [dim]{event.consensus}[/]")
    news_table = Table.grid(expand=True)
    news_table.add_column("news")
    for item in news[:4]:
        news_table.add_row(f"[cyan]{item.timestamp:%H:%M}[/] {item.headline} [dim]{item.quality}[/]")
    return Panel(
        Group(
            _title("MARKET MONITOR / MULTI-ASSET"),
            _function_strip(("MARKETS", "WEI", "FXC", "GOVT", "CORP", "ECO", "NEWS"), "MARKETS"),
            *market_rows,
            _subpanel("MACRO", macro),
            _subpanel("NEWS", news_table),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_wei(groups: dict[str, list[MarketSnapshot]]) -> Panel:
    table = _terminal_table(padding=(0, 1))
    table.add_column("REGION", style="bright_yellow", width=11, no_wrap=True)
    table.add_column("INDEX", style="cyan", width=11, no_wrap=True)
    table.add_column("NAME", ratio=1, no_wrap=True)
    table.add_column("LAST", justify="right", width=13, no_wrap=True)
    table.add_column("NET CHG", justify="right", width=12, no_wrap=True)
    table.add_column("CHG %", justify="right", width=10, no_wrap=True)
    table.add_column("YTD %", justify="right", width=9, no_wrap=True)
    table.add_column("STATUS", justify="center", width=8, no_wrap=True)
    table.add_column("DATA", justify="center", width=9, no_wrap=True)
    for region, snapshots in groups.items():
        for index, snapshot in enumerate(snapshots):
            quote = snapshot.quote
            style = _change_style(quote.change_percent)
            ytd_style = _change_style(snapshot.ytd_change_percent)
            table.add_row(
                region if index == 0 else "",
                _instrument_link(quote.symbol),
                quote.name,
                _price(quote),
                f"[{style}]{fmt_number(quote.change, _quote_decimals(quote), na='--')}[/]",
                f"[{style}]{fmt_percent(quote.change_percent, signed=True)}[/]",
                f"[{ytd_style}]{fmt_percent(snapshot.ytd_change_percent, signed=True)}[/]",
                f"[{_status_style(snapshot.market_status)}]{snapshot.market_status}[/]",
                str(quote.quality),
            )
    return Panel(
        Group(
            _title("WEI  WORLD EQUITY INDICES"),
            _function_strip(("WEI", "MARKETS", "EQS", "WATC", "FXC", "GOVT", "NEWS"), "WEI"),
            Text("GLOBAL INDEX MONITOR  |  PRICES REFRESH AUTOMATICALLY  |  QUALITY SHOWN PER ROW", style="dim"),
            table,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_instruments(instruments: list[Instrument], selected_filter: str | None = None) -> Panel:
    table = _terminal_table()
    table.add_column("SYMBOL", style="cyan", width=12)
    table.add_column("NAME", ratio=1)
    table.add_column("CLASS", width=11)
    table.add_column("TYPE", width=18)
    table.add_column("REGION", width=15)
    table.add_column("CCY", width=5)
    table.add_column("PROVIDER SYMBOL", width=16)
    for instrument in instruments:
        table.add_row(
            _instrument_link(instrument.symbol),
            instrument.name,
            str(instrument.asset_class),
            instrument.instrument_type or "--",
            instrument.region or instrument.country or "--",
            instrument.currency or "--",
            instrument.provider_symbol or instrument.source or "--",
        )
    title = "INSTRUMENT REGISTRY" if not selected_filter else f"INSTRUMENT REGISTRY / {selected_filter.upper()}"
    return Panel(
        Group(
            _title(title),
            _function_strip(
                ("INSTRUMENTS", "INDEX", "FX", "GOVT", "CORP", "CMDTY"),
                "INSTRUMENTS",
                commands={
                    "INDEX": "INSTRUMENTS INDEX",
                    "FX": "INSTRUMENTS FX",
                    "GOVT": "INSTRUMENTS RATES",
                    "CORP": "INSTRUMENTS CORP",
                    "CMDTY": "INSTRUMENTS CMDTY",
                },
            ),
            Text(f"{len(instruments)} registered instruments", style="dim"),
            table,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_fx_matrix(quotes: list[Quote], currencies: tuple[str, ...]) -> Panel:
    rates: dict[tuple[str, str], float] = {}
    changes: dict[tuple[str, str], float | None] = {}
    for quote in quotes:
        if quote.price is None or len(quote.symbol) != 6:
            continue
        base, counter = quote.symbol[:3], quote.symbol[3:]
        rates[(base, counter)] = quote.price
        changes[(base, counter)] = quote.change_percent
        if quote.price:
            rates[(counter, base)] = 1.0 / quote.price
            changes[(counter, base)] = -quote.change_percent if quote.change_percent is not None else None

    table = _terminal_table(padding=(0, 0))
    table.add_column("BASE", style="bold bright_yellow", width=5, no_wrap=True)
    for counter in currencies:
        table.add_column(counter, justify="right", width=8, no_wrap=True)
    for base in currencies:
        values: list[str | Text] = []
        for counter in currencies:
            value = 1.0 if base == counter else rates.get((base, counter))
            change = 0.0 if base == counter else changes.get((base, counter))
            decimals = 3 if counter == "JPY" or base == counter else 5
            label = fmt_number(value, decimals)
            values.append(
                Text(label, style=_matrix_style(change))
                if base == counter
                else _instrument_link(f"{base}{counter}", label, _matrix_style(change))
            )
        table.add_row(base, *values)

    quality_counts: dict[str, int] = {}
    for quote in quotes:
        quality_counts[str(quote.quality)] = quality_counts.get(str(quote.quality), 0) + 1
    quality_text = " | ".join(f"{quality}: {count}" for quality, count in quality_counts.items())
    legend = Text.from_markup(
        "[black on #19733a] POSITIVE [/][white on #7a1830] NEGATIVE [/][black on grey70] FLAT / DIAGONAL [/]"
    )
    return Panel(
        Group(
            _title("FXC / G10 FX MATRIX"),
            _function_strip(
                ("FXC", "FX", "FWD", "GP", "NEWS"),
                "FXC",
                commands={
                    "FXC": "FX",
                    "FX": "FX EURUSD",
                    "FWD": "FWD EURUSD",
                    "GP": "GP EURUSD",
                    "NEWS": "NEWS FX",
                },
            ),
            table,
            legend,
            Text(f"45 liquid G10 crosses | {quality_text} | Drill-down: FX EURJPY", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_financial_statements(statements: FinancialStatements) -> Panel:
    names = {
        StatementType.INCOME: "INCOME STATEMENT",
        StatementType.BALANCE_SHEET: "BALANCE SHEET",
        StatementType.CASH_FLOW: "CASH FLOW STATEMENT",
    }
    active_function = {
        StatementType.INCOME: "IS",
        StatementType.BALANCE_SHEET: "BS",
        StatementType.CASH_FLOW: "CF",
    }[statements.statement_type]
    quality_style = "yellow" if statements.quality in {DataQuality.MOCK, DataQuality.CACHED} else "dim"
    return Panel(
        Group(
            _title(f"{statements.name.upper()}  {statements.symbol}  {names[statements.statement_type]}"),
            _equity_command_strip(statements.symbol, active_function),
            Text(
                f"Currency: {statements.currency or '--'} | Provider: {statements.provider} | Quality: {statements.quality}",
                style=quality_style,
            ),
            Text(
                "Source: filed 10-K / 10-Q XBRL | * quarterly cash-flow value derived from reported cumulative totals"
                if "SEC EDGAR" in statements.provider
                else "Provider-normalized statement history",
                style="dim",
            ),
            _section("ANNUAL HISTORY"),
            _statement_table(
                statements.annual,
                statements.statement_type,
                statements.metric_labels,
                statements.metric_order,
                statements.metric_sections,
            ),
            _section("QUARTERLY HISTORY"),
            _statement_table(
                statements.quarterly,
                statements.statement_type,
                statements.metric_labels,
                statements.metric_order,
                statements.metric_sections,
            ),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_filings(collection: FilingCollection, active_function: str = "FILINGS") -> Panel:
    table = _terminal_table()
    table.add_column("FORM", width=8, style="cyan")
    table.add_column("FILED", width=12)
    table.add_column("PERIOD END", width=12)
    table.add_column("ACCESSION", width=22)
    table.add_column("DOCUMENT", width=12)
    table.add_column("DESCRIPTION", ratio=1)
    open_label = "OPEN SEC" if "SEC" in collection.provider.upper() else "OPEN REPORT"
    for filing in collection.filings:
        open_style = Style(
            color="cyan",
            bold=True,
            underline=False,
            meta={"@click": f"app.open_url({filing.document_url!r})"},
        )
        table.add_row(
            filing.form,
            filing.filing_date.isoformat(),
            filing.report_date.isoformat() if filing.report_date else "--",
            filing.accession_number,
            Text(open_label, style=open_style),
            filing.description or filing.primary_document,
        )
    if not collection.filings:
        if collection.portal_url:
            portal_style = Style(
                color="cyan",
                bold=True,
                underline=False,
                meta={"@click": f"app.open_url({collection.portal_url!r})"},
            )
            open_portal: str | Text = Text("OPEN PORTAL", style=portal_style)
        else:
            open_portal = "--"
        table.add_row("--", "--", "--", "--", open_portal, collection.message or "No filings available")
    status_style = "dim" if collection.quality != DataQuality.UNAVAILABLE else "bold yellow"
    return Panel(
        Group(
            _title(f"{active_function}  {collection.company_name.upper()}  {collection.symbol}"),
            _equity_command_strip(collection.symbol, active_function),
            Text(
                f"Official/regulatory reports for {collection.jurisdiction}. "
                "Select OPEN REPORT to view the complete filing.",
                style="dim",
            ),
            table,
            Text(
                f"REGULATORY ID {collection.cik or '--'} | {collection.provider} | {collection.quality} | "
                f"{fmt_timestamp(collection.timestamp)}",
                style=status_style,
            ),
            Text(collection.message, style="yellow") if collection.message else Text(""),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_export_result(symbol: str, path: str, sheets: tuple[str, ...], skipped: tuple[str, ...]) -> Panel:
    exported = " | ".join(sheets) if sheets else "--"
    omitted = " | ".join(skipped) if skipped else "NONE"
    open_style = Style(
        color="cyan",
        bold=True,
        underline=False,
        meta={"@click": f"app.open_export({path!r})"},
    )
    return Panel(
        Group(
            _title(f"XLS  {symbol}  FINANCIAL STATEMENT EXPORT"),
            _equity_command_strip(symbol, "XLS"),
            _metric_table(
                [
                    ("STATUS", "EXPORT COMPLETE"),
                    ("WORKBOOK", path),
                    ("SHEETS", exported),
                    ("OMITTED", omitted),
                ],
                label_width=12,
            ),
            Text(" OPEN WORKBOOK ", style=open_style),
            Text("Only provider-supplied real or cached statements are exported; mock data is excluded.", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_fx(quote: Quote, forwards: list[ForwardPoint], history: PriceHistory) -> Panel:
    snapshot_tenors = {"1M", "3M", "6M", "1Y"}
    snapshot = [point for point in forwards if point.tenor in snapshot_tenors]
    return Panel(
        Group(
            _title(f"{quote.name.upper()}  SPOT MARKET"),
            _function_strip(("FX", "FWD", "GP", "NEWS"), "FX", quote.symbol),
            _quote_snapshot(quote),
            _history_dashboard(history),
            _section("FORWARD SNAPSHOT"),
            _forward_table(snapshot or forwards, detailed=False),
            Text(
                "Forward data unavailable: valid reference curves are not configured; mock values suppressed.",
                style="bold yellow",
            )
            if not forwards
            else Text("Indicative theoretical forwards; not executable dealer prices.", style="dim"),
            _data_line(quote, history),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_fx_forward(
    quote: Quote,
    forwards: list[ForwardPoint],
    history: PriceHistory,
    selected_tenor: str | None = None,
) -> Panel:
    base, counter = quote.symbol[:3], quote.symbol[3:]
    selected = f" / {selected_tenor}" if selected_tenor else ""
    nearest = forwards[0] if forwards else None
    summary = _paired_metric_table(
        [
            ("SPOT", fmt_number(quote.price, 5)),
            ("BASE CCY", base or "--"),
            ("TERMS CCY", counter or "--"),
            ("NEAR TENOR", nearest.tenor if nearest else "--"),
            ("NEAR OUTRIGHT", fmt_number(nearest.outright if nearest else None, 5)),
            ("NEAR POINTS", _signed_number(nearest.points if nearest else None, 5)),
        ],
        label_width=14,
    )
    return Panel(
        Group(
            _title(f"{quote.symbol}  FORWARD MONITOR{selected}"),
            _function_strip(
                ("FX", "FWD", "CURVE", "GP", "NEWS"),
                "FWD",
                quote.symbol,
                commands={"CURVE": f"CURVE {counter}"},
            ),
            _subpanel("FORWARD SUMMARY", summary),
            _section("FORWARD OUTRIGHTS / CARRY LADDER"),
            _forward_table(forwards, detailed=True),
            Text(
                "FORWARD DATA UNAVAILABLE: two valid reference curves are required; mock values suppressed.",
                style="bold yellow",
            )
            if not forwards
            else Text(
                "Indicative theoretical forwards derived from spot and configured reference curves; "
                "not executable dealer prices.",
                style="dim",
            ),
            _data_line(quote, history),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def _forward_table(forwards: list[ForwardPoint], *, detailed: bool) -> Table:
    table = _terminal_table()
    table.add_column("TENOR", style="cyan", width=7, no_wrap=True)
    table.add_column("MATURITY", width=12, no_wrap=True)
    if detailed:
        table.add_column("DAYS", justify="right", width=7, no_wrap=True)
        table.add_column("SPOT", justify="right", width=12, no_wrap=True)
    table.add_column("OUTRIGHT", justify="right", width=12, no_wrap=True)
    table.add_column("POINTS", justify="right", width=12, no_wrap=True)
    if detailed:
        table.add_column("PIPS", justify="right", width=10, no_wrap=True)
    table.add_column("CARRY", justify="right", width=10, no_wrap=True)
    table.add_column("ANN. CARRY", justify="right", width=12, no_wrap=True)
    if detailed:
        table.add_column("PREM/DISC", justify="center", width=10, no_wrap=True)

    for point in forwards:
        style = _change_style(point.points)
        row = [point.tenor, str(point.maturity)]
        if detailed:
            row.extend(
                [
                    str(max(round(point.year_fraction * 365), 1)),
                    fmt_number(point.spot, 5),
                ]
            )
        row.extend(
            [
                fmt_number(point.outright, 5),
                f"[{style}]{_signed_number(point.points, 5)}[/]",
            ]
        )
        if detailed:
            pip_multiplier = 100 if point.pair.endswith("JPY") else 10_000
            row.append(f"[{style}]{_signed_number(point.points * pip_multiplier, 2)}[/]")
        row.extend(
            [
                f"[{style}]{fmt_percent(point.carry * 100, signed=True)}[/]",
                f"[{style}]{fmt_percent(point.annualized_carry * 100, signed=True)}[/]",
            ]
        )
        if detailed:
            state = "PREMIUM" if point.points > 0 else "DISCOUNT" if point.points < 0 else "FLAT"
            row.append(f"[{style}]{state}[/]")
        table.add_row(*row)

    if not forwards:
        column_count = 10 if detailed else 6
        table.add_row("--", "No forward tenors available", *(["--"] * (column_count - 2)))
    return table


def render_curve(curve: Curve) -> Panel:
    table = _terminal_table()
    table.add_column("TENOR", style="cyan", width=8)
    table.add_column("YIELD", justify="right")
    table.add_column("D1", justify="right")
    table.add_column("PREVIOUS", justify="right")
    usable = curve.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
    points = curve.points if usable else []
    for point in points:
        previous = point.yield_pct - point.change_bp / 100.0 if point.change_bp is not None else None
        table.add_row(
            point.tenor,
            fmt_percent(point.yield_pct),
            f"[{_change_style(point.change_bp)}]{fmt_bp(point.change_bp)}[/]",
            fmt_percent(previous),
        )
    if not points:
        table.add_row("--", "NO LIVE CURVE DATA", "--", "--")
    spreads = Table.grid(expand=True)
    spreads.add_column("spread", width=12)
    spreads.add_column("value", ratio=1)
    for name, left, right in [("2s10s", "2Y", "10Y"), ("5s30s", "5Y", "30Y"), ("3m10y", "3M", "10Y")]:
        value = _spread(curve, left, right) if points else None
        spreads.add_row(name, f"[{_change_style(value)}]{fmt_bp(value)}[/]")
    meta = f"Provider: {curve.provider} | {curve.quality} | {fmt_timestamp(curve.timestamp)}"
    if not points:
        availability = Text("NO LIVE CURVE DATA / MOCK VALUES SUPPRESSED", style="bold yellow")
    elif curve.method.startswith("BOOTSTRAP"):
        availability = Text(
            f"{curve.method} / DERIVED, NOT EXECUTABLE MARKET QUOTES",
            style="bold yellow",
        )
    elif curve.method.startswith("PARTIAL"):
        availability = Text(curve.method, style="bold yellow")
    elif curve.method != "OBSERVED":
        availability = Text(curve.method, style="cyan")
    else:
        availability = Text("Reference government curve", style="dim")
    return Panel(
        Group(
            _title(curve.name),
            _function_strip(("CURVE", "GOVT", "BTMM", "GP"), "CURVE", curve.currency),
            availability,
            table,
            _section("SLOPES"),
            spreads,
            Text(meta, style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_government_bonds(
    instruments: list[Instrument],
    quotes: list[Quote],
    label: str = "GLOBAL 10Y",
) -> Panel:
    by_symbol = {quote.symbol: quote for quote in quotes}
    commands = {"GP": "GP US10Y"} if label == "GLOBAL 10Y" else None
    table = _terminal_table()
    table.add_column("COUNTRY", style="yellow", width=8)
    table.add_column("GOVIE", style="cyan", width=9)
    table.add_column("BENCHMARK", ratio=1)
    table.add_column("YIELD", justify="right", width=10)
    table.add_column("D1", justify="right", width=9)
    table.add_column("PREVIOUS", justify="right", width=10)
    table.add_column("SOURCE", width=16)
    table.add_column("DATA", width=11)
    for instrument in instruments:
        quote = by_symbol.get(instrument.symbol)
        usable = quote is not None and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        change_bp = quote.change * 100.0 if usable and quote.change is not None else None
        yield_value: str | Text = fmt_percent(quote.price if usable else None)
        if usable and quote.estimated:
            yield_value = Text(
                f"{yield_value}*",
                style=Style.from_meta({"@click": f"app.open_methodology({quote.symbol!r})"}),
            )
        table.add_row(
            instrument.country or "--",
            _instrument_link(instrument.symbol),
            instrument.name,
            yield_value,
            f"[{_change_style(change_bp)}]{fmt_bp(change_bp)}[/]",
            fmt_percent(quote.previous_close if usable else None),
            quote.provider if usable else "--",
            "ESTIMATED*" if usable and quote.estimated else str(quote.quality) if quote is not None else str(DataQuality.UNAVAILABLE),
        )
    methodology_notes = [
        f"* {quote.symbol}: {quote.methodology}"
        for quote in quotes
        if quote.estimated and quote.methodology
    ]
    return Panel(
        Group(
            _title(f"GOVERNMENT BONDS / {label}"),
            _function_strip(
                ("GOVT", "BTMM", "WB", "CURVE", "GP"),
                "GOVT",
                label,
                commands=commands,
            ),
            Text("Sovereign benchmark yields. Observed public data or explicitly marked estimates only.", style="dim"),
            table,
            *[Text(note, style="dim yellow") for note in methodology_notes],
            Text("Drill-down: GOVT US | GOVT DE | BOND US10Y | GP US10Y", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_corporate_credit(
    benchmarks: list[CreditBenchmark],
    bonds: list[Instrument],
    label: str = "US CREDIT",
) -> Panel:
    simple_label = re.fullmatch(r"[A-Z0-9.^=_/-]{1,32}", label.upper()) is not None
    benchmark_symbol = benchmarks[0].symbol if benchmarks else "USCORPIG"
    bond_symbol = bonds[0].symbol if bonds else ""
    commands = {
        "CORP": f"CORP {label}" if simple_label else "CORP",
        "BOND": f"BOND {bond_symbol}" if bond_symbol else "BOND",
        "GP": f"GP {label}" if simple_label else f"GP {benchmark_symbol}",
        "NEWS": f"NEWS {label}" if simple_label else "NEWS CREDIT",
    }
    credit = _terminal_table()
    credit.add_column("INDEX", style="cyan", width=12)
    credit.add_column("SEGMENT", ratio=1)
    credit.add_column("RATING", width=8)
    credit.add_column("YIELD", justify="right", width=10)
    credit.add_column("D1", justify="right", width=9)
    credit.add_column("OAS", justify="right", width=10)
    credit.add_column("D1 OAS", justify="right", width=9)
    credit.add_column("DATA", width=11)
    for item in benchmarks:
        credit.add_row(
            _instrument_link(item.symbol),
            item.name,
            item.rating or "--",
            fmt_percent(item.effective_yield_pct),
            f"[{_change_style(item.yield_change_bp)}]{fmt_bp(item.yield_change_bp)}[/]",
            fmt_bp(item.oas_bp),
            f"[{_change_style(item.oas_change_bp)}]{fmt_bp(item.oas_change_bp)}[/]",
            str(item.quality),
        )

    directory = _terminal_table()
    directory.add_column("BOND", style="cyan", width=11)
    directory.add_column("ISSUER", ratio=1)
    directory.add_column("COUPON", justify="right", width=9)
    directory.add_column("MATURITY", width=12)
    directory.add_column("CCY", width=5)
    directory.add_column("ISIN", width=14)
    directory.add_column("MARKET", width=12)
    for instrument in bonds:
        directory.add_row(
            _instrument_link(instrument.symbol),
            instrument.issuer or instrument.name,
            fmt_percent(instrument.coupon),
            instrument.maturity.isoformat() if instrument.maturity else "--",
            instrument.currency or "--",
            instrument.identifier or "--",
            "-- / NO FEED",
        )
    if not bonds:
        directory.add_row("--", "No matching registered issues", "--", "--", "--", "--", "--")
    return Panel(
        Group(
            _title(f"CORPORATE BONDS / {label}"),
            _function_strip(
                ("CORP", "BOND", "GP", "NEWS"),
                "CORP",
                label,
                commands=commands,
            ),
            _section("CREDIT MARKET"),
            credit,
            _section("REGISTERED CASH BONDS"),
            directory,
            Text(
                "Index yields/OAS: FRED / ICE BofA, delayed. Cash-bond terms: SEC EDGAR. "
                "Individual live prices require a TRACE-capable feed and remain --.",
                style="dim",
            ),
            Text("Drill-down: CORP AAPL | BOND AAPL44 | BOND AAPL44 PRICE 92.50 | GP USCORPIG", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_credit_benchmark(benchmark: CreditBenchmark, history: PriceHistory) -> Panel:
    snapshot = _paired_metric_table([
        ("EFFECTIVE YIELD", fmt_percent(benchmark.effective_yield_pct)),
        ("OAS", fmt_bp(benchmark.oas_bp)),
        ("D1 YIELD", fmt_bp(benchmark.yield_change_bp)),
        ("D1 OAS", fmt_bp(benchmark.oas_change_bp)),
    ])

    history_table = _terminal_table()
    history_table.add_column("DATE", style="cyan")
    history_table.add_column("EFFECTIVE YIELD", justify="right")
    history_table.add_column("CHANGE", justify="right")
    previous: float | None = None
    rows: list[tuple[str, str, str]] = []
    for bar in history.bars[-10:]:
        change_bp = (bar.close - previous) * 100.0 if previous is not None else None
        rows.append((f"{bar.timestamp:%d %b %Y}", fmt_percent(bar.close), fmt_bp(change_bp)))
        previous = bar.close
    for row in reversed(rows):
        history_table.add_row(*row)
    if not rows:
        history_table.add_row("--", "--", "--")
    return Panel(
        Group(
            _title(f"{benchmark.symbol} / {benchmark.name}"),
            _function_strip(("CORP", "GP", "NEWS"), "CORP", benchmark.symbol),
            snapshot,
            _section(f"YIELD HISTORY [{history.period}]"),
            history_table,
            Text(
                f"Provider: {benchmark.provider} | {benchmark.quality} | {fmt_timestamp(benchmark.timestamp)}",
                style="dim",
            ),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_bond_detail(
    instrument: Instrument,
    analytics: BondAnalytics | None = None,
    clean_price: float | None = None,
    price_source: str = "USER INPUT",
) -> Panel:
    terms = _paired_metric_table([
        ("ISSUER", instrument.issuer or "--"),
        ("COUPON", fmt_percent(instrument.coupon)),
        ("CURRENCY", instrument.currency or "--"),
        ("ISIN / ID", instrument.identifier or "--"),
        ("TYPE", instrument.instrument_type or "BOND"),
        ("MATURITY", instrument.maturity.isoformat() if instrument.maturity else "--"),
        ("SENIORITY", instrument.seniority or "--"),
        ("RATING", instrument.rating or "--"),
    ])

    market = _metric_table([
        ("CLEAN PRICE", fmt_number(clean_price, 4, na="--")),
        ("LIVE PRICE / YIELD", "-- / --"),
        ("MARKET DATA", "UNAVAILABLE / TRACE FEED NOT CONFIGURED"),
    ])

    sections: list[object] = [
        _title(f"BOND DESCRIPTION / {instrument.symbol}"),
        _function_strip(
            ("DES", "BOND", "GP", "CORP", "GOVT", "NEWS"),
            "DES",
            instrument.symbol,
            commands={"GOVT": "GOVT"},
        ),
        terms,
        _section("MARKET"),
        market,
    ]
    if analytics is not None:
        risk = _paired_metric_table([
            ("YTM", fmt_percent(analytics.ytm * 100.0)),
            ("ACCRUED", fmt_number(analytics.accrued_interest, 4)),
            ("MAC DURATION", fmt_number(analytics.macaulay_duration, 4)),
            ("DV01 / 100", fmt_number(analytics.dv01, 6)),
            ("DIRTY PRICE", fmt_number(analytics.dirty_price, 4)),
            ("MOD DURATION", fmt_number(analytics.modified_duration, 4)),
            ("CONVEXITY", fmt_number(analytics.convexity, 4)),
            ("PRICE SOURCE", price_source),
        ])
        sections.extend([_section("YIELD / RISK ANALYTICS"), risk])
    sections.append(Text(f"Reference terms: {instrument.source or '--'}", style="dim"))
    sections.append(Text(f"Value it with: BOND {instrument.symbol} PRICE 98.50", style="dim"))
    return Panel(Group(*sections), border_style="grey35", box=box.SIMPLE)


def render_macro(country: str, indicators: list[MacroIndicator], selected: MacroIndicator | None = None) -> Panel:
    table = _terminal_table()
    table.add_column("INDICATOR", style="cyan", ratio=2)
    table.add_column("VALUE", justify="right")
    table.add_column("PREVIOUS", justify="right")
    table.add_column("CONSENSUS", justify="right")
    table.add_column("QUALITY", width=10)
    for indicator in indicators:
        value = f"{fmt_number(indicator.value, 2)} {indicator.unit}".strip()
        previous = f"{fmt_number(indicator.previous, 2)} {indicator.unit}".strip()
        consensus = f"{fmt_number(indicator.consensus, 2)} {indicator.unit}".strip()
        table.add_row(indicator.name, value, previous, consensus, str(indicator.quality))
    detail = Text("")
    if selected:
        detail = Text(
            f"{selected.name}: latest {selected.value} {selected.unit}, previous {selected.previous} {selected.unit}."
            f" Provider {selected.provider} / {selected.quality}",
            style="yellow",
        )
    return Panel(
        Group(
            _title(f"{country.upper()} MACRO MONITOR"),
            _function_strip(("ECO", "CAL", "NEWS"), "ECO", country.upper()),
            table,
            detail,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_calendar(events: list[EconomicEvent]) -> Panel:
    table = _terminal_table()
    for column in ["TIME", "COUNTRY", "EVENT", "PERIOD", "ACTUAL", "CONSENSUS", "PREVIOUS", "QUALITY"]:
        table.add_column(column, no_wrap=column != "EVENT")
    for event in events:
        table.add_row(
            event.time.strftime("%H:%M") if event.time else "--",
            event.country,
            event.event,
            event.period,
            event.actual,
            event.consensus,
            event.previous,
            str(event.quality),
        )
    return Panel(
        Group(
            _title("ECONOMIC CALENDAR"),
            _function_strip(("CAL", "ECO", "NEWS"), "CAL"),
            table,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_news(items: list[NewsItem], topic: str | None = None) -> Panel:
    table = _terminal_table()
    table.add_column("TIME", width=8)
    table.add_column("SOURCE", width=20)
    table.add_column("HEADLINE", ratio=1)
    table.add_column("TAGS", width=18)
    table.add_column("QUALITY", width=10)
    for item in items:
        table.add_row(item.timestamp.strftime("%H:%M"), item.source, item.headline, ",".join(item.tags), str(item.quality))
    title = "NEWS" if not topic else f"NEWS {topic.upper()}"
    return Panel(
        Group(_title(title), _function_strip(("NEWS", "MARKETS", "ECO"), "NEWS", topic or "TOP"), table),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_news_context(items: list[NewsItem], topic: str | None = None) -> Panel:
    category_counts = Counter(item.category for item in items)
    source_counts = Counter(item.source for item in items)
    quality_counts = Counter(str(item.quality) for item in items)

    categories = Table.grid(expand=True)
    categories.add_column(ratio=1)
    categories.add_column(justify="right", width=5)
    for category, count in category_counts.most_common(7):
        categories.add_row(category, str(count))
    if not category_counts:
        categories.add_row("NO STORIES", "--")

    sources = Table.grid(expand=True)
    sources.add_column(ratio=1)
    sources.add_column(justify="right", width=5)
    for source, count in source_counts.most_common(6):
        sources.add_row(source, str(count))

    quality = Table.grid(expand=True)
    quality.add_column(ratio=1)
    quality.add_column(justify="right", width=5)
    for label, count in quality_counts.items():
        quality.add_row(label, str(count))

    label = (topic or "TOP STORIES").upper()
    return Panel(
        Group(
            _title(f"NEWS MONITOR / {label}"),
            _section("SECTIONS"),
            categories,
            Text(""),
            _section("SOURCES"),
            sources,
            Text(""),
            _section("DATA QUALITY"),
            quality,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_equity(
    quote: Quote,
    fundamentals: EquityFundamentals | None,
    history: PriceHistory,
    news: list[NewsItem],
    profile: CompanyProfile | None = None,
    analyst: AnalystConsensus | None = None,
    estimates: EstimateSet | None = None,
    active_function: str = "DES",
) -> Panel:
    if fundamentals is not None:
        valuation_rows = [
            ("MARKET CAP", fmt_money(fundamentals.market_cap)),
            ("ENTERPRISE VALUE", fmt_money(fundamentals.enterprise_value)),
            ("P/E", fmt_number(fundamentals.pe)),
            ("FORWARD P/E", fmt_number(fundamentals.forward_pe)),
            ("EV / EBITDA", fmt_number(fundamentals.ev_ebitda)),
            ("PRICE / BOOK", fmt_number(fundamentals.price_book)),
            ("DIVIDEND YIELD", fmt_percent(fundamentals.dividend_yield)),
            ("BETA", fmt_number(fundamentals.beta)),
        ]
        financial_rows = [
            ("REVENUE", fmt_money(fundamentals.revenue)),
            ("REVENUE GROWTH", fmt_percent(fundamentals.revenue_growth, signed=True)),
            ("EBITDA", fmt_money(fundamentals.ebitda)),
            ("EBIT", fmt_money(fundamentals.ebit)),
            ("NET INCOME", fmt_money(fundamentals.net_income)),
            ("EPS", fmt_number(fundamentals.eps)),
            ("FREE CASH FLOW", fmt_money(fundamentals.free_cash_flow)),
            ("OPERATING CF", fmt_money(fundamentals.operating_cash_flow)),
        ]
        profitability_rows = [
            ("GROSS MARGIN", fmt_percent(fundamentals.gross_margin)),
            ("OPERATING MARGIN", fmt_percent(fundamentals.operating_margin)),
            ("NET MARGIN", fmt_percent(fundamentals.profit_margin)),
            ("ROE", fmt_percent(fundamentals.roe)),
            ("ROA", fmt_percent(fundamentals.roa)),
            ("ROIC", fmt_percent(fundamentals.roic)),
            ("TOTAL CASH", fmt_money(fundamentals.total_cash)),
            ("NET DEBT", fmt_money(fundamentals.net_debt)),
        ]
    else:
        valuation_rows = [("VALUATION", "Not applicable / unavailable")]
        financial_rows = [("FINANCIALS", "Not applicable / unavailable")]
        profitability_rows = [("FUNDAMENTALS", "Not applicable / unavailable")]
    valuation = _metric_table(valuation_rows)
    financials = _metric_table(financial_rows)
    profitability = _paired_metric_table(profitability_rows)

    headlines = Table.grid(expand=True)
    headlines.add_column("time", width=7)
    headlines.add_column("headline", ratio=1)
    for item in news[:5]:
        headlines.add_row(item.timestamp.strftime("%H:%M"), f"{item.headline} [dim]{item.source} / {item.quality}[/]")
    if not news:
        headlines.add_row("--", "No related headlines available")

    name = profile.name if profile and profile.quality != DataQuality.UNAVAILABLE else fundamentals.name if fundamentals is not None else quote.name
    fundamental_source = (
        f"Fundamentals: {fundamentals.provider} / {fundamentals.quality}"
        if fundamentals is not None
        else "Fundamentals: unavailable for this instrument type"
    )
    return Panel(
        Group(
            _title(f"{name.upper()}  {quote.symbol}"),
            _equity_identity(profile, estimates),
            _instrument_command_strip(quote, active_function),
            _section("MARKET SNAPSHOT"),
            _quote_snapshot(quote),
            _section("FUNDAMENTALS / VALUATION"),
            _three_columns(
                _subpanel("VALUATION", valuation),
                _subpanel("FINANCIALS", financials),
                _subpanel("PROFITABILITY / BALANCE SHEET", profitability),
            ),
            _analyst_summary(analyst),
            _history_dashboard(history),
            _section("RELATED HEADLINES"),
            headlines,
            Text(fundamental_source, style="dim"),
            _data_line(quote, history),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_financial_analysis(analysis: FinancialAnalysis) -> Panel:
    if analysis.quality == DataQuality.UNAVAILABLE:
        return _research_unavailable("FINANCIAL ANALYSIS", analysis.symbol, analysis.message, "FA")
    visible_periods = analysis.periods[:3] + [item for item in analysis.periods if item.startswith("FY")][:4]
    sections: list[object] = [
        _title(f"FA  {analysis.name.upper()}  {analysis.symbol}"),
        _equity_command_strip(analysis.symbol, "FA"),
        Text("A = actual  |  E = consensus estimate  |  N/A = not offered by provider", style="dim"),
    ]
    for category, metrics in analysis.metrics.items():
        if not metrics:
            continue
        periods = visible_periods if category != "VALUATION" else list(dict.fromkeys(item.period for item in metrics))
        table = _terminal_table()
        table.add_column(category, style="cyan", ratio=2)
        for period in periods:
            status = next((item.status for item in metrics if item.period == period), "ACTUAL")
            marker = "E" if status == "ESTIMATE" else "A"
            table.add_column(f"{period} {marker}", justify="right", ratio=1)
        names = list(dict.fromkeys(item.name for item in metrics))
        for name in names:
            values = []
            for period in periods:
                metric = next((item for item in metrics if item.name == name and item.period == period), None)
                values.append(_financial_metric_value(metric))
            table.add_row(name.upper(), *values)
        sections.extend([_section(category), table])
    sections.append(Text(f"{analysis.provider} | {analysis.quality} | {fmt_timestamp(analysis.timestamp)}", style="dim"))
    return Panel(Group(*sections), border_style="grey35", box=box.SIMPLE)


def render_estimates(estimates: EstimateSet) -> Panel:
    if estimates.quality == DataQuality.UNAVAILABLE:
        return _research_unavailable("EARNINGS ESTIMATES", estimates.symbol, "No consensus estimates supplied", "EE")
    table = _terminal_table()
    for label, kwargs in (
        ("METRIC", {"style": "cyan", "width": 12}),
        ("PERIOD", {"width": 11}),
        ("END", {"width": 11}),
        ("CONSENSUS", {"justify": "right"}),
        ("LOW", {"justify": "right"}),
        ("HIGH", {"justify": "right"}),
        ("GROWTH", {"justify": "right"}),
        ("ANALYSTS", {"justify": "right"}),
        ("REV 7D", {"justify": "right"}),
        ("REV 30D", {"justify": "right"}),
    ):
        table.add_column(label, **kwargs)
    for item in estimates.estimates:
        money = item.metric == "Revenue"
        table.add_row(
            item.metric.upper(),
            item.period,
            item.end_date.isoformat() if item.end_date else "--",
            fmt_money(item.average) if money else fmt_number(item.average),
            fmt_money(item.low) if money else fmt_number(item.low),
            fmt_money(item.high) if money else fmt_number(item.high),
            fmt_percent(item.growth_percent, signed=True),
            str(item.analyst_count) if item.analyst_count is not None else "--",
            fmt_percent(item.revision_7d, signed=True),
            fmt_percent(item.revision_30d, signed=True),
        )
    offered = {(item.metric, item.period) for item in estimates.estimates}
    unavailable = [
        f"{metric} {period}"
        for metric in ("EBITDA", "EBIT", "NET INCOME", "FCF")
        for period in ("FY", "FY+1", "FY+2", "FY+3")
        if (metric, period) not in offered
    ]
    earnings_date = estimates.earnings_date.strftime("%d %b %Y") if estimates.earnings_date else "N/A"
    return Panel(
        Group(
            _title(f"EE  {estimates.name.upper()}  {estimates.symbol}"),
            _equity_command_strip(estimates.symbol, "EE"),
            Text(f"NEXT EARNINGS  {earnings_date}  |  CURRENCY {estimates.currency or '--'}", style="yellow"),
            table,
            Text("EBITDA / EBIT / Net income / FCF and FY+2/FY+3: N/A where the public provider supplies no consensus.", style="dim"),
            Text(f"{estimates.provider} | {estimates.quality} | {fmt_timestamp(estimates.timestamp)}", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_analyst(consensus: AnalystConsensus) -> Panel:
    if consensus.quality == DataQuality.UNAVAILABLE:
        return _research_unavailable("ANALYST RECOMMENDATIONS", consensus.symbol, "No analyst consensus supplied", "ANR")
    summary = _paired_metric_table([
        ("RECOMMENDATION", consensus.recommendation or "--"),
        ("SCORE", fmt_number(consensus.recommendation_score)),
        ("ANALYSTS", str(consensus.analyst_count) if consensus.analyst_count is not None else "--"),
        ("CURRENT PRICE", fmt_number(consensus.current_price)),
        ("TARGET LOW", fmt_number(consensus.target_low)),
        ("TARGET MEAN", fmt_number(consensus.target_mean)),
        ("TARGET MEDIAN", fmt_number(consensus.target_median)),
        ("TARGET HIGH", fmt_number(consensus.target_high)),
        ("MEAN UPSIDE", fmt_percent(consensus.upside_percent, signed=True)),
    ])
    distribution = _terminal_table()
    for label in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"):
        distribution.add_column(label, justify="center")
    distribution.add_row(*[
        str(value) if value is not None else "--"
        for value in (consensus.strong_buy, consensus.buy, consensus.hold, consensus.sell, consensus.strong_sell)
    ])
    return Panel(
        Group(
            _title(f"ANR  {consensus.name.upper()}  {consensus.symbol}"),
            _equity_command_strip(consensus.symbol, "ANR"),
            summary,
            _section("RECOMMENDATION DISTRIBUTION"),
            distribution,
            Text("Consensus and targets are provider aggregates, not THRIVEBERG recommendations.", style="dim"),
            Text(f"{consensus.provider} | {consensus.quality} | {fmt_timestamp(consensus.timestamp)}", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_dividends(dividends: DividendAnalysis) -> Panel:
    if dividends.quality == DataQuality.UNAVAILABLE:
        return _research_unavailable("DIVIDENDS", dividends.symbol, "Dividend data unavailable", "DVD")
    yearly: dict[int, float] = {}
    for record in dividends.records:
        yearly[record.ex_date.year] = yearly.get(record.ex_date.year, 0.0) + record.amount
    years = sorted(yearly, reverse=True)
    latest_years = years[:10]
    history = _terminal_table()
    history.add_column("YEAR", style="cyan")
    history.add_column("DPS", justify="right")
    history.add_column("GROWTH", justify="right")
    for year in latest_years:
        previous = yearly.get(year - 1)
        change = (yearly[year] / previous - 1.0) * 100.0 if previous not in {None, 0} else None
        history.add_row(str(year), fmt_number(yearly[year], 4), fmt_percent(change, signed=True))
    cagr_5y = None
    if len(latest_years) >= 6:
        newest, oldest = latest_years[0], latest_years[5]
        cagr_5y = cagr(yearly[oldest], yearly[newest], newest - oldest)
    snapshot = _paired_metric_table([
        ("INDICATED RATE", fmt_number(dividends.indicated_rate, 4)),
        ("DIVIDEND YIELD", fmt_percent(dividends.yield_percent)),
        ("PAYOUT RATIO", fmt_percent(dividends.payout_ratio_percent)),
        ("5Y AVG YIELD", fmt_percent(dividends.five_year_average_yield)),
        ("5Y DPS CAGR", fmt_percent(cagr_5y, signed=True)),
        ("EX-DIV DATE", dividends.ex_dividend_date.isoformat() if dividends.ex_dividend_date else "--"),
        ("PAYMENT DATE", dividends.payment_date.isoformat() if dividends.payment_date else "--"),
    ])
    return Panel(
        Group(
            _title(f"DVD  {dividends.name.upper()}  {dividends.symbol}"),
            _equity_command_strip(dividends.symbol, "DVD"),
            snapshot,
            _section("HISTORICAL DIVIDENDS PER SHARE"),
            history,
            Text(f"{dividends.provider} | {dividends.quality} | {fmt_timestamp(dividends.timestamp)}", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_events(events: list[CorporateEvent], symbol: str | None = None) -> Panel:
    table = _terminal_table()
    table.add_column("DATE", width=18, style="cyan")
    table.add_column("SYMBOL", width=12)
    table.add_column("EVENT", width=20, style="yellow")
    table.add_column("DETAIL", ratio=1)
    table.add_column("STATUS", width=10)
    table.add_column("DATA", width=10)
    for item in events:
        table.add_row(
            item.event_date.strftime("%d %b %Y %H:%M"),
            _instrument_link(item.symbol),
            item.event_type,
            item.detail or item.company,
            "ESTIMATE" if item.estimated else "CONFIRMED",
            str(item.quality),
        )
    if not events:
        table.add_row("--", symbol or "WATCHLIST", "NO EVENTS", "No events supplied for the selected 7-day window", "--", "N/A")
    title = f"EVT  {symbol}" if symbol else "EVT  WATCHLIST / MAJOR MARKETS  NEXT 7 DAYS"
    content: list[object] = [_title(title)]
    if symbol:
        content.append(_equity_command_strip(symbol, "EVT"))
    content.append(table)
    return Panel(Group(*content), border_style="grey35", box=box.SIMPLE)


def render_relative_valuation(valuation: RelativeValuation) -> Panel:
    if not valuation.peers:
        return _research_unavailable("RELATIVE VALUATION", valuation.symbol, valuation.message, "RV")
    table = _terminal_table()
    columns = ("SYMBOL", "PRICE", "MKT CAP", "P/E", "FWD P/E", "EV/EBITDA", "P/B", "REV GROWTH", "OP MARGIN", "ROE", "DIV YIELD")
    for index, label in enumerate(columns):
        table.add_column(label, style="cyan" if index == 0 else None, justify="left" if index == 0 else "right")
    for item in valuation.peers:
        style = "bold yellow" if item.symbol == valuation.symbol else "white"
        table.add_row(
            _instrument_link(item.symbol, style=style),
            fmt_number(item.price),
            fmt_money(item.market_cap),
            fmt_number(item.pe),
            fmt_number(item.forward_pe),
            fmt_number(item.ev_ebitda),
            fmt_number(item.price_book),
            fmt_percent(item.revenue_growth, signed=True),
            fmt_percent(item.operating_margin),
            fmt_percent(item.roe),
            fmt_percent(item.dividend_yield),
        )
    metric_accessors = [
        ("MEAN", mean),
        ("MEDIAN", median),
    ]
    for label, aggregate in metric_accessors:
        table.add_row(
            label,
            "--",
            fmt_money(aggregate(item.market_cap for item in valuation.peers)),
            fmt_number(aggregate(item.pe for item in valuation.peers)),
            fmt_number(aggregate(item.forward_pe for item in valuation.peers)),
            fmt_number(aggregate(item.ev_ebitda for item in valuation.peers)),
            fmt_number(aggregate(item.price_book for item in valuation.peers)),
            fmt_percent(aggregate(item.revenue_growth for item in valuation.peers), signed=True),
            fmt_percent(aggregate(item.operating_margin for item in valuation.peers)),
            fmt_percent(aggregate(item.roe for item in valuation.peers)),
            fmt_percent(aggregate(item.dividend_yield for item in valuation.peers)),
        )
    mode = "AUTOMATIC INDUSTRY PEERS" if valuation.automatic else "MANUAL PEER SET"
    basis = " / ".join(value for value in (valuation.peer_sector, valuation.peer_industry) if value)
    return Panel(
        Group(
            _title(f"RV  {valuation.symbol}  {mode}"),
            _equity_command_strip(valuation.symbol, "RV"),
            Text(f"PEER BASIS  {basis}" if basis else "PEER BASIS  USER SELECTED", style="yellow"),
            table,
            Text("Relative metrics are descriptive. THRIVEBERG does not label securities cheap or expensive.", style="dim"),
            Text(f"{valuation.provider} | {valuation.quality} | {fmt_timestamp(valuation.timestamp)}", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_screener(page: ScreenerPage) -> Panel:
    table = _terminal_table()
    for label, justify in (("SYMBOL", "left"), ("NAME", "left"), ("LAST", "right"), ("CHG %", "right"), ("MKT CAP", "right"), ("P/E", "right"), ("FWD P/E", "right"), ("ROE", "right"), ("ROIC", "right"), ("REV GROWTH", "right"), ("OP MARGIN", "right")):
        table.add_column(label, justify=justify, style="cyan" if label == "SYMBOL" else None, ratio=2 if label == "NAME" else 1)
    for item in page.results:
        table.add_row(
            _instrument_link(item.symbol),
            item.name,
            fmt_number(item.price),
            f"[{_change_style(item.change_percent)}]{fmt_percent(item.change_percent, signed=True)}[/]",
            fmt_money(item.market_cap),
            fmt_number(item.pe),
            fmt_number(item.forward_pe),
            fmt_percent(item.roe),
            fmt_percent(item.roic),
            fmt_percent(item.revenue_growth, signed=True),
            fmt_percent(item.operating_margin),
        )
    if not page.results:
        table.add_row("--", "No securities matched or data unavailable", *(["--"] * 9))
    filter_text = " ".join(f"{item.field}{item.operator}{item.value}" for item in page.filters) or "NONE"
    return Panel(
        Group(
            _title("EQS  EQUITY SCREENER"),
            _function_strip(("EQS", "WEI", "INSTRUMENTS"), "EQS"),
            Text(f"FILTERS  {filter_text}", style="yellow"),
            Text(f"UNIVERSE  {page.universe}", style="dim"),
            table,
            Text(page.message, style="dim"),
            Text(f"{page.provider} | {page.quality} | {fmt_timestamp(page.timestamp)}", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def _equity_identity(profile: CompanyProfile | None, estimates: EstimateSet | None) -> Text:
    if profile is None or profile.quality == DataQuality.UNAVAILABLE:
        return Text("Company profile unavailable", style="dim")
    parts = [profile.exchange, profile.sector, profile.industry, profile.country]
    line = "  |  ".join(item for item in parts if item)
    if estimates and estimates.earnings_date:
        line += f"  |  NEXT EARNINGS {estimates.earnings_date:%d %b %Y}"
    return Text(line or "Company profile available", style="white")


def _analyst_summary(consensus: AnalystConsensus | None) -> Text:
    if consensus is None or consensus.quality == DataQuality.UNAVAILABLE:
        return Text("Analyst consensus: N/A from configured public providers", style="dim")
    return Text(
        f"ANALYSTS  {consensus.recommendation or '--'}  |  Target {fmt_number(consensus.target_mean)} "
        f"{consensus.currency}  |  Upside {fmt_percent(consensus.upside_percent, signed=True)}  |  N={consensus.analyst_count or '--'}",
        style="yellow",
    )


def _equity_command_strip(symbol: str, active: str = "DES") -> Text:
    return _function_strip(
        ("DES", "GP", "FA", "EE", "ANR", "RV", "FILINGS", "NEWS"),
        active,
        symbol,
    )


def _instrument_command_strip(quote: Quote, active: str) -> Text:
    asset_class = quote.asset_class.upper()
    if asset_class == "EQUITY":
        return _equity_command_strip(quote.symbol, active)
    functions = {
        "INDEX": ("DES", "GP", "WEI", "NEWS"),
        "COMMODITY": ("DES", "GP", "NEWS"),
        "CMDTY": ("DES", "GP", "NEWS"),
        "RATE": ("DES", "GP", "CURVE", "GOVT", "NEWS"),
        "RATES": ("DES", "GP", "CURVE", "GOVT", "NEWS"),
    }.get(asset_class, ("DES", "GP", "NEWS"))
    return _function_strip(functions, active, quote.symbol)


def _function_strip(
    functions: tuple[str, ...],
    active: str,
    context: str = "",
    commands: dict[str, str] | None = None,
) -> Text:
    strip = Text()
    for index, function in enumerate(functions, start=1):
        style = "bold black on #d99116" if function == active else "white on #303338"
        command = (commands or {}).get(function, _function_command(function, context))
        action = "app.focus_command" if function == "SEARCH" else f"app.run_command({command!r})"
        button_style = Style.parse(style) + Style.from_meta({"@click": action})
        strip.append(f" {index}) {function} ", style=button_style)
        strip.append(" ")
    if context:
        strip.append(f" {context}", style="dim")
    return strip


def _function_command(function: str, context: str) -> str:
    function = function.upper()
    context = context.strip().upper()
    if not context:
        return function

    simple_context = re.fullmatch(r"[A-Z0-9.^=_/-]{1,32}", context) is not None
    country_to_currency = {
        "US": "USD",
        "DE": "EUR",
        "FR": "EUR",
        "IT": "EUR",
        "ES": "EUR",
        "GB": "GBP",
        "JP": "JPY",
    }
    currency_to_country = {"USD": "US", "EUR": "DE", "GBP": "GB", "JPY": "JP"}
    currency_to_benchmark = {"USD": "US10Y", "EUR": "DE10Y", "GBP": "GB10Y", "JPY": "JP10Y"}
    country_to_benchmark = {
        "US": "US10Y",
        "DE": "DE10Y",
        "FR": "FR10Y",
        "IT": "IT10Y",
        "ES": "ES10Y",
        "GB": "GB10Y",
        "JP": "JP10Y",
    }

    if function == "CURVE":
        currency = country_to_currency.get(context)
        if currency is None and context in currency_to_country:
            currency = context
        if currency is None and re.fullmatch(r"(US|DE|FR|IT|ES|GB|JP)\d+[MY]", context):
            currency = country_to_currency[context[:2]]
        return f"CURVE {currency}" if currency else "CURVE"

    if function in {"GOVT", "BTMM", "WB"}:
        target = currency_to_country.get(context, context)
        return f"{function} {target}" if simple_context else function

    if function == "GP":
        target = currency_to_benchmark.get(context)
        if target is None:
            target = country_to_benchmark.get(context)
        target = target or (context if simple_context else "")
        return f"GP {target}" if target else "GP AAPL"

    if function == "ECO":
        return f"ECO {context}" if context in country_to_currency else "ECO"

    contextual_functions = {
        "DES",
        "FX",
        "FWD",
        "BOND",
        "CORP",
        "FA",
        "IS",
        "BS",
        "CF",
        "EE",
        "ANR",
        "RV",
        "DVD",
        "EVT",
        "FILINGS",
        "10K",
        "10Q",
        "XLS",
        "EXPORT",
        "NEWS",
        "OMON",
        "OVME",
        "OVDV",
        "VOL",
    }
    if function in contextual_functions and simple_context:
        return f"{function} {context}"
    return function


def _financial_metric_value(metric: FinancialMetric | None) -> str:
    if metric is None or metric.value is None:
        return "[dim]N/A[/]"
    if metric.unit == "percent":
        return fmt_percent(metric.value)
    if metric.unit == "multiple" or metric.name == "EPS":
        return fmt_number(metric.value)
    return fmt_money(metric.value)


def _research_unavailable(title: str, symbol: str, message: str, active: str = "DES") -> Panel:
    return Panel(
        Group(
            _title(f"{title}  {symbol}"),
            _equity_command_strip(symbol, active),
            Text(message or "Data unavailable from configured providers", style="yellow"),
            Text("No mock values are shown on equity research screens.", style="dim"),
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_instrument_context(quote: Quote, history: PriceHistory, news: list[NewsItem]) -> Panel:
    stats = calculate_market_statistics(history)
    market = Table.grid(expand=True)
    market.add_column("field", width=12, style="cyan")
    market.add_column("value", ratio=1, justify="right")
    market.add_row("LAST", _price(quote))
    market.add_row("CHANGE", f"[{_change_style(quote.change_percent)}]{fmt_percent(quote.change_percent, signed=True)}[/]")
    market.add_row("PERIOD", f"[{_change_style(stats.period_return)}]{_decimal_percent(stats.period_return, signed=True)}[/]")
    market.add_row("52W RANGE", _range_bar(quote.price, quote.week_52_low, quote.week_52_high, 18))
    market.add_row("DATA", str(history.quality))

    headlines = Table.grid(expand=True)
    headlines.add_column("time", width=6)
    headlines.add_column("headline", ratio=1)
    for item in news[:7]:
        headlines.add_row(item.timestamp.strftime("%H:%M"), f"{item.headline}\n[dim]{item.source} / {item.quality}[/]")
    if not news:
        headlines.add_row("--", "No related headlines")
    return Panel(
        Group(_section("MARKET SNAPSHOT"), market, _section(f"{quote.symbol} HEADLINES"), headlines),
        title="CONTEXT",
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_chart_context(
    quote: Quote,
    history: PriceHistory,
    news: list[NewsItem],
    supplement: ChartSupplement,
) -> Panel:
    stats = calculate_market_statistics(history)
    snapshot = Table.grid(expand=True)
    snapshot.add_column("field", width=11, style="cyan")
    snapshot.add_column("value", ratio=1, justify="right")
    asset_class = normalized_asset_class(quote)
    change = (
        fmt_bp(quote.change * 100.0 if quote.change is not None else None)
        if asset_class == "RATE"
        else fmt_number(quote.change, _quote_decimals(quote), na="--")
    )
    snapshot.add_row("LAST", format_quote_value(quote))
    snapshot.add_row(
        "CHANGE",
        f"[{_change_style(quote.change_percent)}]{change} / {fmt_percent(quote.change_percent, signed=True)}[/]",
    )
    snapshot.add_row(
        "PERIOD",
        f"[{_change_style(stats.period_return)}]{_decimal_percent(stats.period_return, signed=True)}[/]",
    )
    snapshot.add_row("52W RANGE", _range_bar(quote.price, quote.week_52_low, quote.week_52_high, 12))
    snapshot.add_row("FEED", f"{history.provider} / {history.quality}")

    quick_stats = Table.grid(expand=True)
    quick_stats.add_column("field", width=11, style="cyan")
    quick_stats.add_column("value", ratio=1, justify="right")
    for label, value in build_chart_metrics(quote, history, supplement)[:8]:
        quick_stats.add_row(label, value)

    events = Table.grid(expand=True)
    events.add_column("time", width=10, style="yellow")
    events.add_column("event", ratio=1)
    for item in supplement.events[:3]:
        detail = f" [dim]{item.detail}[/]" if item.detail else ""
        events.add_row(item.when, f"{item.label}{detail}\n[dim]{item.quality}[/]")
    if not supplement.events:
        events.add_row("--", "No upcoming event data")

    headlines = Table.grid(expand=True)
    headlines.add_column("time", width=6)
    headlines.add_column("headline", ratio=1)
    for item in news[:5]:
        headlines.add_row(item.timestamp.strftime("%H:%M"), f"{item.headline}\n[dim]{item.source} / {item.quality}[/]")
    if not news:
        headlines.add_row("--", "No related headlines")

    return Panel(
        Group(
            _section("SNAPSHOT"),
            snapshot,
            _section("QUICK STATS"),
            quick_stats,
            _section("EVENTS / UPCOMING"),
            events,
            _section("NEWS"),
            headlines,
        ),
        title=f"GP CONTEXT / {quote.symbol}",
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_search(query: str, results: list[tuple[str, str, str]]) -> Panel:
    table = _terminal_table()
    table.add_column("SYMBOL", style="cyan", width=12)
    table.add_column("NAME", ratio=1)
    table.add_column("TYPE", width=14)
    for symbol, name, asset_type in results:
        table.add_row(_instrument_link(symbol), name, asset_type)
    if not results:
        table.add_row("--", "No registry or provider matches", "SEARCH")
    return Panel(
        Group(
            _title(f"SECURITY FINDER / {query.upper()}"),
            _function_strip(("SEARCH", "INSTRUMENTS", "EQS"), "SEARCH"),
            table,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_help() -> Panel:
    commands = [
        ("MARKETS", "WEI", "WEI", "World equity indices by region"),
        ("MARKETS", "MONITOR", "MARKETS", "Multi-asset market monitor"),
        ("FX", "FXC", "FXC", "G10 spot cross-rate matrix"),
        ("FX", "SPOT", "FX EURJPY", "Spot, history and forward curve"),
        ("FX", "FORWARDS", "FWD EURUSD 3M", "Outrights, points and carry"),
        ("RATES", "CURVE", "CURVE USD", "Sovereign zero/yield curve"),
        ("RATES", "BTMM / WB", "BTMM US", "Government benchmarks"),
        ("CREDIT", "CORP", "CORP", "Credit indices and registered cash bonds"),
        ("CREDIT", "BOND", "BOND AAPL44 PRICE 98.50", "Bond terms and yield analytics"),
        ("EQUITY", "DES", "DES AAPL", "Description, price history and fundamentals"),
        ("EQUITY", "FA / EE", "FA AAPL | EE AAPL", "Financial analysis and estimates"),
        ("EQUITY", "STATEMENTS", "IS AAPL | BS AAPL | CF AAPL", "Annual and quarterly statements"),
        ("EQUITY", "FILINGS", "FILINGS AAPL | 10K AAPL | 10Q AAPL", "Official filings by jurisdiction"),
        ("EQUITY", "EXPORT", "XLS AAPL", "Export annual and quarterly statements to Excel"),
        ("EQUITY", "ANALYSIS", "ANR AAPL | RV AAPL | DVD AAPL", "Consensus, peers and dividends"),
        ("OPTIONS", "OMON", "OMON AAPL", "Listed calls/puts, activity, IV and delta"),
        ("OPTIONS", "OVME", "OVME AAPL C 350 2026-12-18", "Black-Scholes pricer, Greeks and implied vol"),
        ("OPTIONS", "OVDV", "OVDV AAPL", "Volatility smiles, surface and moneyness table"),
        ("EQUITY", "EQS", "EQS COUNTRY=US PE<25", "Equity screening"),
        ("CHART", "GP", "GP AAPL 1Y 1D", "Interactive price and volume chart"),
        ("MACRO", "ECO / CAL", "ECO US | CAL", "Macro monitor and calendar"),
        ("MACRO", "MAP", "MAP GDP | MAP SPAIN", "Interactive Global Macro Map"),
        ("NEWS", "N", "NEWS | NEWS AAPL", "Topical or security news wire"),
        ("SOCIAL", "SOCIAL", "SOCIAL", "Friends, chat and shared THRIVEBERG screens"),
        ("DISCOVERY", "SECF", "INSTRUMENTS FX", "Registered instrument directory"),
        ("MONITOR", "WATCH", "WATCH ADD EURUSD", "Personal watchlist"),
    ]
    table = _terminal_table()
    table.add_column("MARKET", style="yellow", width=12)
    table.add_column("FUNCTION", style="cyan", width=14)
    table.add_column("COMMAND", width=28)
    table.add_column("DESCRIPTION", ratio=1)
    for row in commands:
        table.add_row(*row)
    return Panel(
        Group(
            _title("FUNCTION DIRECTORY"),
            _function_strip(("HELP", "SEARCH", "INSTRUMENTS"), "HELP"),
            table,
        ),
        border_style="grey35",
        box=box.SIMPLE,
    )


def render_message(title: str, message: str) -> Panel:
    return Panel(Group(_title(title), Text(message, style="white")), border_style="grey35", box=box.SIMPLE)


def _quote_snapshot(quote: Quote) -> Table:
    decimals = _quote_decimals(quote)
    change_style = _change_style(quote.change_percent)
    return _paired_metric_table([
        ("LAST", f"[bold white]{fmt_number(quote.price, decimals)} {_quote_unit(quote)}[/]"),
        ("OPEN", fmt_number(quote.open_price, decimals)),
        ("DAY HIGH", fmt_number(quote.day_high, decimals)),
        ("52W HIGH", fmt_number(quote.week_52_high, decimals)),
        ("BID", fmt_number(quote.bid, decimals)),
        (
            "CHANGE",
            f"[{change_style}]{fmt_number(quote.change, decimals, na='--')} / {fmt_percent(quote.change_percent, signed=True)}[/]",
        ),
        ("PREV CLOSE", fmt_number(quote.previous_close, decimals)),
        ("DAY LOW", fmt_number(quote.day_low, decimals)),
        ("52W LOW", fmt_number(quote.week_52_low, decimals)),
        ("ASK", fmt_number(quote.ask, decimals)),
    ], label_width=12)


def _history_dashboard(history: PriceHistory) -> Group:
    stats = calculate_market_statistics(history)
    first_close = history.bars[0].close if history.bars else None
    last_close = history.bars[-1].close if history.bars else None
    net_change = last_close - first_close if first_close is not None and last_close is not None else None
    closes = [bar.close for bar in history.bars]
    average_price = sum(closes) / len(closes) if closes else None

    summary = _terminal_table(expand=False)
    summary.add_column("RANGE", style="cyan", width=8, no_wrap=True)
    summary.add_column("NET CHG", justify="right", min_width=10, no_wrap=True)
    summary.add_column("% CHG", justify="right", min_width=9, no_wrap=True)
    summary.add_column("HIGH", justify="right", min_width=10, no_wrap=True)
    summary.add_column("LOW", justify="right", min_width=10, no_wrap=True)
    summary.add_column("AVG PX", justify="right", min_width=10, no_wrap=True)
    summary.add_column("LAST VOL", justify="right", min_width=10, no_wrap=True)
    summary.add_column("AVG VOL 20", justify="right", min_width=10, no_wrap=True)
    period_style = _change_style(stats.period_return)
    summary.add_row(
        history.period,
        f"[{period_style}]{_signed_number(net_change, 4)}[/]",
        f"[{period_style}]{_decimal_percent(stats.period_return, signed=True)}[/]",
        fmt_number(stats.high, 4),
        fmt_number(stats.low, 4),
        fmt_number(average_price, 4),
        fmt_money(stats.latest_volume, 1),
        fmt_money(stats.average_volume_20, 1),
    )

    risk_rows = [
        ("ANN. VOL", _decimal_percent(stats.annualized_volatility)),
        ("MAX DRAWDOWN", _decimal_percent(stats.max_drawdown)),
        ("HIST. VAR 95", _decimal_percent(stats.historical_var_95)),
        ("EXP. SHORTFALL", _decimal_percent(stats.expected_shortfall_95)),
        ("SHARPE", fmt_number(stats.sharpe)),
        ("ATR 14", fmt_number(_average_true_range(history), 4)),
    ]
    risk = _paired_metric_table(risk_rows, label_width=16)

    performance = _terminal_table(expand=False)
    performance.add_column("HORIZON", style="cyan", width=9, no_wrap=True)
    returns = horizon_returns(history)
    for label in returns:
        performance.add_column(label, justify="right", min_width=8, no_wrap=True)
    performance.add_row(
        "RETURN",
        *[
            f"[{_change_style(value)}]{_decimal_percent(value, signed=True)}[/]"
            for value in returns.values()
        ],
    )
    return Group(
        _section(f"PRICE HISTORY [{history.period}]"),
        _subpanel("PERIOD SUMMARY", summary),
        _subpanel(f"HISTORICAL OHLC / {history.interval}", _recent_ohlc(history)),
        _subpanel("HORIZON RETURNS", performance),
        _subpanel("RISK / TRADING", risk),
    )


def _recent_ohlc(history: PriceHistory) -> Table:
    table = _terminal_table(expand=False)
    table.add_column("DATE", style="cyan", min_width=13, no_wrap=True)
    for label in ("OPEN", "HIGH", "LOW", "CLOSE"):
        table.add_column(label, justify="right", min_width=10, no_wrap=True)
    table.add_column("NET CHG", justify="right", min_width=10, no_wrap=True)
    table.add_column("% CHG", justify="right", min_width=9, no_wrap=True)
    table.add_column("VOLUME", justify="right", min_width=10, no_wrap=True)
    intraday = history.interval.endswith("m") or history.interval.endswith("h")
    first_visible_index = max(0, len(history.bars) - 5)
    for index in range(len(history.bars) - 1, first_visible_index - 1, -1):
        bar = history.bars[index]
        timestamp = f"{bar.timestamp:%d %b %H:%M}" if intraday else f"{bar.timestamp:%d %b %Y}"
        previous_close = history.bars[index - 1].close if index > 0 else None
        change = bar.close - previous_close if previous_close is not None else None
        change_percent = change / previous_close if change is not None and previous_close else None
        change_style = _change_style(change)
        table.add_row(
            timestamp,
            fmt_number(bar.open, 4),
            fmt_number(bar.high, 4),
            fmt_number(bar.low, 4),
            fmt_number(bar.close, 4),
            f"[{change_style}]{_signed_number(change, 4)}[/]",
            f"[{change_style}]{_decimal_percent(change_percent, signed=True)}[/]",
            fmt_money(bar.volume, 1),
        )
    if not history.bars:
        table.add_row("No history", "--", "--", "--", "--", "--", "--", "--")
    return table


def _terminal_table(*, expand: bool = True, padding: tuple[int, int] = (0, 1)) -> Table:
    return Table(
        box=box.SQUARE,
        show_edge=False,
        expand=expand,
        padding=padding,
        header_style="bold bright_yellow",
        border_style="grey23",
    )


def _metric_table(rows: list[tuple[str, str]] | None = None, label_width: int = 20) -> Table:
    table = Table.grid(expand=False, padding=(0, 1))
    table.add_column("metric", style="cyan", width=label_width, no_wrap=True)
    table.add_column("value", justify="right", min_width=10, no_wrap=True)
    for label, value in rows or []:
        table.add_row(label, value)
    return table


def _statement_table(
    periods: list[FinancialPeriod],
    statement_type: StatementType,
    metric_labels: dict[str, str] | None = None,
    metric_order: list[str] | None = None,
    metric_sections: dict[str, str] | None = None,
) -> Table:
    table = _terminal_table()
    table.add_column("LINE ITEM", style="cyan", ratio=2)
    visible_periods = periods[:6]
    for period in visible_periods:
        label = f"{period.period}{'*' if period.derived else ''}"
        table.add_column(label, justify="right", ratio=1)
    if not visible_periods:
        table.add_row("No data offered by provider")
        return table
    if any(period.source_form for period in visible_periods):
        table.add_row(
            "PERIOD END",
            *[period.end_date.isoformat() if period.end_date else "--" for period in visible_periods],
            style="dim",
        )
        table.add_row(
            "SOURCE FORM",
            *[
                f"{period.source_form}{'*' if period.derived else ''}" if period.source_form else "--"
                for period in visible_periods
            ],
            style="dim",
        )
        table.add_row(
            "FILED",
            *[period.filed_date.isoformat() if period.filed_date else "--" for period in visible_periods],
            style="dim",
        )
    keys = ordered_statement_metrics(visible_periods, statement_type, metric_order)
    for group_index, (group_title, group_metrics) in enumerate(
        grouped_statement_metrics(keys, statement_type, metric_sections)
    ):
        if group_index:
            table.add_row(*([""] * (1 + len(visible_periods))))
        table.add_row(
            Text(group_title, style="bold blue"),
            *([""] * len(visible_periods)),
        )
        for key in group_metrics:
            is_expense = is_expense_or_outflow_metric(key, statement_type)
            table.add_row(
                Text((metric_labels or {}).get(key, _humanize_metric(key)).upper(), style="white"),
                *[
                    _statement_value_text(period.values.get(key), force_red=is_expense)
                    for period in visible_periods
                ],
            )
    return table


def _humanize_metric(value: str) -> str:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ")
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", separated)
    return separated.upper()


def _statement_value(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 100_000:
        return fmt_money(value, 1)
    return fmt_number(value, 2)


def _statement_value_text(value: float | None, force_red: bool = False) -> Text:
    style = "bright_red" if force_red else "bright_yellow"
    return Text(_statement_value(value), style=style)


def _paired_metric_table(rows: list[tuple[str, str]], label_width: int = 20) -> Table:
    table = Table.grid(expand=False, padding=(0, 1))
    table.add_column("metric1", style="cyan", width=label_width, no_wrap=True)
    table.add_column("value1", justify="right", min_width=10, no_wrap=True)
    table.add_column("separator", style="grey35", width=3, justify="center", no_wrap=True)
    table.add_column("metric2", style="cyan", width=label_width, no_wrap=True)
    table.add_column("value2", justify="right", min_width=10, no_wrap=True)
    midpoint = (len(rows) + 1) // 2
    left = rows[:midpoint]
    right = rows[midpoint:]
    for index, (left_label, left_value) in enumerate(left):
        right_label, right_value = right[index] if index < len(right) else ("", "")
        separator = "|" if right_label else ""
        table.add_row(left_label, left_value, separator, right_label, right_value)
    return table


def _data_line(quote: Quote, history: PriceHistory) -> Text:
    return Text(
        f"Quote: {quote.provider} / {quote.quality} / {fmt_timestamp(quote.timestamp)}  |  "
        f"History: {history.provider} / {history.quality} / {fmt_timestamp(history.timestamp)}",
        style="dim",
    )


def _decimal_percent(value: float | None, signed: bool = False) -> str:
    return fmt_percent(value * 100.0 if value is not None else None, signed=signed)


def _signed_number(value: float | None, decimals: int = 2) -> str:
    formatted = fmt_number(value, decimals)
    return f"+{formatted}" if value is not None and value > 0 else formatted


def _range_bar(value: float | None, low: float | None, high: float | None, width: int = 20) -> str:
    if value is None or low is None or high is None or high <= low:
        return "--"
    position = round((value - low) / (high - low) * (width - 1))
    position = min(max(position, 0), width - 1)
    return "|" + "-" * position + "*" + "-" * (width - position - 1) + "|"


def _average_true_range(history: PriceHistory, length: int = 14) -> float | None:
    if not history.bars:
        return None
    bars = history.bars[-length:]
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        candidates = [bar.high - bar.low]
        if previous_close is not None:
            candidates.extend([abs(bar.high - previous_close), abs(bar.low - previous_close)])
        ranges.append(max(candidates))
        previous_close = bar.close
    return sum(ranges) / len(ranges)


def _quote_block(title: str, quotes: list[Quote]) -> Group:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column("symbol", style="cyan", width=6, no_wrap=True)
    table.add_column("price", justify="right", width=8, no_wrap=True)
    table.add_column("change", justify="right", width=7, no_wrap=True)
    table.add_column("data", justify="right", width=5, no_wrap=True)
    for quote in quotes:
        table.add_row(
            _instrument_link(quote.symbol),
            _price(quote),
            f"[{_change_style(quote.change_percent)}]{fmt_percent(quote.change_percent, signed=True)}[/]",
            _quality_label(quote.quality, compact=True),
        )
    return Group(_subpanel(title, table), Text(""))


def _two_columns(left, right) -> Table:
    layout = Table.grid(expand=True, padding=(0, 0))
    layout.add_column("left", ratio=1)
    layout.add_column("gutter", width=3)
    layout.add_column("right", ratio=1)
    layout.add_row(left, "", right)
    return layout


def _three_columns(left, middle, right) -> Table:
    layout = Table.grid(expand=True, padding=(0, 0))
    layout.add_column("left", ratio=1)
    layout.add_column("gutter-a", width=2)
    layout.add_column("middle", ratio=1)
    layout.add_column("gutter-b", width=2)
    layout.add_column("right", ratio=1)
    layout.add_row(left, "", middle, "", right)
    return layout


def _subpanel(title: str, renderable) -> Group:
    return Group(Text(title, style="bold #4f9ebb"), renderable)


def _title(text: str) -> Text:
    return Text(text, style="bold bright_yellow")


def _instrument_link(
    symbol: str,
    label: str | None = None,
    style: str = "bold cyan",
) -> Text:
    clean_symbol = symbol.strip().upper()
    link_style = Style.parse(style) + Style(
        underline=False,
        meta={"@click": f"app.open_instrument({clean_symbol!r})"},
    )
    return Text(label if label is not None else clean_symbol, style=link_style)


def _section(text: str) -> Text:
    return Text(f"\n{text}", style="bold #4f9ebb")


def _price(quote: Quote) -> str:
    price = fmt_number(quote.price, _quote_decimals(quote))
    return f"{price}%" if quote.asset_class.upper() in {"RATE", "RATES"} else price


def _quote_unit(quote: Quote) -> str:
    return "%" if quote.asset_class.upper() in {"RATE", "RATES"} else quote.currency or "--"


def _quality_label(quality: DataQuality, compact: bool = False) -> str:
    style = "yellow" if quality == DataQuality.MOCK else "dim"
    label = str(quality)
    if compact:
        label = {
            DataQuality.REALTIME: "LIVE",
            DataQuality.DELAYED: "DLY",
            DataQuality.CACHED: "CACHE",
            DataQuality.MOCK: "MOCK",
            DataQuality.UNAVAILABLE: "N/A",
        }[quality]
    return f"[{style}]{label}[/]"


def _quote_decimals(quote: Quote) -> int:
    asset_class = quote.asset_class.upper()
    return 5 if asset_class == "FX" else 3 if asset_class in {"RATE", "RATES"} else 2


def _change_style(value: float | None) -> str:
    if value is None:
        return "grey58"
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "white"


def _matrix_style(value: float | None) -> str:
    if value is None:
        return "dim"
    if value > 0:
        return "black on #19733a"
    if value < 0:
        return "white on #7a1830"
    return "black on grey70"


def _status_style(status: str) -> str:
    if status == "OPEN":
        return "green"
    if status in {"PRE", "POST"}:
        return "yellow"
    return "grey58"


def _spread(curve: Curve, left: str, right: str) -> float | None:
    left_point = curve.point(left)
    right_point = curve.point(right)
    if left_point is None or right_point is None:
        return None
    return (right_point.yield_pct - left_point.yield_pct) * 100.0
