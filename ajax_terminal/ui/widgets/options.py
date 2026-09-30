from __future__ import annotations

from datetime import date
import math

from rich.table import Table
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Static

from ajax_terminal.analytics.options import implied_volatility, option_analytics
from ajax_terminal.models.options import OptionChain, OptionContract, OptionMarketContext, VolatilitySurface
from ajax_terminal.ui.image_widget import Image
from ajax_terminal.ui.options_chart import build_volatility_image


class OptionsWorkspace(Vertical):
    can_focus = True

    class FunctionRequested(Message):
        def __init__(self, function: str, symbol: str, *args: str) -> None:
            super().__init__()
            self.function = function
            self.symbol = symbol
            self.args = args

    class PopOutRequested(Message):
        def __init__(self, symbol: str) -> None:
            super().__init__()
            self.symbol = symbol

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.mode = "OMON"
        self.symbol = "AAPL"
        self.chain: OptionChain | None = None
        self.monitor_chains: list[OptionChain] = []
        self.context = OptionMarketContext(0.0, 0.0, "UNAVAILABLE", "UNAVAILABLE")
        self.surface: VolatilitySurface | None = None
        self.selected_strike: float | None = None
        self.option_type = "call"
        self.vol_mode = "SURFACE"
        self.surface_elevation = 14.0
        self.surface_azimuth = -48.0
        self.surface_zoom = 1.0
        self.surface_slice_index = 0
        self.skew_center = 1.0
        self.skew_zoom = 1.0
        self.skew_tracked_moneyness = 1.0
        self._surface_dragging = False
        self._surface_render_pending = False

    def compose(self) -> ComposeResult:
        yield Static("Waiting for option data...", id="options-market-line")
        with Vertical(id="options-chain-view", classes="options-view"):
            with Horizontal(id="options-chain-controls"):
                yield Static("CALC MODE", classes="options-control-label")
                yield Static("MID", id="options-calc-mode", classes="options-amber-field")
                yield Static("EXP", classes="options-control-label compact")
                yield Button("<", id="options-expiry-prev", classes="options-icon")
                yield Static("--", id="options-expiry-label")
                yield Button(">", id="options-expiry-next", classes="options-icon")
                yield Button("VALUE CALL", id="options-price-call", classes="options-action")
                yield Button("VALUE PUT", id="options-price-put", classes="options-action")
            yield Static("CALLS  <  OPTION MONITOR  >  PUTS", id="options-chain-summary")
            with Horizontal(id="options-chain-body"):
                yield DataTable(id="options-chain-table")
                with Vertical(id="options-chain-analysis"):
                    yield Static("EXPIRY ANALYSIS", classes="options-section-title")
                    yield Static("Select a strike to inspect the contract.", id="options-contract-detail")
            yield Static("MID MARKET  |  IV FROM VALID BID / ASK  |  REAL PROVIDER CONTRACTS", id="options-chain-footer")
        with Vertical(id="options-pricer-view", classes="options-view"):
            with Horizontal(id="options-pricer-nav"):
                yield Static("1) VALUATION", classes="options-pricer-tab selected")
                yield Static("VANILLA EQUITY OPTION", classes="options-pricer-tab")
                yield Button("CALCULATE", id="options-calculate", classes="options-action")
                yield Button("SOLVE IV", id="options-solve-iv", classes="options-action")
                yield Button("USE MARKET", id="options-use-market", classes="options-action")
            yield Static("UNDERLYING  --  |  UND PRICE  MID --  |  TRADE DATE --  |  SETTLE --", id="options-pricer-underlying")
            with Horizontal(id="options-pricer-body"):
                with Vertical(id="options-pricer-results", classes="options-pricer-panel"):
                    yield Static("RESULTS", classes="options-section-title")
                    yield Static("Enter valid deal inputs.", id="options-result-grid")
                with Vertical(id="options-pricer-deal", classes="options-pricer-panel"):
                    yield Static("EUROPEAN VANILLA", id="options-deal-title", classes="options-section-title")
                    with Horizontal(id="options-pricer-fields"):
                        with Vertical(id="options-pricer-terms"):
                            with Horizontal(classes="option-field"):
                                yield Static("CALL / PUT", classes="option-field-label")
                                yield Button("CALL", id="options-call", classes="option-side")
                                yield Button("PUT", id="options-put", classes="option-side")
                            for field_id, label in (
                                ("spot", "UND PRICE"),
                                ("strike", "STRIKE"),
                                ("expiry", "EXPIRY"),
                                ("quantity", "SHARES"),
                            ):
                                with Horizontal(classes="option-field"):
                                    yield Static(label, classes="option-field-label")
                                    yield Input(id=f"option-input-{field_id}", classes="option-input")
                        with Vertical(id="options-pricer-market"):
                            for field_id, label in (
                                ("volatility", "VOL %"),
                                ("rate", "USD RATE %"),
                                ("dividend", "DIV YIELD %"),
                                ("premium", "MKT PRICE"),
                            ):
                                with Horizontal(classes="option-field"):
                                    yield Static(label, classes="option-field-label")
                                    yield Input(id=f"option-input-{field_id}", classes="option-input")
                    yield Static(
                        "STYLE       VANILLA\n"
                        "EXERCISE    EUROPEAN\n"
                        "DIRECTION   BUY\n"
                        "MODEL       BLACK-SCHOLES\n"
                        "MULTIPLIER  100\n"
                        "DAY COUNT   ACT / 365",
                        id="options-conventions-grid",
                    )
            yield Static("EUROPEAN / BLACK-SCHOLES / CONTINUOUS DIVIDEND YIELD", id="options-model-note")
        with Vertical(id="options-vol-view", classes="options-view"):
            with Horizontal(id="options-vol-tabs"):
                yield Button("1) VOL TABLE", id="options-vol-table", name="TABLE", classes="options-vol-mode")
                yield Button("2) 3D SURFACE", id="options-vol-surface", name="SURFACE", classes="options-vol-mode")
                yield Button("3) TERM", id="options-vol-term", name="TERM", classes="options-vol-mode")
                yield Button("4) SKEW", id="options-vol-skew", name="SKEW", classes="options-vol-mode")
                yield Button("< TERM", id="options-vol-term-prev", classes="options-action")
                yield Button("TERM >", id="options-vol-term-next", classes="options-action")
                yield Button("RESET VIEW", id="options-vol-reset", classes="options-action")
                yield Button("POP OUT", id="options-vol-popout", classes="options-action")
            with Horizontal(id="options-vol-parameters"):
                yield Static("MONEYNESS", id="options-vol-axis")
                yield Static("* LISTED EXP", classes="options-vol-parameter active")
                yield Static("o TENORS", classes="options-vol-parameter")
                yield Static("o LOCAL VOL", classes="options-vol-parameter")
                yield Static("o STRIKES", classes="options-vol-parameter")
                yield Static("[X] MATCH SCALES", classes="options-vol-parameter active")
                yield Static("DERIVED DISPLAY GRID / OBSERVED MIDS IN VOL TABLE", id="options-vol-method")
            yield Image(id="options-vol-image")
            yield DataTable(id="options-vol-table-grid")

    def on_mount(self) -> None:
        self._show_mode("OMON")
        self.query_one("#options-chain-table", DataTable).cursor_type = "row"
        self.query_one("#options-vol-table-grid", DataTable).cursor_type = "row"
        self._sync_buttons()

    def set_loading(self, mode: str, symbol: str) -> None:
        self.mode = mode.upper()
        self.symbol = symbol.upper()
        self._show_mode(self.mode)
        self.query_one("#options-market-line", Static).update("Loading real option market data...")
        self.query_one("#options-vol-image", Image).image = None
        self._sync_buttons()

    def set_chain(
        self,
        chain: OptionChain,
        context: OptionMarketContext,
        chains: list[OptionChain] | None = None,
    ) -> None:
        self.mode = "OMON"
        self.chain = chain
        self.monitor_chains = chains or [chain]
        self.context = context
        self.symbol = chain.symbol
        self._show_mode("OMON")
        self._update_common_header(chain)
        self._populate_chain_table()
        self._sync_buttons()

    def set_pricer(
        self,
        chain: OptionChain,
        context: OptionMarketContext,
        option_type: str | None = None,
        strike: float | None = None,
    ) -> None:
        self.mode = "OVME"
        self.chain = chain
        self.monitor_chains = [chain]
        self.context = context
        self.symbol = chain.symbol
        self.option_type = option_type if option_type in {"call", "put"} else "call"
        self.selected_strike = strike or _nearest_strike(chain)
        self._show_mode("OVME")
        self._update_common_header(chain)
        self._load_market_contract()
        self._calculate()
        self._sync_buttons()

    def set_surface(self, surface: VolatilitySurface) -> None:
        self.mode = "OVDV"
        self.surface = surface
        self.symbol = surface.symbol
        self._reset_surface_camera(redraw=False)
        self._reset_skew_view(redraw=False)
        self._show_mode("OVDV")
        rate_text = f"{surface.rate * 100:.3f}%" if surface.rate_available else "--"
        self.query_one("#options-market-line", Static).update(
            f"{surface.name.upper()}  |  SPOT {_price(surface.spot)} {surface.currency or '--'}  |  "
            f"RATE {rate_text}  |  DIV {surface.dividend_yield * 100:.3f}%  |  "
            f"{len(surface.slices)} EXPIRIES"
        )
        self._populate_vol_table()
        self._draw_volatility()
        self._sync_buttons()

    @on(Button.Pressed, "#options-expiry-prev")
    def previous_expiry(self) -> None:
        self._request_expiry(-1)

    @on(Button.Pressed, "#options-expiry-next")
    def next_expiry(self) -> None:
        self._request_expiry(1)

    @on(Button.Pressed, "#options-price-call")
    def price_call(self) -> None:
        self._request_pricer("call")

    @on(Button.Pressed, "#options-price-put")
    def price_put(self) -> None:
        self._request_pricer("put")

    @on(Button.Pressed, "#options-call")
    def select_call(self) -> None:
        self.option_type = "call"
        self._load_market_contract()
        self._calculate()
        self._sync_buttons()

    @on(Button.Pressed, "#options-put")
    def select_put(self) -> None:
        self.option_type = "put"
        self._load_market_contract()
        self._calculate()
        self._sync_buttons()

    @on(Button.Pressed, "#options-calculate")
    def calculate_selected(self) -> None:
        self._calculate()

    @on(Button.Pressed, "#options-solve-iv")
    def solve_iv_selected(self) -> None:
        try:
            values = self._pricer_values()
            premium = _float_input(self, "premium")
            volatility = implied_volatility(
                self.option_type,
                premium,
                values["spot"],
                values["strike"],
                values["rate"],
                values["time"],
                values["dividend"],
            )
            self.query_one("#option-input-volatility", Input).value = f"{volatility * 100:.4f}"
            self._calculate()
        except ValueError as exc:
            self._set_pricer_error(str(exc))

    @on(Button.Pressed, "#options-use-market")
    def use_market_selected(self) -> None:
        self._load_market_contract()
        self._calculate()

    @on(Input.Submitted, ".option-input")
    def input_submitted(self) -> None:
        self._calculate()

    @on(Button.Pressed, ".options-vol-mode")
    def vol_mode_selected(self, event: Button.Pressed) -> None:
        self.vol_mode = (event.button.name or "SMILE").upper()
        self._draw_volatility()
        self._sync_buttons()
        self.focus()

    @on(Button.Pressed, "#options-vol-reset")
    def reset_vol_view(self) -> None:
        if self.vol_mode == "SURFACE":
            self._reset_surface_camera(redraw=True)
        elif self.vol_mode == "SKEW":
            self._reset_skew_view(redraw=True)

    @on(Button.Pressed, "#options-vol-term-prev")
    def previous_vol_term(self) -> None:
        self._change_surface_slice(-1)

    @on(Button.Pressed, "#options-vol-term-next")
    def next_vol_term(self) -> None:
        self._change_surface_slice(1)

    @on(Button.Pressed, "#options-vol-popout")
    def popout_volatility(self) -> None:
        if self.surface is not None:
            self.post_message(self.PopOutRequested(self.surface.symbol))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not self._is_volatility_pointer_event(event) or event.button != 1:
            return
        self._surface_dragging = True
        if self.vol_mode == "SKEW":
            self._track_skew_pointer(event)
        self.capture_mouse()
        self.focus()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._surface_dragging:
            return
        if self.vol_mode == "SURFACE":
            self.surface_azimuth = (self.surface_azimuth + event.delta_x * 2.4) % 360.0
            self.surface_elevation = max(-5.0, min(80.0, self.surface_elevation - event.delta_y * 2.0))
        elif self.vol_mode == "SKEW":
            low, high = self._skew_range()
            self.skew_center = max(0.55, min(1.45, self.skew_center - event.delta_x * (high - low) / 90.0))
        else:
            return
        self._schedule_surface_draw()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._surface_dragging:
            return
        self._surface_dragging = False
        self.release_mouse()
        self._draw_volatility()
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if not self._is_volatility_pointer_event(event):
            return
        if self.vol_mode == "SURFACE":
            self.surface_zoom = min(self.surface_zoom * 1.12, 2.5)
        elif self.vol_mode == "SKEW":
            self.skew_zoom = min(self.skew_zoom * 1.18, 4.0)
        self._draw_volatility()
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if not self._is_volatility_pointer_event(event):
            return
        if self.vol_mode == "SURFACE":
            self.surface_zoom = max(self.surface_zoom / 1.12, 0.65)
        elif self.vol_mode == "SKEW":
            self.skew_zoom = max(self.skew_zoom / 1.18, 0.75)
        self._draw_volatility()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if self.mode != "OVDV" or self.vol_mode not in {"SURFACE", "SKEW"}:
            return
        handled = True
        if self.vol_mode == "SURFACE":
            if event.key == "left":
                self.surface_azimuth -= 8.0
            elif event.key == "right":
                self.surface_azimuth += 8.0
            elif event.key == "up":
                self.surface_elevation = min(self.surface_elevation + 5.0, 80.0)
            elif event.key == "down":
                self.surface_elevation = max(self.surface_elevation - 5.0, -5.0)
            elif event.key in {"plus", "equal_sign"}:
                self.surface_zoom = min(self.surface_zoom * 1.12, 2.5)
            elif event.key in {"minus", "underscore"}:
                self.surface_zoom = max(self.surface_zoom / 1.12, 0.65)
            elif event.key == "r":
                self._reset_surface_camera(redraw=False)
            else:
                handled = False
        else:
            low, high = self._skew_range()
            if event.key == "left":
                self.skew_center = max(0.55, self.skew_center - (high - low) * 0.08)
            elif event.key == "right":
                self.skew_center = min(1.45, self.skew_center + (high - low) * 0.08)
            elif event.key in {"up", "plus", "equal_sign"}:
                self.skew_zoom = min(self.skew_zoom * 1.18, 4.0)
            elif event.key in {"down", "minus", "underscore"}:
                self.skew_zoom = max(self.skew_zoom / 1.18, 0.75)
            elif event.key == "r":
                self._reset_skew_view(redraw=False)
            else:
                handled = False
        if handled:
            self._draw_volatility()
            event.stop()

    @on(DataTable.RowHighlighted, "#options-chain-table")
    def chain_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        selected = _contract_from_key(event.row_key.value)
        if selected is not None:
            self._select_monitor_contract(*selected)

    @on(DataTable.RowSelected, "#options-chain-table")
    def chain_row_selected(self, event: DataTable.RowSelected) -> None:
        selected = _contract_from_key(event.row_key.value)
        if selected is not None:
            self._select_monitor_contract(*selected)
            strike = selected[1]
            side = "call" if self.chain and strike >= (self.chain.spot or strike) else "put"
            self._request_pricer(side)

    def _show_mode(self, mode: str) -> None:
        selected = mode.upper()
        self.query_one("#options-chain-view").display = selected == "OMON"
        self.query_one("#options-pricer-view").display = selected == "OVME"
        self.query_one("#options-vol-view").display = selected == "OVDV"

    def _update_common_header(self, chain: OptionChain) -> None:
        change_style = "green" if (chain.underlying_change or 0) > 0 else "red" if (chain.underlying_change or 0) < 0 else "white"
        rate_text = f"{self.context.rate * 100:.3f}%" if self.context.rate_available else "--"
        self.query_one("#options-market-line", Static).update(
            f"{chain.name.upper()}  |  [bold white]{_price(chain.spot)} {chain.currency or '--'}[/]  "
            f"[{change_style}]{_signed(chain.underlying_change)} / {_percent(chain.underlying_change_percent)}[/]  |  "
            f"MKT {chain.market_status or '--'}  |  R {rate_text}  |  "
            f"Q {self.context.dividend_yield * 100:.3f}%  |  {chain.provider}"
        )
        self.query_one("#options-pricer-underlying", Static).update(
            f"UNDERLYING  [bold black on #d99116] {chain.symbol} EQUITY [/]  |  "
            f"UND PRICE  [bold black on #d99116] MID {_price(chain.spot)} {chain.currency or '--'} [/]  |  "
            f"TRADE DATE [bold black on #d99116] {date.today():%d/%m/%Y} [/]  |  "
            f"SETTLE [bold black on #d99116] {date.today():%d/%m/%Y} [/]"
        )

    def _populate_chain_table(self) -> None:
        table = self.query_one("#options-chain-table", DataTable)
        table.clear(columns=True)
        columns = (
            "C BID", "C ASK", "C LAST", "C IV", "C DELTA", "C VOL", "C OI",
            "STRIKE",
            "P BID", "P ASK", "P LAST", "P IV", "P DELTA", "P VOL", "P OI",
        )
        table.add_columns(*columns)
        chain = self.chain
        rate_text = f"{self.context.rate * 100:.3f}%" if self.context.rate_available else "--"
        chains = self.monitor_chains or ([chain] if chain is not None else [])
        if chain is None or not chains:
            return
        expiry = chain.selected_expiry
        self.query_one("#options-expiry-label", Static).update(
            f"{len(chains)} LISTED" if len(chains) > 1 else
            (f"{expiry:%d %b %Y} / {max((expiry - date.today()).days, 0)}D" if expiry else "--")
        )
        total_calls = sum(len(item.calls) for item in chains)
        total_puts = sum(len(item.puts) for item in chains)
        all_strikes = {
            contract.strike
            for item in chains
            for contract in (*item.calls, *item.puts)
        }
        forward = None
        if chain.spot is not None and expiry is not None and self.context.rate_available:
            days = max((expiry - date.today()).days, 0)
            forward = chain.spot * math.exp(
                (self.context.rate - self.context.dividend_yield) * days / 365.0
            )
        self.query_one("#options-chain-summary", Static).update(
            f"CALLS [bold white]{total_calls}[/]  |  PUTS [bold white]{total_puts}[/]  |  "
            f"CENTER [bold black on #d99116] {_price(chain.spot)} [/]  |  "
            f"STRIKES [bold white]{len(all_strikes)}[/]  |  EXP [bold white]{len(chains)}[/]  |  "
            f"CSIZE [bold white]100[/]  |  R [bold white]{rate_text}[/]  |  "
            f"IFWD [bold white]{_price(forward)}[/]  |  AS OF {chain.timestamp:%H:%M:%S} UTC"
        )
        selected_row: int | None = None
        row_index = 0
        for chain_index, item in enumerate(chains):
            item_expiry = item.selected_expiry
            days = max((item_expiry - date.today()).days, 0) if item_expiry else 0
            separator = [Text("", style="on #202327") for _ in columns]
            separator[0] = Text("CALLS", style="bold #d7d7d7 on #202327")
            separator[7] = Text(
                f"{item_expiry:%d %b %y} / {days}D" if item_expiry else "EXPIRY --",
                style="bold #ffb000 on #202327",
            )
            separator[8] = Text("PUTS", style="bold #d7d7d7 on #202327")
            table.add_row(*separator, key=f"expiry:{item_expiry.isoformat() if item_expiry else chain_index}")
            row_index += 1
            calls = {contract.strike: contract for contract in item.calls}
            puts = {contract.strike: contract for contract in item.puts}
            strikes = _centered_strikes(sorted(set(calls) | set(puts)), item.spot, 7)
            nearest_index = (
                min(range(len(strikes)), key=lambda index: abs(strikes[index] - (item.spot or strikes[index])))
                if strikes else 0
            )
            for index, strike in enumerate(strikes):
                call = calls.get(strike)
                put = puts.get(strike)
                strike_text = Text(
                    f"{strike:.2f}",
                    style="bold black on #d99116" if index == nearest_index else "bold #ffb000",
                )
                table.add_row(
                    *_contract_cells(call),
                    strike_text,
                    *_contract_cells(put),
                    key=f"contract:{item_expiry.isoformat() if item_expiry else ''}:{strike}",
                )
                if chain_index == 0 and index == nearest_index:
                    selected_row = row_index
                    self.selected_strike = strike
                row_index += 1
        if selected_row is not None:
            table.move_cursor(row=selected_row, column=7, animate=False)
            self._update_contract_detail()
        else:
            self.query_one("#options-contract-detail", Static).update(
                f"[yellow]{chain.message or 'No contracts returned for this expiry.'}[/]"
            )

    def _update_contract_detail(self) -> None:
        chain = self.chain
        if chain is None or self.selected_strike is None:
            return
        call = next((item for item in chain.calls if item.strike == self.selected_strike), None)
        put = next((item for item in chain.puts if item.strike == self.selected_strike), None)
        self.query_one("#options-contract-detail", Static).update(
            f"[bold #ffb000]{chain.selected_expiry:%d %b %Y}[/]\n"
            f"DAYS TO EXPIRY   [bold white]{max((chain.selected_expiry - date.today()).days, 0)}[/]\n"
            f"STRIKE           [bold black on #d99116] {self.selected_strike:.2f} [/]\n\n"
            f"[bold #d7d7d7]CALL[/]\n{_contract_detail(call)}\n\n"
            f"[bold #d7d7d7]PUT[/]\n{_contract_detail(put)}\n\n"
            "[dim]IV calculated from valid mid; vendor IV is shown only when the calculation is unavailable.[/]"
        )

    def _select_monitor_contract(self, expiry: date, strike: float) -> None:
        selected_chain = next(
            (item for item in self.monitor_chains if item.selected_expiry == expiry),
            None,
        )
        if selected_chain is not None:
            self.chain = selected_chain
        self.selected_strike = strike
        self._update_contract_detail()

    def _request_expiry(self, direction: int) -> None:
        chain = self.chain
        if chain is None or chain.selected_expiry not in chain.expirations:
            return
        index = chain.expirations.index(chain.selected_expiry)
        next_index = max(0, min(index + direction, len(chain.expirations) - 1))
        if next_index != index:
            self.post_message(
                self.FunctionRequested("OMON", chain.symbol, chain.expirations[next_index].isoformat())
            )

    def _request_pricer(self, option_type: str) -> None:
        if self.chain is None or self.selected_strike is None:
            return
        expiry = self.chain.selected_expiry.isoformat() if self.chain.selected_expiry else ""
        side = "C" if option_type == "call" else "P"
        self.post_message(
            self.FunctionRequested("OVME", self.chain.symbol, side, f"{self.selected_strike:g}", expiry)
        )

    def _load_market_contract(self) -> None:
        chain = self.chain
        if chain is None or chain.spot is None:
            return
        contracts = chain.calls if self.option_type == "call" else chain.puts
        if not contracts:
            return
        target = self.selected_strike or chain.spot
        contract = min(contracts, key=lambda item: abs(item.strike - target))
        self.selected_strike = contract.strike
        volatility = contract.calculated_implied_volatility or contract.vendor_implied_volatility or 0.20
        values = {
            "spot": f"{chain.spot:.4f}",
            "strike": f"{contract.strike:.4f}",
            "expiry": contract.expiry.isoformat(),
            "volatility": f"{volatility * 100:.4f}",
            "rate": f"{self.context.rate * 100:.4f}" if self.context.rate_available else "",
            "dividend": f"{self.context.dividend_yield * 100:.4f}",
            "premium": f"{contract.market_price:.4f}" if contract.market_price is not None else "",
            "quantity": self.query_one("#option-input-quantity", Input).value or "1",
        }
        for field, value in values.items():
            self.query_one(f"#option-input-{field}", Input).value = value

    def _pricer_values(self) -> dict[str, float]:
        expiry_text = self.query_one("#option-input-expiry", Input).value.strip()
        try:
            expiry = date.fromisoformat(expiry_text)
        except ValueError as exc:
            raise ValueError("Expiry must use YYYY-MM-DD") from exc
        days = (expiry - date.today()).days
        if days <= 0:
            raise ValueError("Expiry must be after today")
        quantity = _float_input(self, "quantity")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        return {
            "spot": _positive_input(self, "spot"),
            "strike": _positive_input(self, "strike"),
            "volatility": _positive_input(self, "volatility") / 100.0,
            "rate": _float_input(self, "rate") / 100.0,
            "dividend": _float_input(self, "dividend") / 100.0,
            "time": days / 365.0,
            "days": float(days),
            "quantity": quantity,
        }

    def _calculate(self) -> None:
        try:
            values = self._pricer_values()
            result = option_analytics(
                self.option_type,
                values["spot"],
                values["strike"],
                values["rate"],
                values["volatility"],
                values["time"],
                values["dividend"],
            )
        except ValueError as exc:
            self._set_pricer_error(str(exc))
            return
        multiplier = values["quantity"] * 100.0
        rows = (
            ("PRICE (TOTAL)", f"{result.price * multiplier:,.2f}"),
            ("PRICE (SHARE)", f"{result.price:,.4f}"),
            ("PRICE (%)", f"{result.price / values['spot'] * 100:,.4f}"),
            ("CURRENCY", self.chain.currency if self.chain else "--"),
            ("DELTA (%)", f"{result.delta * 100:,.4f}"),
            ("GAMMA (%)", f"{result.gamma * 100:,.4f}"),
            ("VEGA / 1 VOL PT", f"{result.vega:,.6f}"),
            ("THETA / DAY", f"{result.theta:,.6f}"),
            ("RHO / 1 RATE PT", f"{result.rho:,.6f}"),
            ("TIME VALUE", f"{result.time_value:,.4f}"),
            ("GEARING", _number(result.gearing, 4)),
            ("BREAK-EVEN (%)", f"{abs(result.break_even / values['spot'] - 1) * 100:,.4f}"),
            ("FORWARD", f"{result.forward:,.4f}"),
            ("INTRINSIC", f"{result.intrinsic_value:,.4f}"),
            ("VANNA / VOLGA", f"{result.vanna:,.4f} / {result.volga:,.4f}"),
        )
        table = Table.grid(expand=False, padding=(0, 1))
        table.add_column(style="#d7d7d7", width=22, no_wrap=True)
        table.add_column(justify="right", style="bold black on #d99116", width=18, no_wrap=True)
        for label, value in rows:
            table.add_row(label, f" {value} ")
        self.query_one("#options-result-grid", Static).update(table)
        self.query_one("#options-deal-title", Static).update(
            f"EUROPEAN VANILLA  /  {self.option_type.upper()}  /  BUY"
        )
        self.query_one("#options-conventions-grid", Static).update(
            "STYLE       [black on #d99116] VANILLA       [/]\n"
            "EXERCISE    [black on #d99116] EUROPEAN      [/]\n"
            f"CALL / PUT  [black on #d99116] {self.option_type.upper():<13}[/]\n"
            "DIRECTION   [black on #d99116] BUY           [/]\n"
            "MODEL       [black on #d99116] BS CONTINUOUS [/]\n"
            "MULTIPLIER  [black on #d99116] 100           [/]\n"
            "DAY COUNT   [black on #d99116] ACT / 365     [/]"
        )
        self.query_one("#options-model-note", Static).update(
            f"EUROPEAN / BLACK-SCHOLES  |  R {values['rate'] * 100:.4f}% ({self.context.rate_source})  |  "
            f"Q {values['dividend'] * 100:.4f}% ({self.context.dividend_source})"
        )

    def _set_pricer_error(self, message: str) -> None:
        self.query_one("#options-result-grid", Static).update(f"[bold red]INPUT ERROR[/]  {message}")

    def _populate_vol_table(self) -> None:
        table = self.query_one("#options-vol-table-grid", DataTable)
        table.clear(columns=True)
        surface = self.surface
        if surface is None:
            return
        table.add_columns("EXPIRY", "DTE", *(f"{value * 100:.0f}% MNY" for value in surface.moneyness_grid))
        for slice_ in surface.slices:
            table.add_row(
                slice_.expiry.isoformat(),
                str(slice_.days_to_expiry),
                *(
                    f"{slice_.grid[target] * 100:.2f}%" if slice_.grid.get(target) is not None else "--"
                    for target in surface.moneyness_grid
                ),
                key=f"expiry:{slice_.expiry.isoformat()}",
            )

    def _draw_volatility(self) -> None:
        image = self.query_one("#options-vol-image", Image)
        table = self.query_one("#options-vol-table-grid", DataTable)
        table.display = self.vol_mode == "TABLE"
        image.display = self.vol_mode != "TABLE"
        self._update_vol_method()
        if self.vol_mode == "TABLE" or self.surface is None:
            return
        try:
            image.image = build_volatility_image(
                self.surface,
                self.vol_mode,
                elevation=self.surface_elevation,
                azimuth=self.surface_azimuth,
                zoom=self.surface_zoom,
                selected_slice=self.surface_slice_index,
                moneyness_range=self._skew_range(),
                tracked_moneyness=self.skew_tracked_moneyness,
            )
        except ValueError as exc:
            image.image = None
            self.query_one("#options-vol-method", Static).update(f"NO SURFACE: {exc}")

    def _is_volatility_pointer_event(self, event: events.MouseEvent) -> bool:
        return (
            self.mode == "OVDV"
            and self.vol_mode in {"SURFACE", "SKEW"}
            and getattr(event.widget, "id", None) == "options-vol-image"
        )

    def _schedule_surface_draw(self) -> None:
        if self._surface_render_pending:
            return
        self._surface_render_pending = True
        self.set_timer(0.05, self._flush_surface_draw)

    def _flush_surface_draw(self) -> None:
        self._surface_render_pending = False
        if self._surface_dragging and self.vol_mode in {"SURFACE", "SKEW"}:
            self._draw_volatility()

    def _reset_surface_camera(self, *, redraw: bool) -> None:
        self.surface_elevation = 14.0
        self.surface_azimuth = -48.0
        self.surface_zoom = 1.0
        if redraw and self.surface is not None and self.vol_mode == "SURFACE":
            self._draw_volatility()

    def _reset_skew_view(self, *, redraw: bool) -> None:
        self.surface_slice_index = 0
        self.skew_center = 1.0
        self.skew_zoom = 1.0
        self.skew_tracked_moneyness = 1.0
        if redraw and self.surface is not None and self.vol_mode == "SKEW":
            self._draw_volatility()

    def _skew_range(self) -> tuple[float, float]:
        half_span = 0.25 / max(self.skew_zoom, 0.75)
        return self.skew_center - half_span, self.skew_center + half_span

    def _track_skew_pointer(self, event: events.MouseEvent) -> None:
        image = self.query_one("#options-vol-image", Image)
        main_width = max(int(image.size.width * 0.68), 1)
        ratio = max(0.0, min(float(event.x) / main_width, 1.0))
        low, high = self._skew_range()
        self.skew_tracked_moneyness = low + ratio * (high - low)
        self._draw_volatility()

    def _change_surface_slice(self, amount: int) -> None:
        if self.surface is None or not self.surface.slices:
            return
        self.surface_slice_index = max(
            0,
            min(self.surface_slice_index + amount, len(self.surface.slices) - 1),
        )
        self._draw_volatility()

    def _update_vol_method(self) -> None:
        if self.vol_mode == "SURFACE":
            term = self._selected_surface_term()
            message = (
                f"DRAG ROTATE  |  WHEEL ZOOM  |  ELEV {self.surface_elevation:.0f}  "
                f"AZIM {self.surface_azimuth % 360:.0f}  ZOOM {self.surface_zoom:.2f}x  |  TERM {term}"
            )
        elif self.vol_mode == "SKEW":
            low, high = self._skew_range()
            message = (
                f"CLICK TRACK  |  DRAG PAN  |  WHEEL ZOOM  |  {low * 100:.0f}-{high * 100:.0f}%  "
                f"TRACK {self.skew_tracked_moneyness * 100:.1f}%  |  TERM {self._selected_surface_term()}"
            )
        else:
            message = (
                "TERM STRUCTURE  |  OBSERVED EXPIRIES"
                if self.vol_mode == "TERM"
                else "INTERPOLATED ONLY BETWEEN OBSERVED STRIKES"
            )
        self.query_one("#options-vol-method", Static).update(message)

    def _selected_surface_term(self) -> str:
        if self.surface is None or not self.surface.slices:
            return "--"
        index = max(0, min(self.surface_slice_index, len(self.surface.slices) - 1))
        slice_ = self.surface.slices[index]
        return f"{slice_.days_to_expiry}D / {slice_.expiry:%d %b %y}"

    def _sync_buttons(self) -> None:
        self.query_one("#options-call", Button).set_class(self.option_type == "call", "selected")
        self.query_one("#options-put", Button).set_class(self.option_type == "put", "selected")
        for mode in ("SKEW", "SURFACE", "TERM", "TABLE"):
            self.query_one(f"#options-vol-{mode.lower()}", Button).set_class(self.vol_mode == mode, "selected")


