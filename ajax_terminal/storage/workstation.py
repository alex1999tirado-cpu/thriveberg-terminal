from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ajax_terminal.storage.database import DEFAULT_DB_PATH, get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(value: str, *, default: str = "") -> str:
    clean = " ".join(value.strip().upper().split()) or default
    if not clean:
        raise ValueError("Name cannot be blank")
    return clean[:48]


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    name: str
    active_command: str
    current_symbol: str = ""
    history: tuple[str, ...] = ()
    geometry_b64: str = ""
    updated_at: str = ""


class WorkspaceStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def list(self) -> list[WorkspaceSnapshot]:
        with get_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM workspace_snapshots ORDER BY updated_at DESC, name"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, name: str) -> WorkspaceSnapshot | None:
        with get_connection(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM workspace_snapshots WHERE name = ?", (_name(name),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def save(self, snapshot: WorkspaceSnapshot) -> WorkspaceSnapshot:
        clean = _name(snapshot.name)
        updated = _now()
        history = tuple(item for item in snapshot.history if item.strip())[-50:]
        with get_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO workspace_snapshots
                    (name, active_command, current_symbol, history_json, geometry_b64, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    active_command = excluded.active_command,
                    current_symbol = excluded.current_symbol,
                    history_json = excluded.history_json,
                    geometry_b64 = excluded.geometry_b64,
                    updated_at = excluded.updated_at
                """,
                (
                    clean,
                    snapshot.active_command.strip() or "HOME",
                    snapshot.current_symbol.strip().upper(),
                    json.dumps(history),
                    snapshot.geometry_b64,
                    updated,
                ),
            )
            connection.commit()
        return WorkspaceSnapshot(
            clean,
            snapshot.active_command.strip() or "HOME",
            snapshot.current_symbol.strip().upper(),
            history,
            snapshot.geometry_b64,
            updated,
        )

    def delete(self, name: str) -> None:
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM workspace_snapshots WHERE name = ?", (_name(name),))
            connection.commit()

    @staticmethod
    def _from_row(row) -> WorkspaceSnapshot:
        try:
            history = tuple(str(item) for item in json.loads(row["history_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            history = ()
        return WorkspaceSnapshot(
            row["name"],
            row["active_command"],
            row["current_symbol"],
            history,
            row["geometry_b64"],
            row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    portfolio: str
    symbol: str
    quantity: float
    cost_basis: float
    currency: str = ""
    position: int = 0
    updated_at: str = ""


class PortfolioStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def names(self) -> list[str]:
        with get_connection(self.path) as connection:
            rows = connection.execute("SELECT name FROM portfolio_meta ORDER BY name").fetchall()
        names = [row["name"] for row in rows]
        if "MAIN" not in names:
            self.create("MAIN")
            names.insert(0, "MAIN")
        elif names[0] != "MAIN":
            names.remove("MAIN")
            names.insert(0, "MAIN")
        return names

    def create(self, name: str, base_currency: str = "USD") -> str:
        clean = _name(name, default="MAIN")
        now = _now()
        with get_connection(self.path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO portfolio_meta (name, base_currency, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (clean, base_currency.strip().upper() or "USD", now, now),
            )
            connection.commit()
        return clean

    def base_currency(self, name: str = "MAIN") -> str:
        clean = self.create(name)
        with get_connection(self.path) as connection:
            row = connection.execute(
                "SELECT base_currency FROM portfolio_meta WHERE name = ?", (clean,)
            ).fetchone()
        return row["base_currency"] if row else "USD"

    def positions(self, name: str = "MAIN") -> list[PortfolioPosition]:
        clean = self.create(name)
        with get_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM portfolio_positions WHERE portfolio = ? ORDER BY position, symbol",
                (clean,),
            ).fetchall()
        return [
            PortfolioPosition(
                row["portfolio"], row["symbol"], row["quantity"], row["cost_basis"],
                row["currency"], row["position"], row["updated_at"]
            )
            for row in rows
        ]

    def upsert(
        self,
        symbol: str,
        quantity: float,
        cost_basis: float,
        currency: str = "",
        name: str = "MAIN",
    ) -> None:
        clean_name = self.create(name)
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            raise ValueError("Symbol cannot be blank")
        if quantity == 0:
            self.remove(clean_symbol, clean_name)
            return
        now = _now()
        existing = self.positions(clean_name)
        position = next((item.position for item in existing if item.symbol == clean_symbol), len(existing))
        with get_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO portfolio_positions
                    (portfolio, symbol, quantity, cost_basis, currency, position, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio, symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    cost_basis = excluded.cost_basis,
                    currency = excluded.currency,
                    updated_at = excluded.updated_at
                """,
                (clean_name, clean_symbol, float(quantity), float(cost_basis), currency.upper(), position, now),
            )
            connection.execute(
                "UPDATE portfolio_meta SET updated_at = ? WHERE name = ?", (now, clean_name)
            )
            connection.commit()

    def remove(self, symbol: str, name: str = "MAIN") -> None:
        clean_name = _name(name, default="MAIN")
        with get_connection(self.path) as connection:
            connection.execute(
                "DELETE FROM portfolio_positions WHERE portfolio = ? AND symbol = ?",
                (clean_name, symbol.strip().upper()),
            )
            connection.commit()

    def delete(self, name: str) -> None:
        clean = _name(name, default="MAIN")
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM portfolio_positions WHERE portfolio = ?", (clean,))
            connection.execute("DELETE FROM portfolio_meta WHERE name = ?", (clean,))
            connection.commit()
        if clean == "MAIN":
            self.create("MAIN")


@dataclass(frozen=True, slots=True)
class AlertRule:
    id: int | None
    symbol: str
    field: str
    operator: str
    threshold: float
    enabled: bool = True
    last_value: float | None = None
    last_triggered_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


class AlertStore:
    FIELDS = {"PRICE", "CHANGE_PCT", "VOLUME", "BID", "ASK"}
    OPERATORS = {">", ">=", "<", "<=", "="}

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def list(self, *, enabled_only: bool = False) -> list[AlertRule]:
        query = (
            "SELECT * FROM alerts WHERE enabled = 1 ORDER BY id"
            if enabled_only
            else "SELECT * FROM alerts ORDER BY id"
        )
        with get_connection(self.path) as connection:
            rows = connection.execute(query).fetchall()
        return [self._from_row(row) for row in rows]

    def add(self, symbol: str, field: str, operator: str, threshold: float) -> AlertRule:
        clean_symbol = symbol.strip().upper()
        clean_field = field.strip().upper()
        clean_operator = operator.strip()
        if not clean_symbol:
            raise ValueError("Symbol cannot be blank")
        if clean_field not in self.FIELDS:
            raise ValueError(f"Unsupported alert field: {clean_field}")
        if clean_operator not in self.OPERATORS:
            raise ValueError(f"Unsupported alert operator: {clean_operator}")
        now = _now()
        with get_connection(self.path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO alerts
                    (symbol, field, operator, threshold, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (clean_symbol, clean_field, clean_operator, float(threshold), now, now),
            )
            connection.commit()
            alert_id = int(cursor.lastrowid)
        return AlertRule(alert_id, clean_symbol, clean_field, clean_operator, float(threshold), True, created_at=now, updated_at=now)

    def set_enabled(self, alert_id: int, enabled: bool) -> None:
        with get_connection(self.path) as connection:
            connection.execute(
                "UPDATE alerts SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _now(), int(alert_id)),
            )
            connection.commit()

    def record_evaluation(self, alert_id: int, value: float | None, triggered: bool) -> None:
        now = _now()
        with get_connection(self.path) as connection:
            connection.execute(
                """
                UPDATE alerts SET last_value = ?,
                    last_triggered_at = CASE WHEN ? THEN ? ELSE last_triggered_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (value, int(triggered), now, now, int(alert_id)),
            )
            connection.commit()

    def delete(self, alert_id: int) -> None:
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM alerts WHERE id = ?", (int(alert_id),))
            connection.commit()

    @staticmethod
    def _from_row(row) -> AlertRule:
        return AlertRule(
            row["id"], row["symbol"], row["field"], row["operator"], row["threshold"],
            bool(row["enabled"]), row["last_value"], row["last_triggered_at"],
            row["created_at"], row["updated_at"]
        )


class SavedScreenStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def list(self) -> list[tuple[str, str]]:
        with get_connection(self.path) as connection:
            rows = connection.execute("SELECT name, query FROM saved_screens ORDER BY name").fetchall()
        return [(row["name"], row["query"]) for row in rows]

    def save(self, name: str, query: str) -> None:
        clean = _name(name)
        with get_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO saved_screens (name, query, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET query = excluded.query, updated_at = excluded.updated_at
                """,
                (clean, " ".join(query.strip().upper().split()), _now()),
            )
            connection.commit()

    def delete(self, name: str) -> None:
        with get_connection(self.path) as connection:
            connection.execute("DELETE FROM saved_screens WHERE name = ?", (_name(name),))
            connection.commit()
