from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data/ajax_terminal.sqlite3")


def get_connection(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlists (
            name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (name, symbol)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_meta (
            name TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_snapshots (
            name TEXT PRIMARY KEY,
            active_command TEXT NOT NULL,
            current_symbol TEXT NOT NULL DEFAULT '',
            history_json TEXT NOT NULL DEFAULT '[]',
            geometry_b64 TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_meta (
            name TEXT PRIMARY KEY,
            base_currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            portfolio TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            cost_basis REAL NOT NULL,
            cost_basis_base REAL,
            currency TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (portfolio, symbol)
        )
        """
    )
    _ensure_column(connection, "portfolio_positions", "cost_basis_base", "REAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            fees REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT '',
            fx_rate REAL NOT NULL DEFAULT 1,
            realized_pnl REAL NOT NULL DEFAULT 0,
            external_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (portfolio, source, external_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_cash_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio TEXT NOT NULL,
            flow_date TEXT NOT NULL,
            kind TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT '',
            fx_rate REAL NOT NULL DEFAULT 1,
            symbol TEXT NOT NULL DEFAULT '',
            external_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (portfolio, source, external_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portfolio_transactions_date
        ON portfolio_transactions (portfolio, trade_date DESC, id DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portfolio_cash_flows_date
        ON portfolio_cash_flows (portfolio, flow_date DESC, id DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            field TEXT NOT NULL,
            operator TEXT NOT NULL,
            threshold REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_value REAL,
            last_triggered_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_screens (
            name TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT NOT NULL,
            domain TEXT NOT NULL,
            status TEXT NOT NULL,
            quality TEXT NOT NULL DEFAULT 'UNAVAILABLE',
            latency_ms REAL,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT NOT NULL,
            last_success_at TEXT,
            last_failure_at TEXT,
            message TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (provider, domain)
        )
        """
    )
    connection.commit()


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {
        str(row[1]).lower()
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column.lower() not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
