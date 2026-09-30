from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ajax_terminal.instruments import INSTRUMENT_REGISTRY
from ajax_terminal.storage.database import DEFAULT_DB_PATH, get_connection


class SQLiteCache:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        with get_connection(self.path) as connection:
            row = connection.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None or row["expires_at"] < time.time():
            return None
        return json.loads(row["value"])

    def get_stale_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        with get_connection(self.path) as connection:
            row = connection.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def set_json(self, key: str, value: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True)
        with get_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO cache (key, value, expires_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (key, payload, expires_at, updated_at),
            )
            connection.commit()


class WatchlistStore:
    DEFAULT = INSTRUMENT_REGISTRY.default_watchlist()

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def symbols(self, name: str = "DEFAULT") -> list[str]:
        clean_name = self._name(name)
        with get_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT symbol FROM watchlists WHERE name = ? ORDER BY position, symbol",
                (clean_name,),
            ).fetchall()
        if not rows and clean_name == "DEFAULT":
            self.replace("DEFAULT", self.DEFAULT)
            return list(self.DEFAULT)
        return [row["symbol"] for row in rows]

    def names(self) -> list[str]:
        with get_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT name FROM watchlist_meta
                UNION
                SELECT DISTINCT name FROM watchlists
                ORDER BY name
                """
            ).fetchall()
        names = [row["name"] for row in rows]
        if "DEFAULT" not in names:
            self.create("DEFAULT")
            names.insert(0, "DEFAULT")
        elif names[0] != "DEFAULT":
            names.remove("DEFAULT")
            names.insert(0, "DEFAULT")
        return names

    def create(self, name: str) -> str:
        clean_name = self._name(name)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self.path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO watchlist_meta (name, created_at, updated_at) VALUES (?, ?, ?)",
                (clean_name, now, now),
            )
            connection.commit()
        return clean_name

    def add(self, symbol: str, name: str = "DEFAULT") -> None:
        clean_name = self.create(name)
        symbols = self.symbols(clean_name)
        if symbol.upper() in symbols:
            return
        with get_connection(self.path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO watchlists (name, symbol, position) VALUES (?, ?, ?)",
                (clean_name, symbol.upper(), len(symbols)),
            )
            connection.execute(
                "UPDATE watchlist_meta SET updated_at = ? WHERE name = ?",
                (datetime.now(timezone.utc).isoformat(), clean_name),
            )
            connection.commit()

    def remove(self, symbol: str, name: str = "DEFAULT") -> None:
        clean_name = self._name(name)
        with get_connection(self.path) as connection:
            connection.execute(
                "DELETE FROM watchlists WHERE name = ? AND symbol = ?",
                (clean_name, symbol.upper()),
            )
            connection.execute(
                "UPDATE watchlist_meta SET updated_at = ? WHERE name = ?",
                (datetime.now(timezone.utc).isoformat(), clean_name),
            )
            connection.commit()

    def replace(self, name: str, symbols: list[str]) -> None:
        clean_name = self.create(name)
        unique = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM watchlists WHERE name = ?", (clean_name,))
            connection.executemany(
                "INSERT INTO watchlists (name, symbol, position) VALUES (?, ?, ?)",
                [(clean_name, symbol, index) for index, symbol in enumerate(unique)],
            )
            connection.execute(
                "UPDATE watchlist_meta SET updated_at = ? WHERE name = ?",
                (datetime.now(timezone.utc).isoformat(), clean_name),
            )
            connection.commit()

    def move(self, symbol: str, offset: int, name: str = "DEFAULT") -> None:
        symbols = self.symbols(name)
        clean_symbol = symbol.upper()
        if clean_symbol not in symbols:
            return
        current = symbols.index(clean_symbol)
        target = max(0, min(len(symbols) - 1, current + offset))
        if target == current:
            return
        symbols.insert(target, symbols.pop(current))
        self.replace(name, symbols)

    def rename(self, old_name: str, new_name: str) -> str:
        old = self._name(old_name)
        new = self._name(new_name)
        if old == "DEFAULT":
            raise ValueError("The DEFAULT watchlist cannot be renamed")
        if old == new:
            return new
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self.path) as connection:
            if connection.execute("SELECT 1 FROM watchlist_meta WHERE name = ?", (new,)).fetchone():
                raise ValueError(f"Watchlist {new} already exists")
            connection.execute(
                "INSERT INTO watchlist_meta (name, created_at, updated_at) VALUES (?, ?, ?)",
                (new, now, now),
            )
            connection.execute("UPDATE watchlists SET name = ? WHERE name = ?", (new, old))
            connection.execute("DELETE FROM watchlist_meta WHERE name = ?", (old,))
            connection.commit()
        return new

    def delete(self, name: str) -> None:
        clean_name = self._name(name)
        if clean_name == "DEFAULT":
            self.replace("DEFAULT", self.DEFAULT)
            return
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM watchlists WHERE name = ?", (clean_name,))
            connection.execute("DELETE FROM watchlist_meta WHERE name = ?", (clean_name,))
            connection.commit()

    @staticmethod
    def _name(name: str) -> str:
        clean = " ".join(name.strip().upper().split())
        if not clean:
            raise ValueError("Watchlist name cannot be blank")
        return clean[:40]
