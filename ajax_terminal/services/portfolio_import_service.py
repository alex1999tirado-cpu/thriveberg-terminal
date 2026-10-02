from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from ajax_terminal.storage.workstation import PortfolioStore


MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_IMPORT_ROWS = 100_000


@dataclass(frozen=True, slots=True)
class BrokerImportRow:
    row_number: int
    entry_type: str
    entry_date: str
    action: str
    symbol: str
    quantity: float | None
    price: float | None
    amount: float | None
    fees: float
    currency: str
    fx_rate: float
    external_id: str
    status: str
    message: str = ""

    @property
    def valid(self) -> bool:
        return self.status == "READY"


@dataclass(frozen=True, slots=True)
class BrokerImportPreview:
    path: Path
    broker: str
    headers: tuple[str, ...]
    rows: tuple[BrokerImportRow, ...]

    @property
    def ready_count(self) -> int:
        return sum(row.valid for row in self.rows)

    @property
    def error_count(self) -> int:
        return len(self.rows) - self.ready_count


@dataclass(frozen=True, slots=True)
class BrokerImportResult:
    portfolio: str
    broker: str
    imported: int
    duplicates: int
    failed: int
    messages: tuple[str, ...] = ()


_ALIASES = {
    "date": ("date", "tradedate", "datetime", "time", "fecha", "datadellordine"),
    "symbol": ("symbol", "ticker", "instrument", "product", "producto", "code", "security"),
    "action": (
        "action", "side", "type", "transactiontype", "buysell", "accion",
        "operation", "description", "descripcion",
    ),
    "quantity": (
        "quantity", "qty", "shares", "number", "units", "cantidad",
        "numero", "noofshares",
    ),
    "price": (
        "price", "tradeprice", "unitprice", "precio", "priceperunit",
        "pricepershare", "priceshare",
    ),
    "amount": ("amount", "total", "netamount", "value", "importe", "cashamount"),
    "fees": (
        "commission", "commissions", "fees", "fee", "transactionfee",
        "comision", "ibcommission", "currencyconversionfee",
        "stampdutyreservetax", "transactioncosts", "costesdetransaccion",
    ),
    "currency": (
        "currency", "ccy", "divisa", "currencyprimary",
        "currencypricepershare", "currencypriceshare", "currencytotal",
    ),
    "fx_rate": ("fxrate", "exchangerate", "conversionrate", "tipodecambio"),
    "external_id": ("id", "transactionid", "tradeid", "orderid", "reference", "referencia"),
    "account_id": ("clientaccountid", "accountid", "account", "cuenta"),
}
_BUY = {"BUY", "B", "BOT", "COMPRA", "KAUF", "MARKETBUY"}
_SELL = {"SELL", "S", "SLD", "VENTA", "VERKAUF", "MARKETSELL"}
_CASH_ACTIONS = {
    "DEPOSIT": "DEPOSIT",
    "DEPOSITO": "DEPOSIT",
    "WITHDRAWAL": "WITHDRAWAL",
    "RETIRADA": "WITHDRAWAL",
    "DIVIDEND": "DIVIDEND",
    "DIVIDENDO": "DIVIDEND",
    "INTEREST": "INTEREST",
    "INTERES": "INTEREST",
    "TAX": "TAX",
    "TAXES": "TAX",
    "RETENCION": "TAX",
    "FEE": "FEE",
    "FEES": "FEE",
    "COMMISSION": "FEE",
}


def preview_broker_csv(path: Path | str, *, default_currency: str = "USD") -> BrokerImportPreview:
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError("Broker import accepts CSV or delimited TXT files only")
    size = source.stat().st_size
    if size <= 0:
        raise ValueError("Broker CSV is empty")
    if size > MAX_IMPORT_BYTES:
        raise ValueError("Broker CSV exceeds the 50 MB safety limit")
    text = _decode(source.read_bytes())
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = tuple(str(header or "").strip() for header in (reader.fieldnames or ()))
    if not headers:
        raise ValueError("Broker CSV has no header row")
    broker = _detect_broker(headers, source.name)
    columns = _column_map(headers)
    rows: list[BrokerImportRow] = []
    try:
        for row_number, raw in enumerate(reader, start=2):
            if row_number > MAX_IMPORT_ROWS + 1:
                raise ValueError("Broker CSV exceeds the 100,000-row safety limit")
            if not any(str(value or "").strip() for value in raw.values()):
                continue
            rows.append(
                _normalize_row(
                    row_number,
                    raw,
                    columns,
                    broker,
                    default_currency.strip().upper() or "USD",
                )
            )
    except csv.Error as exc:
        raise ValueError(f"Malformed broker CSV: {exc}") from exc
    if not rows:
        raise ValueError("Broker CSV contains no data rows")
    return BrokerImportPreview(source, broker, headers, tuple(rows))