def _contract_cells(contract: OptionContract | None) -> tuple[Text | str, ...]:
    if contract is None:
        return ("--",) * 7
    iv = contract.calculated_implied_volatility
    iv_style = "cyan"
    if iv is None:
        iv = contract.vendor_implied_volatility
        iv_style = "dim"
    return (
        _cell(contract.bid),
        _cell(contract.ask),
        _cell(contract.last),
        Text(f"{iv * 100:.2f}" if iv is not None else "--", style=iv_style),
        _cell(contract.delta, 3),
        _integer_cell(contract.volume),
        _integer_cell(contract.open_interest),
    )


def _cell(value: float | None, decimals: int = 2) -> Text:
    return Text(f"{value:,.{decimals}f}" if value is not None else "--", style="white")


def _integer_cell(value: int | None) -> Text:
    return Text(f"{value:,}" if value is not None else "--", style="white")


def _contract_summary(contract: OptionContract | None) -> str:
    if contract is None:
        return "--"
    iv = contract.calculated_implied_volatility or contract.vendor_implied_volatility
    return (
        f"BID {_price(contract.bid)}  ASK {_price(contract.ask)}  LAST {_price(contract.last)}  "
        f"IV {iv * 100:.2f}%  OI {contract.open_interest or 0:,}"
        if iv is not None
        else f"BID {_price(contract.bid)}  ASK {_price(contract.ask)}  LAST {_price(contract.last)}  IV --"
    )


