from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import shutil
import sqlite3
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ajax_terminal.build_info import BuildInfo, current_build_info
from ajax_terminal.config import application_roots
from ajax_terminal.logging_config import log_path
from ajax_terminal.secure_settings import SECRET_SETTING_NAMES, SecureSettings, user_data_directory
from ajax_terminal.services.update_service import public_key_path
from ajax_terminal.storage.database import DEFAULT_DB_PATH


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    category: str
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    generated_at: datetime
    build: BuildInfo
    checks: tuple[DiagnosticCheck, ...]
    configured_connections: tuple[str, ...]
    log_file: Path

    @property
    def failed_count(self) -> int:
        return sum(check.status == "FAIL" for check in self.checks)

    @property
    def warning_count(self) -> int:
        return sum(check.status == "WARN" for check in self.checks)


def collect_diagnostics(
    *,
    database_path: Path | str = DEFAULT_DB_PATH,
    secure_store: SecureSettings | None = None,
    roots: tuple[Path, ...] | None = None,
) -> DiagnosticReport:
    store = secure_store or SecureSettings()
    checks: list[DiagnosticCheck] = []
    build = current_build_info()
    checks.append(DiagnosticCheck("BUILD", "APPLICATION", "PASS", build.label))
    checks.append(
        DiagnosticCheck(
            "RUNTIME",
            "PYTHON / OS",
            "PASS",
            f"Python {platform.python_version()} | {platform.system()} {platform.release()} | {platform.machine()}",
        )
    )
    checks.append(_writable_directory_check(user_data_directory()))
    checks.append(_public_key_check())

    secure_status = store.status()
    secure_detail = (
        f"DPAPI V{secure_status.format_version} | {len(secure_status.configured_names)} configured names"
        if secure_status.decryptable
        else secure_status.error
    )
    checks.append(
        DiagnosticCheck(
            "SECURITY",
            "ENCRYPTED SETTINGS",
            "PASS" if secure_status.decryptable else "FAIL",
            secure_detail,
        )
    )
    plaintext_files = _plaintext_secret_files(roots or application_roots())
    checks.append(
        DiagnosticCheck(
            "SECURITY",
            "PLAINTEXT SECRET SCAN",
            "WARN" if plaintext_files else "PASS",
            ", ".join(path.name for path in plaintext_files) if plaintext_files else "No recognized plaintext API keys",
        )
    )
    checks.extend(_database_checks(Path(database_path)))
    active_log = log_path()
    checks.append(
        DiagnosticCheck(
            "LOGGING",
            "ROTATING LOG",
            "PASS" if active_log.parent.exists() else "WARN",
            _safe_path(active_log),
        )
    )
    usage = shutil.disk_usage(user_data_directory().anchor or Path.cwd().anchor)
    free_gb = usage.free / (1024**3)
    checks.append(
        DiagnosticCheck(
            "STORAGE",
            "FREE SPACE",
            "PASS" if free_gb >= 1 else "WARN",
            f"{free_gb:,.1f} GB available",
        )
    )
    return DiagnosticReport(
        datetime.now(timezone.utc),
        build,
        tuple(checks),
        secure_status.configured_names if secure_status.decryptable else (),
        active_log,
    )


