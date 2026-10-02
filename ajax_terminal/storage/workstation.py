from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    cost_basis_base: float | None = None


@dataclass(frozen=True, slots=True)
class PortfolioTransaction:
    id: int | None
    portfolio: str
    trade_date: str
    symbol: str
    side: str
    quantity: float
    price: float
    fees: float
    currency: str
    fx_rate: float
    realized_pnl: float
    external_id: str
    source: str = "MANUAL"
    notes: str = ""
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class PortfolioCashFlow:
    id: int | None
    portfolio: str
    flow_date: str
    kind: str
    amount: float
    currency: str
    fx_rate: float
    symbol: str
    external_id: str
    source: str = "MANUAL"
    notes: str = ""
    created_at: str = ""


class PortfolioStore:
    SIDES = {"BUY", "SELL"}
    CASH_KINDS = {
        "DEPOSIT",
        "WITHDRAWAL",
        "DIVIDEND",
        "INTEREST",
        "TAX",
        "FEE",
        "OTHER_IN",
        "OTHER_OUT",
    }

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
                row["currency"], row["position"], row["updated_at"], row["cost_basis_base"]
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
        *,
        cost_basis_base: float | None = None,
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
                    (portfolio, symbol, quantity, cost_basis, cost_basis_base, currency, position, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio, symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    cost_basis = excluded.cost_basis,
                    cost_basis_base = excluded.cost_basis_base,
                    currency = excluded.currency,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_name,
                    clean_symbol,
                    float(quantity),
                    float(cost_basis),
                    float(cost_basis_base) if cost_basis_base is not None else None,
                    currency.upper(),
                    position,
                    now,
                ),
            )
            connection.execute(
                "UPDATE portfolio_meta SET updated_at = ? WHERE name = ?", (now, clean_name)
            )
            connection.commit()

    def transactions(self, name: str = "MAIN", *, limit: int = 500) -> list[PortfolioTransaction]:
        clean = self.create(name)
        with get_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM portfolio_transactions
                WHERE portfolio = ?
                ORDER BY trade_date DESC, id DESC
                LIMIT ?
                """,
                (clean, max(1, min(int(limit), 10_000))),
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def cash_flows(self, name: str = "MAIN", *, limit: int = 500) -> list[PortfolioCashFlow]:
        clean = self.create(name)
        with get_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM portfolio_cash_flows
                WHERE portfolio = ?
                ORDER BY flow_date DESC, id DESC
                LIMIT ?
                """,
                (clean, max(1, min(int(limit), 10_000))),
            ).fetchall()
        return [self._cash_flow_from_row(row) for row in rows]

    def has_external_id(self, name: str, source: str, external_id: str) -> bool:
        clean_name = self.create(name)
        clean_source = _source(source)
        clean_id = str(external_id).strip()[:160]
        if not clean_id:
            return False
        with get_connection(self.path) as connection:
            transaction = connection.execute(
                """
                SELECT 1 FROM portfolio_transactions
                WHERE portfolio = ? AND source = ? AND external_id = ?
                """,
                (clean_name, clean_source, clean_id),
            ).fetchone()
            cash_flow = connection.execute(
                """
                SELECT 1 FROM portfolio_cash_flows
                WHERE portfolio = ? AND source = ? AND external_id = ?
                """,
                (clean_name, clean_source, clean_id),
            ).fetchone()
        return transaction is not None or cash_flow is not None

    def has_transaction_history(self, symbol: str, name: str = "MAIN") -> bool:
        clean_name = self.create(name)
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return False
        with get_connection(self.path) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM portfolio_transactions
                WHERE portfolio = ? AND symbol = ? LIMIT 1
                """,
                (clean_name, clean_symbol),
            ).fetchone()
        return row is not None

    def record_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        *,
        fees: float = 0.0,
        currency: str = "",
        fx_rate: float = 1.0,
        trade_date: str | date | datetime | None = None,
        name: str = "MAIN",
        external_id: str = "",
        source: str = "MANUAL",
        notes: str = "",
    ) -> PortfolioTransaction:
        clean_name = self.create(name)
        clean_symbol = symbol.strip().upper()[:32]
        clean_side = side.strip().upper()
        clean_currency = currency.strip().upper()[:8] or self.base_currency(clean_name)
        clean_source = _source(source)
        clean_id = str(external_id).strip()[:160] or f"MANUAL-{uuid.uuid4().hex.upper()}"
        observed_date = _iso_date(trade_date)
        quantity_value = float(quantity)
        price_value = float(price)
        fee_value = float(fees)
        rate_value = float(fx_rate)
        if not clean_symbol:
            raise ValueError("Symbol cannot be blank")
        if clean_side not in self.SIDES:
            raise ValueError("Trade side must be BUY or SELL")
        if not math.isfinite(quantity_value) or quantity_value <= 0:
            raise ValueError("Quantity must be a positive finite number")
        if not math.isfinite(price_value) or price_value < 0:
            raise ValueError("Price must be a non-negative finite number")
        if not math.isfinite(fee_value) or fee_value < 0:
            raise ValueError("Fees must be a non-negative finite number")
        if not math.isfinite(rate_value) or rate_value <= 0:
            raise ValueError("FX rate must be a positive finite number")
        now = _now()
        with get_connection(self.path) as connection:
            duplicate = connection.execute(
                """
                SELECT * FROM portfolio_transactions
                WHERE portfolio = ? AND source = ? AND external_id = ?
                """,
                (clean_name, clean_source, clean_id),
            ).fetchone()
            if duplicate is not None:
                return self._transaction_from_row(duplicate)
            row = connection.execute(
                """
                SELECT * FROM portfolio_positions
                WHERE portfolio = ? AND symbol = ?
                """,
                (clean_name, clean_symbol),
            ).fetchone()
            existing_quantity = float(row["quantity"]) if row is not None else 0.0
            existing_cost = float(row["cost_basis"]) if row is not None else 0.0
            existing_base_cost = (
                float(row["cost_basis_base"])
                if row is not None and row["cost_basis_base"] is not None
                else existing_cost * rate_value
            )
            existing_currency = str(row["currency"] or "") if row is not None else ""
            if existing_currency and clean_currency and existing_currency != clean_currency:
                raise ValueError(
                    f"Currency mismatch for {clean_symbol}: {existing_currency} vs {clean_currency}"
                )
            if clean_side == "BUY":
                new_quantity = existing_quantity + quantity_value
                native_cost = existing_quantity * existing_cost + quantity_value * price_value + fee_value
                base_cost = (
                    existing_quantity * existing_base_cost
                    + (quantity_value * price_value + fee_value) * rate_value
                )
                new_cost = native_cost / new_quantity
                new_base_cost = base_cost / new_quantity
                realized = 0.0
            else:
                if existing_quantity <= 0 or quantity_value > existing_quantity + 1e-9:
                    raise ValueError(
                        f"Cannot sell {quantity_value:g} {clean_symbol}; available quantity is {existing_quantity:g}"
                    )
                new_quantity = max(0.0, existing_quantity - quantity_value)
                new_cost = existing_cost
                new_base_cost = existing_base_cost
                realized = (
                    (quantity_value * price_value - fee_value) * rate_value
                    - quantity_value * existing_base_cost
                )
            cursor = connection.execute(
                """
                INSERT INTO portfolio_transactions (
                    portfolio, trade_date, symbol, side, quantity, price, fees,
                    currency, fx_rate, realized_pnl, external_id, source, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    observed_date,
                    clean_symbol,
                    clean_side,
                    quantity_value,
                    price_value,
                    fee_value,
                    clean_currency,
                    rate_value,
                    realized,
                    clean_id,
                    clean_source,
                    " ".join(notes.split())[:240],
                    now,
                ),
            )
            if new_quantity <= 1e-9:
                connection.execute(
                    "DELETE FROM portfolio_positions WHERE portfolio = ? AND symbol = ?",
                    (clean_name, clean_symbol),
                )
            else:
                if row is not None:
                    existing_position = int(row["position"])
                else:
                    position_row = connection.execute(
                        """
                        SELECT COALESCE(MAX(position) + 1, 0) AS next_position
                        FROM portfolio_positions WHERE portfolio = ?
                        """,
                        (clean_name,),
                    ).fetchone()
                    existing_position = int(position_row["next_position"])
                connection.execute(
                    """
                    INSERT INTO portfolio_positions (
                        portfolio, symbol, quantity, cost_basis, cost_basis_base,
                        currency, position, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(portfolio, symbol) DO UPDATE SET
                        quantity = excluded.quantity,
                        cost_basis = excluded.cost_basis,
                        cost_basis_base = excluded.cost_basis_base,
                        currency = excluded.currency,
                        updated_at = excluded.updated_at
                    """,
                    (
                        clean_name,
                        clean_symbol,
                        new_quantity,
                        new_cost,
                        new_base_cost,
                        clean_currency,
                        existing_position,
                        now,
                    ),
                )
            connection.execute(
                "UPDATE portfolio_meta SET updated_at = ? WHERE name = ?",
                (now, clean_name),
            )
            transaction = connection.execute(
                "SELECT * FROM portfolio_transactions WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()
        return self._transaction_from_row(transaction)

    def record_cash_flow(
        self,
        kind: str,
        amount: float,
        *,
        currency: str = "",
        fx_rate: float = 1.0,
        flow_date: str | date | datetime | None = None,
        symbol: str = "",
        name: str = "MAIN",
        external_id: str = "",
        source: str = "MANUAL",
        notes: str = "",
    ) -> PortfolioCashFlow:
        clean_name = self.create(name)
        clean_kind = kind.strip().upper()
        if clean_kind not in self.CASH_KINDS:
            raise ValueError(f"Unsupported cash-flow kind: {clean_kind}")
        amount_value = float(amount)
        rate_value = float(fx_rate)
        if not math.isfinite(amount_value) or amount_value == 0:
            raise ValueError("Cash-flow amount must be a non-zero finite number")
        if not math.isfinite(rate_value) or rate_value <= 0:
            raise ValueError("FX rate must be a positive finite number")
        negative_kinds = {"WITHDRAWAL", "TAX", "FEE", "OTHER_OUT"}
        signed_amount = -abs(amount_value) if clean_kind in negative_kinds else abs(amount_value)
        clean_source = _source(source)
        clean_id = str(external_id).strip()[:160] or f"MANUAL-{uuid.uuid4().hex.upper()}"
        clean_currency = currency.strip().upper()[:8] or self.base_currency(clean_name)
        now = _now()
        with get_connection(self.path) as connection:
            duplicate = connection.execute(
                """
                SELECT * FROM portfolio_cash_flows
                WHERE portfolio = ? AND source = ? AND external_id = ?
                """,
                (clean_name, clean_source, clean_id),
            ).fetchone()
            if duplicate is not None:
                return self._cash_flow_from_row(duplicate)
            cursor = connection.execute(
                """
                INSERT INTO portfolio_cash_flows (
                    portfolio, flow_date, kind, amount, currency, fx_rate, symbol,
                    external_id, source, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    _iso_date(flow_date),
                    clean_kind,
                    signed_amount,
                    clean_currency,
                    rate_value,
                    symbol.strip().upper()[:32],
                    clean_id,
                    clean_source,
                    " ".join(notes.split())[:240],
                    now,
                ),
            )
            connection.execute(
                "UPDATE portfolio_meta SET updated_at = ? WHERE name = ?",
                (now, clean_name),
            )
            cash_flow = connection.execute(
                "SELECT * FROM portfolio_cash_flows WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()
        return self._cash_flow_from_row(cash_flow)

    def cash_balance(self, name: str = "MAIN") -> float:
        transactions = self.transactions(name, limit=10_000)
        flows = self.cash_flows(name, limit=10_000)
        trade_cash = sum(
            (
                -(item.quantity * item.price + item.fees)
                if item.side == "BUY"
                else item.quantity * item.price - item.fees
            )
            * item.fx_rate
            for item in transactions
        )
        return trade_cash + sum(item.amount * item.fx_rate for item in flows)

    def net_external_flow(self, name: str = "MAIN") -> float:
        return sum(
            item.amount * item.fx_rate
            for item in self.cash_flows(name, limit=10_000)
            if item.kind in {"DEPOSIT", "WITHDRAWAL"}
        )

    def invested_capital(self, name: str = "MAIN") -> float:
        return sum(
            (item.quantity * item.price + item.fees) * item.fx_rate
            for item in self.transactions(name, limit=10_000)
            if item.side == "BUY"
        )

    @staticmethod
    def _transaction_from_row(row) -> PortfolioTransaction:
        return PortfolioTransaction(
            int(row["id"]),
            str(row["portfolio"]),
            str(row["trade_date"]),
            str(row["symbol"]),
            str(row["side"]),
            float(row["quantity"]),
            float(row["price"]),
            float(row["fees"]),
            str(row["currency"]),
            float(row["fx_rate"]),
            float(row["realized_pnl"]),
            str(row["external_id"]),
            str(row["source"]),
            str(row["notes"]),
            str(row["created_at"]),
        )

    @staticmethod
    def _cash_flow_from_row(row) -> PortfolioCashFlow:
        return PortfolioCashFlow(
            int(row["id"]),
            str(row["portfolio"]),
            str(row["flow_date"]),
            str(row["kind"]),
            float(row["amount"]),
            str(row["currency"]),
            float(row["fx_rate"]),
            str(row["symbol"]),
            str(row["external_id"]),
            str(row["source"]),
            str(row["notes"]),
            str(row["created_at"]),
        )

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
            connection.execute("DELETE FROM portfolio_transactions WHERE portfolio = ?", (clean,))
            connection.execute("DELETE FROM portfolio_cash_flows WHERE portfolio = ?", (clean,))
            connection.execute("DELETE FROM portfolio_meta WHERE name = ?", (clean,))
            connection.commit()
        if clean == "MAIN":
            self.create("MAIN")


def _iso_date(value: str | date | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    clean = str(value).strip()
    try:
        return date.fromisoformat(clean[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date: {clean}") from exc


def _source(value: str) -> str:
    return " ".join((value.strip().upper() or "MANUAL").split())[:64]


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