def _contract_detail(contract: OptionContract | None) -> str:
    if contract is None:
        return "BID / ASK        -- / --\nLAST             --\nIV / DELTA       -- / --\nVOLUME / OI      -- / --"
    iv = contract.calculated_implied_volatility or contract.vendor_implied_volatility
    return (
        f"BID / ASK        {_price(contract.bid)} / {_price(contract.ask)}\n"
        f"LAST             {_price(contract.last)}\n"
        f"IV / DELTA       {_percent_plain(iv)} / {_number(contract.delta, 4)}\n"
        f"VOLUME / OI      {contract.volume or 0:,} / {contract.open_interest or 0:,}"
    )


def _nearest_strike(chain: OptionChain) -> float | None:
    strikes = [contract.strike for contract in (*chain.calls, *chain.puts)]
    if not strikes:
        return None
    spot = chain.spot or strikes[0]
    return min(strikes, key=lambda value: abs(value - spot))


def _contract_from_key(value: object) -> tuple[date, float] | None:
    text = str(value)
    if not text.startswith("contract:"):
        return None
    try:
        _, expiry_text, strike_text = text.split(":", maxsplit=2)
        return date.fromisoformat(expiry_text), float(strike_text)
    except ValueError:
        return None


def _centered_strikes(strikes: list[float], spot: float | None, limit: int) -> list[float]:
    if len(strikes) <= limit:
        return strikes
    center = min(
        range(len(strikes)),
        key=lambda index: abs(strikes[index] - (spot if spot is not None else strikes[index])),
    )
    start = max(0, min(center - limit // 2, len(strikes) - limit))
    return strikes[start : start + limit]


def _float_input(workspace: OptionsWorkspace, field: str) -> float:
    raw = workspace.query_one(f"#option-input-{field}", Input).value.strip().replace(",", "")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{field.upper()} must be numeric") from exc


def _positive_input(workspace: OptionsWorkspace, field: str) -> float:
    value = _float_input(workspace, field)
    if value <= 0:
        raise ValueError(f"{field.upper()} must be positive")
    return value


def _price(value: float | None) -> str:
    return f"{value:,.4f}" if value is not None else "--"


def _signed(value: float | None) -> str:
    return f"{value:+,.4f}" if value is not None else "--"


def _percent(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "--"


def _percent_plain(value: float | None) -> str:
    return f"{value * 100:.2f}%" if value is not None else "--"


def _number(value: float | None, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}" if value is not None else "--"
