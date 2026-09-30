from __future__ import annotations

from ajax_terminal.secure_settings import SecureSettings, migrate_env_file


def test_secure_settings_round_trip_is_not_plaintext(tmp_path) -> None:
    path = tmp_path / "secure-settings.bin"
    store = SecureSettings(path)

    store.set("FINNHUB_KEY", "private-value-123")

    assert store.get("FINNHUB_KEY") == "private-value-123"
    assert b"private-value-123" not in path.read_bytes()
    assert store.configured("FINNHUB_KEY")


def test_secure_settings_delete_preserves_other_values(tmp_path) -> None:
    store = SecureSettings(tmp_path / "secure-settings.bin")
    store.set_many({"FINNHUB_KEY": "one", "FRED_API_KEY": "two"})

    store.delete("FINNHUB_KEY")

    assert store.get("FINNHUB_KEY") == ""
    assert store.get("FRED_API_KEY") == "two"


def test_plaintext_env_migration_scrubs_recognized_keys(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FINNHUB_KEY=private-finnhub\nAJAX_RUNTIME_TEST=visible\n",
        encoding="utf-8",
    )
    store = SecureSettings(tmp_path / "secure-settings.bin")

    migrated = migrate_env_file(env_path, store=store)

    assert migrated == ("FINNHUB_KEY",)
    assert store.get("FINNHUB_KEY") == "private-finnhub"
    assert env_path.read_text(encoding="utf-8") == (
        "FINNHUB_KEY=\nAJAX_RUNTIME_TEST=visible\n"
    )
