from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from rich.style import Style
from rich.text import Text

from ajax_terminal.models.quote import DataQuality, Quote
from ajax_terminal.utils.dates import local_now, utc_now


class TerminalHeader(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.can_go_back = False
        self.can_go_forward = False

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar-brand")
        yield Static("", id="topbar-actions")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh_header)
        self.refresh_header()

    def refresh_header(self) -> None:
        local = local_now("Europe/Madrid")
        utc = utc_now().astimezone(timezone.utc)
        market_state = "OPEN" if 8 <= local.astimezone(ZoneInfo("America/New_York")).hour < 22 else "CLOSED"
        self.query_one("#topbar-brand", Static).update(
            "THRIVEBERG TERMINAL"
            f"     {local:%H:%M:%S %Z}"
            f"     UTC {utc:%H:%M:%S}"
            "     DATA: AUTO"
            f"     MARKET: {market_state}"
        )
        actions = Text()
        actions.append(" GO ", _action_style("app.run_command('HOME')"))
        actions.append(" < ", _action_style("app.history_back", self.can_go_back))
        actions.append(" > ", _action_style("app.history_forward", self.can_go_forward))
        for label, command in (
            ("F1", "HELP"),
            ("F2", "MARKETS"),
            ("F3", "FX"),
            ("HELP", "HELP"),
        ):
            actions.append(f" {label} ", _action_style(f"app.run_command('{command}')"))
        actions.append(" ")
        actions.append(" SEARCH ", _action_style("app.focus_command"))
        for label, command in (
            ("MONITOR", "MARKETS"),
            ("NEWS", "NEWS"),
            ("OPTIONS", "OMON AAPL"),
            ("SOCIAL", "SOCIAL"),
            ("MENU", "HELP"),
        ):
            actions.append(f" {label} ", _action_style(f"app.run_command('{command}')"))
        actions.append("  THRIVEBERG PROFESSIONAL", style="grey70")
        self.query_one("#topbar-actions", Static).update(actions)

    def set_navigation_state(self, *, can_go_back: bool, can_go_forward: bool) -> None:
        self.can_go_back = can_go_back
        self.can_go_forward = can_go_forward
        if self.is_mounted:
            self.refresh_header()


