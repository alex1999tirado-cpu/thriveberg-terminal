from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ajax_terminal.models.quote import DataQuality
from ajax_terminal.storage.database import DEFAULT_DB_PATH, get_connection


@dataclass(frozen=True, slots=True)
class ProviderHealthRecord:
    provider: str
    domain: str
    status: str
    quality: DataQuality
    latency_ms: float | None
    success_count: int
    failure_count: int
    last_checked_at: datetime
    last_success_at: datetime | None
    last_failure_at: datetime | None
    message: str = ""


class DataQualityStore:
    """Persist provider health without retaining payloads or credentials."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def record(
        self,
        provider: str,
        domain: str,
        *,
        status: str,
        quality: DataQuality = DataQuality.UNAVAILABLE,
        latency_ms: float | None = None,
        message: str = "",
        checked_at: datetime | None = None,
    ) -> ProviderHealthRecord:
        observed_at = checked_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        clean_provider = _label(provider, "UNKNOWN")
        clean_domain = _label(domain, "GENERAL")
        clean_status = _label(status, "FAILED")
        success = clean_status in {"AVAILABLE", "DEGRADED"}
        checked = observed_at.astimezone(timezone.utc).isoformat()
        clean_message = " ".join(str(message).split())[:240]
        with get_connection(self.path) as connection:
            connection.execute(
                """
                INSERT INTO provider_health (
                    provider, domain, status, quality, latency_ms,
                    success_count, failure_count, last_checked_at,
                    last_success_at, last_failure_at, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, domain) DO UPDATE SET
                    status = excluded.status,
                    quality = excluded.quality,
                    latency_ms = excluded.latency_ms,
                    success_count = provider_health.success_count + excluded.success_count,
                    failure_count = provider_health.failure_count + excluded.failure_count,
                    last_checked_at = excluded.last_checked_at,
                    last_success_at = CASE
                        WHEN excluded.last_success_at IS NOT NULL THEN excluded.last_success_at
                        ELSE provider_health.last_success_at
                    END,
                    last_failure_at = CASE
                        WHEN excluded.last_failure_at IS NOT NULL THEN excluded.last_failure_at
                        ELSE provider_health.last_failure_at
                    END,
                    message = excluded.message
                """,
                (
                    clean_provider,
                    clean_domain,
                    clean_status,
                    str(quality),
                    latency_ms,
                    1 if success else 0,
                    0 if success else 1,
                    checked,
                    checked if success else None,
                    None if success else checked,
                    clean_message,
                ),
            )
            connection.commit()
        record = self.get(clean_provider, clean_domain)
        if record is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError("Provider health record was not persisted")
        return record

    def get(self, provider: str, domain: str) -> ProviderHealthRecord | None:
        with get_connection(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM provider_health WHERE provider = ? AND domain = ?",
                (_label(provider, "UNKNOWN"), _label(domain, "GENERAL")),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def records(self) -> tuple[ProviderHealthRecord, ...]:
        with get_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM provider_health ORDER BY provider, domain"
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)


def _record_from_row(row) -> ProviderHealthRecord:
    try:
        quality = DataQuality(str(row["quality"]))
    except ValueError:
        quality = DataQuality.UNAVAILABLE
    return ProviderHealthRecord(
        provider=str(row["provider"]),
        domain=str(row["domain"]),
        status=str(row["status"]),
        quality=quality,
        latency_ms=float(row["latency_ms"]) if row["latency_ms"] is not None else None,
        success_count=int(row["success_count"]),
        failure_count=int(row["failure_count"]),
        last_checked_at=_datetime(row["last_checked_at"]) or datetime.now(timezone.utc),
        last_success_at=_datetime(row["last_success_at"]),
        last_failure_at=_datetime(row["last_failure_at"]),
        message=str(row["message"] or ""),
    )


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _label(value: object, fallback: str) -> str:
    return " ".join(str(value or fallback).upper().split())[:80]
