from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ajax_terminal.analytics.options import implied_volatility, option_analytics
from ajax_terminal.charts.theme import AJAX_AMBER, AJAX_MUTED, AJAX_RED, AJAX_TEXT
from ajax_terminal.models.options import OptionChain, OptionContract, OptionMarketContext
from ajax_terminal.services.market_service import MarketService
from ajax_terminal.services.options_service import OptionsService


@dataclass(slots=True)
class OptionsDesktopLoad:
    mode: str
    chains: list[OptionChain]
    context: OptionMarketContext
    option_type: str = "call"
    strike: float | None = None

    @property
    def chain(self) -> OptionChain:
        return self.chains[0]


def _parse_expiry(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def load_option_monitor(symbol: str, expiry: str | None = None) -> OptionsDesktopLoad:
    service = OptionsService(MarketService())
    chains, context = asyncio.run(service.option_monitor(symbol.upper(), _parse_expiry(expiry)))
    return OptionsDesktopLoad("OMON", chains, context)


def load_option_valuation(
    symbol: str,
    side: str | None = None,
    strike: str | None = None,
    expiry: str | None = None,
) -> OptionsDesktopLoad:
    service = OptionsService(MarketService())
    chain, context = asyncio.run(service.chain_with_context(symbol.upper(), _parse_expiry(expiry)))
    try:
        parsed_strike = float(strike) if strike else None
    except ValueError:
        parsed_strike = None
    return OptionsDesktopLoad(
        "OVME",
        [chain],
        context,
        "put" if str(side or "").upper() in {"P", "PUT"} else "call",
        parsed_strike,
    )


class OptionsDesktopWorkspace(QFrame):
    command_requested = Signal(str)

    def __init__(self, loaded: OptionsDesktopLoad) -> None:
        super().__init__()
        self.loaded = loaded
        self.chain = loaded.chain
        self.context = loaded.context
        self.option_type = loaded.option_type
        self.setObjectName("optionsDesktopWorkspace")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(5)
        root.addWidget(self._function_bar())

        self.market_line = QLabel(self._market_text())
        self.market_line.setStyleSheet(f"color:{AJAX_TEXT};padding:2px 4px")
        root.addWidget(self.market_line)

        if loaded.mode == "OMON":
            root.addWidget(self._monitor_view(), 1)
        else:
            root.addWidget(self._valuation_view(), 1)

    def _function_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("terminalSubnav")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        for command, label in (
            ("OMON", "1) OMON  OPTION MONITOR"),
            ("OVME", "2) OVME  OPTION VALUATION"),
            ("OVDV", "3) OVDV  VOLATILITY"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(self.loaded.mode == command)
            button.setFixedHeight(27)
            button.setMinimumWidth(210)
            button.clicked.connect(
                lambda _checked=False, command=command: self.command_requested.emit(
                    f"{command} {self.chain.symbol}"
                )
            )
            row.addWidget(button)
        row.addStretch(1)
        return bar

    def _market_text(self) -> str:
        expiry = self.chain.selected_expiry.isoformat() if self.chain.selected_expiry else "--"
        spot = _number(self.chain.spot, 4)
        rate = f"{self.context.rate * 100:.3f}%" if self.context.rate_available else "--"
        return (
            f"{self.chain.name.upper()}  |  SPOT {spot} {self.chain.currency or '--'}  |  "
            f"EXP {expiry}  |  RATE {rate}  |  "
            f"DIV {self.context.dividend_yield * 100:.3f}%  |  "
            f"{self.chain.provider} {str(self.chain.quality).upper()}"
        )

    def _monitor_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        controls.addWidget(_section_label("LISTED OPTION CHAIN"))
        controls.addStretch(1)
        controls.addWidget(QLabel("EXPIRY"))
        expiry = QComboBox()
        expiry.setMinimumWidth(140)
        expiry.blockSignals(True)
        for item in self.chain.expirations:
            expiry.addItem(item.isoformat(), item.isoformat())
        selected = self.chain.selected_expiry.isoformat() if self.chain.selected_expiry else ""
        if selected:
            index = expiry.findData(selected)
            if index >= 0:
                expiry.setCurrentIndex(index)
        expiry.blockSignals(False)
        expiry.currentIndexChanged.connect(
            lambda _index: self.command_requested.emit(
                f"OMON {self.chain.symbol} {expiry.currentData()}"
            )
        )
        controls.addWidget(expiry)
        refresh = QPushButton("REFRESH")
        refresh.clicked.connect(
            lambda: self.command_requested.emit(
                f"OMON {self.chain.symbol} {selected}".strip()
            )
        )
        controls.addWidget(refresh)
        layout.addLayout(controls)

        if not self.chain.calls and not self.chain.puts:
            message = QLabel(self.chain.message or "NO REAL OPTION CHAIN AVAILABLE")
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message.setStyleSheet(f"color:{AJAX_AMBER};font-weight:bold")
            layout.addWidget(message, 1)
            return page

        table = QTableWidget()
        table.setObjectName("optionChainTable")
        headers = (
            "C BID", "C ASK", "C LAST", "C IV", "C DELTA", "C VOL", "C OI",
            "STRIKE",
            "P BID", "P ASK", "P LAST", "P IV", "P DELTA", "P VOL", "P OI",
        )
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(68)
        table.setAlternatingRowColors(True)

        calls = {item.strike: item for item in self.chain.calls}
        puts = {item.strike: item for item in self.chain.puts}
        strikes = sorted(set(calls) | set(puts))
        table.setRowCount(len(strikes))
        for row, strike in enumerate(strikes):
            call = calls.get(strike)
            put = puts.get(strike)
            values = (*_contract_values(call), _number(strike, 2), *_contract_values(put))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor(AJAX_AMBER if column == 7 else AJAX_TEXT))
                table.setItem(row, column, item)
        table.cellDoubleClicked.connect(
            lambda row, column: self._open_contract(strikes[row], "C" if column < 7 else "P")
        )
        layout.addWidget(table, 1)

        footer = QLabel(
            "DOUBLE-CLICK CALL OR PUT VALUES FOR OVME  |  "
            f"{len(self.chain.calls)} CALLS  |  {len(self.chain.puts)} PUTS"
        )
        footer.setStyleSheet(f"color:{AJAX_MUTED};padding:2px 4px")
        layout.addWidget(footer)
        return page

    def _open_contract(self, strike: float, side: str) -> None:
        expiry = self.chain.selected_expiry.isoformat() if self.chain.selected_expiry else ""
        self.command_requested.emit(f"OVME {self.chain.symbol} {side} {strike:g} {expiry}".strip())

    def _valuation_view(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        form_panel = QFrame()
        form_panel.setObjectName("terminalPanel")
        form = QGridLayout(form_panel)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.addWidget(_section_label("OPTION INPUTS"), 0, 0, 1, 2)

        contract = self._initial_contract()
        strike = self.loaded.strike or (contract.strike if contract else self.chain.spot) or 0.0
        volatility = _contract_volatility(contract) or 0.20
        expiry = self.chain.selected_expiry or (date.today())
        values = {
            "spot": _number(self.chain.spot, 6, plain=True),
            "strike": _number(strike, 6, plain=True),
            "expiry": expiry.isoformat(),
            "volatility": f"{volatility * 100:.4f}",
            "rate": f"{self.context.rate * 100:.4f}" if self.context.rate_available else "",
            "dividend": f"{self.context.dividend_yield * 100:.4f}",
            "quantity": "1",
        }
        labels = (
            ("spot", "SPOT"), ("strike", "STRIKE"), ("expiry", "EXPIRY YYYY-MM-DD"),
            ("volatility", "VOLATILITY %"), ("rate", "RATE %"),
            ("dividend", "DIVIDEND %"), ("quantity", "QUANTITY"),
        )
        self.inputs: dict[str, QLineEdit] = {}
        for row, (key, label) in enumerate(labels, start=1):
            form.addWidget(QLabel(label), row, 0)
            field = QLineEdit(values[key])
            field.setObjectName(f"optionInput_{key}")
            field.returnPressed.connect(self._calculate)
            self.inputs[key] = field
            form.addWidget(field, row, 1)

        side_row = QHBoxLayout()
        self.side_group = QButtonGroup(self)
        for label, side in (("CALL", "call"), ("PUT", "put")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(self.option_type == side)
            self.side_group.addButton(button)
            button.clicked.connect(lambda _checked=False, side=side: self._set_side(side))
            side_row.addWidget(button)
        form.addLayout(side_row, len(labels) + 1, 0, 1, 2)

        actions = QHBoxLayout()
        calculate = QPushButton("CALCULATE")
        calculate.clicked.connect(self._calculate)
        actions.addWidget(calculate)
        use_market = QPushButton("USE MARKET")
        use_market.clicked.connect(self._use_market)
        actions.addWidget(use_market)
        solve_iv = QPushButton("SOLVE IV")
        solve_iv.clicked.connect(self._solve_iv)
        actions.addWidget(solve_iv)
        form.addLayout(actions, len(labels) + 2, 0, 1, 2)
        form.setRowStretch(len(labels) + 3, 1)
        layout.addWidget(form_panel, 0)

        result_panel = QFrame()
        result_panel.setObjectName("terminalPanel")
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(10, 8, 10, 8)
        result_layout.addWidget(_section_label("VALUATION / RISK"))
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(("MEASURE", "VALUE"))
        self.result_table.verticalHeader().hide()
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        result_layout.addWidget(self.result_table, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color:{AJAX_MUTED}")
        result_layout.addWidget(self.message)
        layout.addWidget(result_panel, 1)
        self._calculate()
        return page

    def _set_side(self, side: str) -> None:
        self.option_type = side
        self._calculate()

    def _initial_contract(self) -> OptionContract | None:
        contracts = self.chain.calls if self.option_type == "call" else self.chain.puts
        if not contracts:
            return None
        target = self.loaded.strike or self.chain.spot or contracts[0].strike
        return min(contracts, key=lambda item: abs(item.strike - target))

    def _use_market(self) -> None:
        contract = self._initial_contract()
        if contract is None:
            self._set_error("NO LISTED MARKET CONTRACT IS AVAILABLE")
            return
        self.inputs["strike"].setText(f"{contract.strike:g}")
        volatility = _contract_volatility(contract)
        if volatility:
            self.inputs["volatility"].setText(f"{volatility * 100:.4f}")
        self._calculate()

    def _solve_iv(self) -> None:
        contract = self._initial_contract()
        market_price = contract.market_price if contract else None
        if market_price is None:
            self._set_error("NO VALID BID/ASK OR LAST PRICE FOR IMPLIED VOLATILITY")
            return
        try:
            inputs = self._input_values()
            volatility = implied_volatility(
                self.option_type,
                market_price,
                inputs["spot"],
                inputs["strike"],
                inputs["rate"],
                inputs["time"],
                inputs["dividend"],
            )
            self.inputs["volatility"].setText(f"{volatility * 100:.4f}")
            self._calculate()
        except ValueError as exc:
            self._set_error(str(exc).upper())

    def _input_values(self) -> dict[str, float]:
        expiry = date.fromisoformat(self.inputs["expiry"].text().strip())
        time_years = max((expiry - date.today()).days / 365.0, 1 / 365.0)
        values = {
            "spot": float(self.inputs["spot"].text().replace(",", "")),
            "strike": float(self.inputs["strike"].text().replace(",", "")),
            "volatility": float(self.inputs["volatility"].text().replace(",", "")) / 100.0,
            "rate": float(self.inputs["rate"].text().replace(",", "")) / 100.0,
            "dividend": float(self.inputs["dividend"].text().replace(",", "")) / 100.0,
            "quantity": float(self.inputs["quantity"].text().replace(",", "")),
            "time": time_years,
        }
        if values["spot"] <= 0 or values["strike"] <= 0 or values["volatility"] <= 0:
            raise ValueError("spot, strike and volatility must be positive")
        return values

    def _calculate(self) -> None:
        try:
            inputs = self._input_values()
            result = option_analytics(
                self.option_type,
                inputs["spot"],
                inputs["strike"],
                inputs["rate"],
                inputs["volatility"],
                inputs["time"],
                inputs["dividend"],
            )
        except (ValueError, OverflowError) as exc:
            self._set_error(str(exc).upper())
            return
        quantity = inputs["quantity"]
        rows = (
            ("MODEL PRICE", result.price * quantity),
            ("INTRINSIC VALUE", result.intrinsic_value * quantity),
            ("TIME VALUE", result.time_value * quantity),
            ("FORWARD", result.forward),
            ("BREAK EVEN", result.break_even),
            ("DELTA", result.delta * quantity),
            ("GAMMA", result.gamma * quantity),
            ("THETA / DAY", result.theta * quantity),
            ("VEGA / 1 VOL PT", result.vega * quantity),
            ("RHO / 1 RATE PT", result.rho * quantity),
            ("VANNA", result.vanna * quantity),
            ("VOLGA", result.volga * quantity),
        )
        self.result_table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor("#4fb3ce"))
            value_item = QTableWidgetItem(f"{value:,.6f}")
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_item.setForeground(QColor(AJAX_TEXT))
            self.result_table.setItem(row, 0, name_item)
            self.result_table.setItem(row, 1, value_item)
        self.message.setStyleSheet(f"color:{AJAX_MUTED}")
        self.message.setText(
            f"EUROPEAN BLACK-SCHOLES  |  {self.option_type.upper()}  |  "
            f"RATE: {self.context.rate_source}  |  DIVIDEND: {self.context.dividend_source}"
        )

    def _set_error(self, message: str) -> None:
        self.message.setStyleSheet(f"color:{AJAX_RED};font-weight:bold")
        self.message.setText(f"INPUT ERROR  |  {message}")


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color:#4fb3ce;font-weight:bold;padding:3px 4px")
    return label


def _number(value: float | int | None, decimals: int, *, plain: bool = False) -> str:
    if value is None:
        return ""
    return f"{value:.{decimals}f}" if plain else f"{value:,.{decimals}f}"


def _contract_volatility(contract: OptionContract | None) -> float | None:
    if contract is None:
        return None
    return contract.calculated_implied_volatility or contract.vendor_implied_volatility


def _contract_values(contract: OptionContract | None) -> tuple[str, ...]:
    if contract is None:
        return ("--",) * 7
    volatility = _contract_volatility(contract)
    return (
        _number(contract.bid, 3),
        _number(contract.ask, 3),
        _number(contract.last, 3),
        f"{volatility * 100:.2f}%" if volatility is not None else "--",
        _number(contract.delta, 3),
        f"{contract.volume:,}" if contract.volume is not None else "--",
        f"{contract.open_interest:,}" if contract.open_interest is not None else "--",
    )
