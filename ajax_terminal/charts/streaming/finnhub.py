from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from ajax_terminal.analytics.live_bars import TradeTick
from ajax_terminal.providers.finnhub_stream import parse_trade_message


class FinnhubTradeStream(QObject):
    trade_received = Signal(object)
    status_changed = Signal(str)

    def __init__(self, api_key: str, symbol: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.api_key = api_key.strip()
        self.symbol = symbol.strip().upper()
        self.socket = QWebSocket("THRIVEBERG Terminal")
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.textMessageReceived.connect(self._on_message)
        self.socket.errorOccurred.connect(self._on_error)
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.setInterval(3_000)
        self.reconnect_timer.timeout.connect(self.start)
        self.enabled = False

    def start(self) -> None:
        if not self.api_key or not self.symbol:
            self.status_changed.emit("NO FINNHUB KEY")
            return
        self.enabled = True
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        self.status_changed.emit("FINNHUB CONNECTING")
        self.socket.open(QUrl(f"wss://ws.finnhub.io?token={self.api_key}"))

    def stop(self) -> None:
        self.enabled = False
        self.reconnect_timer.stop()
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self.socket.close()

    def _on_connected(self) -> None:
        payload = json.dumps({"type": "subscribe", "symbol": self.symbol}, separators=(",", ":"))
        self.socket.sendTextMessage(payload)
        self.status_changed.emit("FINNHUB STREAM CONNECTED")

    def _on_disconnected(self) -> None:
        if self.enabled:
            self.status_changed.emit("FINNHUB RECONNECTING")
            self.reconnect_timer.start()

    def _on_error(self, _error) -> None:
        self.status_changed.emit("FINNHUB STREAM ERROR / AUTO 30S ACTIVE")

    def _on_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if payload.get("type") == "error":
            self.status_changed.emit("FINNHUB ENTITLEMENT ERROR / AUTO 30S ACTIVE")
            return
        for tick in parse_trade_message(message):
            self.trade_received.emit(tick)