def apply_broker_import(
    preview: BrokerImportPreview,
    portfolio: str,
    store: PortfolioStore | None = None,
) -> BrokerImportResult:
    ledger = store or PortfolioStore()
    name = ledger.create(portfolio)
    source = f"CSV / {preview.broker}"
    imported = 0
    duplicates = 0
    failures: list[str] = []
    ordered_rows = sorted(
        preview.rows,
        key=lambda row: (
            row.entry_date if row.valid else "9999-12-31",
            row.row_number,
        ),
    )
    for row in ordered_rows:
        if not row.valid:
            failures.append(f"ROW {row.row_number}: {row.message}")
            continue
        if ledger.has_external_id(name, source, row.external_id):
            duplicates += 1
            continue
        try:
            if row.entry_type == "TRADE":
                ledger.record_trade(
                    row.symbol,
                    row.action,
                    row.quantity or 0.0,
                    row.price or 0.0,
                    fees=row.fees,
                    currency=row.currency,
                    fx_rate=row.fx_rate,
                    trade_date=row.entry_date,
                    name=name,
                    external_id=row.external_id,
                    source=source,
                    notes=f"Imported from {preview.path.name} row {row.row_number}",
                )
            else:
                ledger.record_cash_flow(
                    row.action,
                    row.amount or 0.0,
                    currency=row.currency,
                    fx_rate=row.fx_rate,
                    flow_date=row.entry_date,
                    symbol=row.symbol,
                    name=name,
                    external_id=row.external_id,
                    source=source,
                    notes=f"Imported from {preview.path.name} row {row.row_number}",
                )
            imported += 1
        except (TypeError, ValueError) as exc:
            failures.append(f"ROW {row.row_number}: {exc}")
    return BrokerImportResult(name, preview.broker, imported, duplicates, len(failures), tuple(failures[:20]))


def _normalize_row(
    row_number: int,
    raw: Mapping[str | None, object],
    columns: Mapping[str, str],
    broker: str,
    default_currency: str,
) -> BrokerImportRow:
    def value(field: str) -> str:
        header = columns.get(field, "")
        return str(raw.get(header, "") or "").strip() if header else ""

    action_raw = _key(value("action"))
    symbol = value("symbol").strip().upper()[:32]
    external_id = value("external_id")[:160]
    account_id = value("account_id")[:64]
    currency = value("currency").strip().upper()[:8] or default_currency
    try:
        entry_date = _parse_date(value("date"), broker)
        fee_values = _matching_values(raw, _ALIASES["fees"])
        fees = sum(abs(_number(item, default=0.0)) for item in fee_values)
        fx_text = value("fx_rate")
        if not fx_text and currency != default_currency:
            raise ValueError(
                f"missing FX rate for {currency} to {default_currency}"
            )
        fx_rate = _number(fx_text, default=1.0)
        if fx_rate <= 0:
            raise ValueError("FX rate must be positive")
        quantity_text = value("quantity")
        quantity_number = _number(quantity_text) if quantity_text else None
        action = _canonical_action(action_raw, quantity_number)
        if action in {"BUY", "SELL"}:
            quantity = abs(quantity_number) if quantity_number is not None else 0.0
            price = abs(_number(value("price")))
            if not symbol:
                raise ValueError("missing symbol")
            if quantity <= 0:
                raise ValueError("quantity must be positive")
            if price < 0:
                raise ValueError("price cannot be negative")
            entry_type = "TRADE"
            amount = None
        elif action in PortfolioStore.CASH_KINDS:
            amount = _number(value("amount"))
            if amount == 0:
                raise ValueError("cash amount cannot be zero")
            entry_type = "CASH"
            quantity = None
            price = None
        else:
            raise ValueError(f"unsupported action '{value('action') or '--'}'")
        stable_id = (
            f"{account_id}:{external_id}" if account_id and external_id else external_id
        ) or _fingerprint(row_number, raw, broker)
        return BrokerImportRow(
            row_number,
            entry_type,
            entry_date,
            action,
            symbol,
            quantity,
            price,
            amount,
            fees,
            currency,
            fx_rate,
            stable_id,
            "READY",
        )
    except (TypeError, ValueError) as exc:
        return BrokerImportRow(
            row_number,
            "ERROR",
            value("date")[:24] or "--",
            value("action").upper()[:24] or "--",
            symbol,
            None,
            None,
            None,
            0.0,
            currency,
            1.0,
            (
                f"{account_id}:{external_id}" if account_id and external_id else external_id
            ) or _fingerprint(row_number, raw, broker),
            "ERROR",
            " ".join(str(exc).split())[:160],
        )