class InstrumentStrip(Vertical):
    """Persistent Bloomberg-style header for the active instrument."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.function = "DES"
        self.symbol = "--"
        self.period: str | None = None
        self.interval: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="instrument-function")
        yield Static("", id="instrument-market")

    def on_mount(self) -> None:
        self.clear()

    def prepare(
        self,
        function: str,
        symbol: str,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        self.function = function.upper()
        self.symbol = symbol.upper().strip()
        self.period = period.upper() if period else None
        self.interval = _interval_label(interval) if interval else None
        self.display = True
        self.query_one("#instrument-function", Static).update(self._function_line("LOADING"))
        self.query_one("#instrument-market", Static).update(self._market_line(None))

    def set_quote(self, quote: Quote) -> None:
        self.symbol = quote.symbol.upper().strip() or self.symbol
        self.display = True
        self.query_one("#instrument-function", Static).update(self._function_line(str(quote.quality), quote))
        self.query_one("#instrument-market", Static).update(self._market_line(quote))

    def set_unavailable(self) -> None:
        self.display = True
        self.query_one("#instrument-function", Static).update(self._function_line("UNAVAILABLE"))
        self.query_one("#instrument-market", Static).update(self._market_line(None))

    def clear(self) -> None:
        self.function = "--"
        self.symbol = "--"
        self.period = None
        self.interval = None
        self.display = True
        self.query_one("#instrument-function", Static).update(self._function_line("NO INSTRUMENT"))
        self.query_one("#instrument-market", Static).update(self._market_line(None))

    def _function_line(self, quality: str, quote: Quote | None = None) -> str | Text:
        if self.symbol != "--":
            title = {
                "DES": "SECURITY DESCRIPTION",
                "GP": "PRICE CHART",
                "FX": "SPOT MARKET",
                "FWD": "FORWARD MONITOR",
                "GOVT": "GOVERNMENT BONDS",
                "CORP": "CORPORATE CREDIT",
                "BOND": "BOND ANALYSIS",
                "IS": "INCOME STATEMENT",
                "BS": "BALANCE SHEET",
                "CF": "CASH FLOW",
                "FA": "FINANCIAL ANALYSIS",
                "RV": "RELATIVE VALUE",
                "EE": "EARNINGS & ESTIMATES",
                "ANR": "ANALYST RECOMMENDATIONS",
                "DVD": "DIVIDENDS",
                "EVT": "EVENTS",
                "FILINGS": "REGULATORY FILINGS",
                "10K": "ANNUAL FILING",
                "10Q": "QUARTERLY FILING",
                "XLS": "EXCEL EXPORT",
                "NEWS": "SECURITY NEWS",
                "OMON": "OPTION MONITOR",
                "OVME": "OPTION VALUATION",
                "OVDV": "VOLATILITY SURFACE",
            }.get(self.function, self.function)
            context = ""
            if self.period and self.interval:
                context = f"  {self.period} / {self.interval}"
            elif self.period:
                context = f"  {self.period}"
            line = Text()
            line.append(f" {self.symbol} {_security_label(quote)} ", style="bold black on #e6a019")
            line.append(" 90) Asset ", style="bold white on #b00025")
            line.append(" 91) Actions ", style="bold white on #b00025")
            line.append(" 92) Settings ", style="bold white on #b00025")
            line.append(f" {title} ", style="bold white on #b00025")
            if context:
                line.append(context, style="bold white on #b00025")
            line.append(f" {quality} ", style="bold white on #7b0019")
            return line
        return f"{self.function}  --  |  Related Functions  |  Actions  |  {quality}"

    def _market_line(self, quote: Quote | None) -> str:
        usable = quote is not None and quote.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        asset_class = quote.asset_class.upper() if quote is not None else ""
        is_rate = asset_class in {"RATE", "RATES"}
        decimals = 5 if asset_class == "FX" else 3 if is_rate else 2
        price = _number(quote.price if usable and quote else None, decimals)
        change = quote.change if usable and quote else None
        change_percent = quote.change_percent if usable and quote else None
        color = "green" if (change_percent or change or 0) > 0 else "red" if (change_percent or change or 0) < 0 else "white"
        unit = "%" if is_rate else quote.currency if usable and quote and quote.currency else "--"
        open_price = _number(quote.open_price if usable and quote else None, decimals)
        high = _number(quote.day_high if usable and quote else None, decimals)
        low = _number(quote.day_low if usable and quote else None, decimals)
        bid = _number(quote.bid if usable and quote else None, decimals)
        ask = _number(quote.ask if usable and quote else None, decimals)
        volume = f"{quote.volume:,.0f}" if usable and quote and quote.volume is not None else "--"
        status = quote.market_status if usable and quote and quote.market_status else "--"
        return (
            f"[bold cyan]{self.symbol}[/]  [bold white]{price} {unit}[/]  "
            f"[{color}]{_signed(change)} / {_signed(change_percent, suffix='%')}[/]  |  "
            f"BID [white]{bid}[/]  ASK [white]{ask}[/]  |  "
            f"O [white]{open_price}[/]  H [green]{high}[/]  L [red]{low}[/]  |  "
            f"VOL [white]{volume}[/]  |  {status}"
        )


class HotkeyBar(Static):
    def on_mount(self) -> None:
        self.update(
            "F1 HELP  F2 MARKETS  F3 FX  F4 GOVT  F5 EQUITY  F6 ECO  F7 NEWS  F8 GP  F9 SOCIAL  F10 OPTIONS  |  "
            "PGUP/PGDN  / COMMAND  ESC MENU"
        )


def _number(value: float | None, decimals: int) -> str:
    return f"{value:,.{decimals}f}" if value is not None else "--"


def _signed(value: float | None, suffix: str = "") -> str:
    return f"{value:+,.2f}{suffix}" if value is not None else "--"


def _interval_label(value: str) -> str:
    labels = {"1wk": "1W", "1mo": "1M", "60m": "60M"}
    return labels.get(value.lower(), value.upper())


def _security_label(quote: Quote | None) -> str:
    if quote is None:
        return "Security"
    return {
        "EQUITY": "Equity",
        "INDEX": "Index",
        "FX": "Curncy",
        "RATE": "Govt",
        "RATES": "Govt",
        "COMMODITY": "Comdty",
        "CMDTY": "Comdty",
    }.get(quote.asset_class.upper(), quote.asset_class.title() or "Security")


def _action_style(action: str, enabled: bool = True) -> Style:
    if not enabled:
        return Style(color="grey39", underline=False)
    return Style(color="grey78", underline=False, meta={"@click": action})
