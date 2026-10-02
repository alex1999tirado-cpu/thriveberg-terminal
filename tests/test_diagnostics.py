from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ajax_terminal.build_info import BuildInfo
from ajax_terminal.secure_settings import SecureSettings
from ajax_terminal.services.diagnostics_service import (
    DiagnosticCheck,
    DiagnosticReport,
    collect_diagnostics,
    export_support_bundle,
    sanitize_text,
)
from ajax_terminal.storage.database import get_connection


def test_diagnostics_check_database_and_plaintext_secrets(tmp_path: Path) -> None:
    database = tmp_path / "terminal.sqlite3"
    get_connection(database).close()
    env_file = tmp_path / ".env"
    env_file.write_text("FINNHUB_KEY=must-not-leak\n", encoding="utf-8")
    store = SecureSettings(tmp_path / "secure-settings.bin")
    store.set("FRED_API_KEY", "encrypted-value")

    report = collect_diagnostics(database_path=database, secure_store=store, roots=(tmp_path,))

    assert any(check.name == "SQLITE INTEGRITY" and check.status == "PASS" for check in report.checks)
    assert any(check.name == "PLAINTEXT SECRET SCAN" and check.status == "WARN" for check in report.checks)
    assert report.configured_connections == ("FRED_API_KEY",)
    assert "encrypted-value" not in repr(report)


def test_support_bundle_redacts_secrets_email_and_home(tmp_path: Path) -> None:
    store = SecureSettings(tmp_path / "secure-settings.bin")
    store.set("FINNHUB_KEY", "top-secret-token")
    log = tmp_path / "thriveberg.log"
    log.write_text(
        f"email trader@example.com FINNHUB_KEY=top-secret-token path={Path.home()}\n",
        encoding="utf-8",
    )
    report = DiagnosticReport(
        datetime.now(timezone.utc),
        BuildInfo("0.5.0", 18, "beta"),
        (DiagnosticCheck("SECURITY", "TEST", "PASS", "ok"),),
        ("FINNHUB_KEY",),
        log,
    )

    bundle = export_support_bundle(report, tmp_path / "support.zip", secure_store=store)

    with zipfile.ZipFile(bundle) as archive:
        exported_log = archive.read("thriveberg-sanitized.log").decode()
        diagnostics = json.loads(archive.read("diagnostics.json"))
    assert "top-secret-token" not in exported_log
    assert "trader@example.com" not in exported_log
    assert str(Path.home()) not in exported_log
    assert "[REDACTED_SECRET]" in exported_log
    assert diagnostics["configured_connections"] == ["FINNHUB_KEY"]


def test_sanitize_text_redacts_generic_authorization() -> None:
    sanitized = sanitize_text("Authorization: Bearer abc.def.ghi password=hunter2")

    assert "abc.def.ghi" not in sanitized
    assert "hunter2" not in sanitized