def _column_map(headers: tuple[str, ...]) -> dict[str, str]:
    normalized = {_key(header): header for header in headers}
    result: dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        result[field] = next(
            (normalized[_key(alias)] for alias in aliases if _key(alias) in normalized),
            "",
        )
    required = ("date",)
    missing = [field.upper() for field in required if not result[field]]
    if missing:
        raise ValueError("Broker CSV is missing required columns: " + ", ".join(missing))
    return result


def _matching_values(
    row: Mapping[str | None, object],
    aliases: tuple[str, ...],
) -> tuple[str, ...]:
    alias_keys = {_key(alias) for alias in aliases}
    return tuple(
        str(value or "").strip()
        for header, value in row.items()
        if _key(str(header or "")) in alias_keys
    )


def _canonical_action(action: str, quantity: float | None) -> str:
    if action in _BUY or action.startswith("MARKETBUY"):
        return "BUY"
    if action in _SELL or action.startswith("MARKETSELL"):
        return "SELL"
    for prefix, canonical in (
        ("DIVIDEND", "DIVIDEND"),
        ("DIVIDENDO", "DIVIDEND"),
        ("INTEREST", "INTEREST"),
        ("INTERES", "INTEREST"),
        ("WITHHOLDINGTAX", "TAX"),
        ("RETENCION", "TAX"),
        ("DEPOSIT", "DEPOSIT"),
        ("DEPOSITO", "DEPOSIT"),
        ("WITHDRAWAL", "WITHDRAWAL"),
        ("RETIRADA", "WITHDRAWAL"),
        ("COMMISSION", "FEE"),
        ("FEE", "FEE"),
        ("TAX", "TAX"),
    ):
        if action.startswith(prefix):
            return canonical
    if action in _CASH_ACTIONS:
        return _CASH_ACTIONS[action]
    if not action and quantity is not None and quantity != 0:
        return "BUY" if quantity > 0 else "SELL"
    return ""


def _detect_broker(headers: tuple[str, ...], filename: str) -> str:
    keys = {_key(header) for header in headers}
    name = filename.upper()
    if {"CLIENTACCOUNTID", "ASSETCLASS"} & keys or "IBKR" in name:
        return "IBKR"
    if {"ISIN", "PRODUCTO"}.issubset(keys) or "DEGIRO" in name:
        return "DEGIRO"
    if "NOOFSHARES" in keys or "TRADING212" in _key(name):
        return "TRADING 212"
    return "GENERIC BROKER"


def _parse_date(value: str, broker: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("missing date")
    candidate = clean.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        pass
    formats = (
        ("%m/%d/%Y", "%m/%d/%y", "%Y%m%d")
        if broker == "IBKR"
        else ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y%m%d")
    )
    for fmt in formats:
        try:
            return datetime.strptime(clean.split(" ", 1)[0], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{clean}'")


def _number(value: str, *, default: float | None = None) -> float:
    clean = value.strip()
    if not clean:
        if default is not None:
            return default
        raise ValueError("missing numeric value")
    negative = clean.startswith("(") and clean.endswith(")")
    clean = re.sub(r"[^0-9,\.\-+]", "", clean)
    if not clean or clean in {"-", "+", ".", ","}:
        raise ValueError("missing numeric value")
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        tail = clean.rsplit(",", 1)[1]
        clean = clean.replace(",", "") if len(tail) == 3 else clean.replace(",", ".")
    number = float(clean)
    return -abs(number) if negative else number


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Broker CSV encoding is not supported")


def _key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]", "", ascii_value.upper())


def _fingerprint(row_number: int, raw: Mapping[str | None, object], broker: str) -> str:
    canonical = json.dumps(
        {str(key): str(value or "").strip() for key, value in raw.items()},
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(f"{broker}|{row_number}|{canonical}".encode("utf-8")).hexdigest()
    return f"ROW-{digest[:32].upper()}"
