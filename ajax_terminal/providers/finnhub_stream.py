from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from ajax_terminal.analytics.live_bars import TradeTick


def parse_trade_message(message: str) -> list[TradeTick]:
    """Normalize one Finnhub WebSocket frame."""
    ticks: list[TradeTick] = []
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return ticks
    if payload.get("type") != "trade" or not isinstance(payload.get("data"), list):
        return ticks
    for node in payload["data"]:
        if not isinstance(node, dict):
            continue
        try:
            ticks.append(
                TradeTick(
                    symbol=str(node["s"]),
                    price=float(node["p"]),
                    timestamp_ms=int(node["t"]),
                    volume=float(node.get("v") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return ticks


class FinnhubThreadStream:
    """Small websocket-client transport for the Textual process."""

    def __init__(
        self,
        api_key: str,
        symbol: str,
        on_trade: Callable[[TradeTick], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.api_key = api_key.strip()
        self.symbol = symbol.strip().upper()
        self.on_trade = on_trade
        self.on_status = on_status
        self._enabled = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: Any = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._enabled.set()
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run, name=f"finnhub-{self.symbol}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._enabled.clear()
        self._stopped.set()
        socket = self._socket
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            import websocket
        except ImportError:
            self.on_status("INSTALL WEBSOCKET-CLIENT / AUTO 30S")
            return
        while self._enabled.is_set():
            self.on_status("FINNHUB CONNECTING")
            self._socket = websocket.WebSocketApp(
                f"wss://ws.finnhub.io?token={self.api_key}",
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=lambda _ws, _error: self.on_status("FINNHUB ERROR / RECONNECTING"),
                on_close=lambda _ws, _code, _reason: None,
            )
            self._socket.run_forever(ping_interval=20, ping_timeout=10, skip_utf8_validation=True)
            self._socket = None
            if self._enabled.is_set():
                self.on_status("FINNHUB RECONNECTING")
                self._stopped.wait(3.0)

    def _on_open(self, socket) -> None:
        socket.send(json.dumps({"type": "subscribe", "symbol": self.symbol}, separators=(",", ":")))
        self.on_status("FINNHUB STREAM CONNECTED / 2HZ UI")

    def _on_message(self, _socket, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if payload.get("type") == "error":
            self.on_status("FINNHUB ENTITLEMENT ERROR / AUTO 30S")
            return
        for tick in parse_trade_message(message):
            self.on_trade(tick)