def export_support_bundle(
    report: DiagnosticReport,
    destination: Path | str,
    *,
    secure_store: SecureSettings | None = None,
) -> Path:
    target = Path(destination)
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    payload = {
        "schema": 1,
        "generated_at": report.generated_at.isoformat(),
        "build": asdict(report.build),
        "checks": [asdict(check) for check in report.checks],
        "configured_connections": list(report.configured_connections),
    }
    sanitized_log = "Log file is not available."
    try:
        raw_log = _tail_bytes(report.log_file, 512 * 1024).decode("utf-8", errors="replace")
        sanitized_log = sanitize_text(raw_log, secure_store=secure_store)
    except OSError:
        pass
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostics.json",
                sanitize_text(json.dumps(payload, indent=2, sort_keys=True), secure_store=secure_store),
            )
            archive.writestr("thriveberg-sanitized.log", sanitized_log)
            archive.writestr(
                "README.txt",
                "THRIVEBERG support bundle. API keys, passwords, email addresses and user paths are redacted.\n",
            )
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def sanitize_text(text: str, *, secure_store: SecureSettings | None = None) -> str:
    sanitized = text
    store = secure_store or SecureSettings()
    try:
        values = [store.get(name) for name in store.names()]
    except RuntimeError:
        values = []
    values.extend(os.getenv(name, "") for name in SECRET_SETTING_NAMES)
    for value in sorted({value for value in values if len(value) >= 4}, key=len, reverse=True):
        sanitized = sanitized.replace(value, "[REDACTED_SECRET]")
    sanitized = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*", "Bearer [REDACTED_SECRET]", sanitized)
    sanitized = re.sub(
        r"(?i)\b(api[_ -]?key|token|password|secret|authorization)\b(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED_SECRET]",
        sanitized,
    )
    sanitized = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", sanitized, flags=re.I)
    home = str(Path.home())
    if home:
        sanitized = re.sub(re.escape(home), "%USERPROFILE%", sanitized, flags=re.I)
    return sanitized


def _writable_directory_check(path: Path) -> DiagnosticCheck:
    probe = path / ".diagnostic-write-test"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return DiagnosticCheck("STORAGE", "USER DATA", "PASS", _safe_path(path))
    except OSError as exc:
        probe.unlink(missing_ok=True)
        return DiagnosticCheck("STORAGE", "USER DATA", "FAIL", str(exc))


def _public_key_check() -> DiagnosticCheck:
    try:
        key_data = public_key_path().read_bytes()
        key = serialization.load_pem_public_key(key_data)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("public key is not Ed25519")
        fingerprint = hashlib.sha256(key_data).hexdigest().upper()[:16]
        return DiagnosticCheck("SECURITY", "UPDATE SIGNING KEY", "PASS", f"Ed25519 {fingerprint}")
    except (OSError, ValueError, TypeError) as exc:
        return DiagnosticCheck("SECURITY", "UPDATE SIGNING KEY", "FAIL", str(exc))


def _database_checks(path: Path) -> tuple[DiagnosticCheck, ...]:
    if not path.is_file():
        return (DiagnosticCheck("DATABASE", "SQLITE", "WARN", f"Not created yet: {_safe_path(path)}"),)
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            table_count = int(
                connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
            )
            cache_count = _safe_scalar(connection, "SELECT COUNT(*) FROM cache")
            failed_providers = _safe_scalar(
                connection,
                "SELECT COUNT(*) FROM provider_health WHERE status NOT IN ('AVAILABLE', 'OK')",
            )
        finally:
            connection.close()
        return (
            DiagnosticCheck(
                "DATABASE", "SQLITE INTEGRITY", "PASS" if integrity.lower() == "ok" else "FAIL", integrity,
            ),
            DiagnosticCheck(
                "DATABASE", "SCHEMA / CACHE", "PASS", f"{table_count} tables | {cache_count} cache rows",
            ),
            DiagnosticCheck(
                "DATA", "PROVIDER FAILURES", "WARN" if failed_providers else "PASS", f"{failed_providers} recorded",
            ),
        )
    except sqlite3.Error as exc:
        return (DiagnosticCheck("DATABASE", "SQLITE", "FAIL", str(exc)),)


def _safe_scalar(connection: sqlite3.Connection, query: str) -> int:
    try:
        return int(connection.execute(query).fetchone()[0])
    except sqlite3.Error:
        return 0


def _plaintext_secret_files(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    matches: list[Path] = []
    accepted = {name.upper() for name in SECRET_SETTING_NAMES}
    seen: set[str] = set()
    for root in roots:
        path = root / ".env"
        identity = os.path.normcase(str(path.resolve()))
        if identity in seen or not path.is_file():
            continue
        seen.add(identity)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.removeprefix("export ").strip().upper() in accepted and value.strip().strip("'\""):
                matches.append(path)
                break
    return tuple(matches)


def _tail_bytes(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(size - limit, 0))
        return handle.read(limit)


def _safe_path(path: Path) -> str:
    value = str(path.resolve())
    home = str(Path.home())
    return re.sub(re.escape(home), "%USERPROFILE%", value, flags=re.I) if home else value
