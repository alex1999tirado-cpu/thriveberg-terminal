from __future__ import annotations

import asyncio
import json

import pytest

import ajax_terminal.services.social_service as social_module
from ajax_terminal.services.social_service import SocialService, _load_configuration, _validate_configuration


class HealthyProvider:
    def __init__(self, url: str, key: str) -> None:
        self.url = url
        self.anon_key = key

    async def health_check(self) -> None:
        return None


def test_social_configuration_is_saved_and_reloaded(tmp_path, monkeypatch) -> None:
    path = tmp_path / "social.json"
    monkeypatch.setattr(social_module, "SupabaseSocialProvider", HealthyProvider)
    service = SocialService(config_path=path)

    asyncio.run(
        service.configure("https://ajax-test.supabase.co/", "sb_publishable_12345678901234567890")
    )

    assert service.configured
    assert service.config_source == str(path)
    assert b"sb_publishable_" not in path.read_bytes()
    assert b"ajax-test.supabase.co" not in path.read_bytes()
    restored = SocialService(config_path=path)
    assert restored.configured
    assert restored.provider.url == "https://ajax-test.supabase.co"


def test_social_configuration_rejects_privileged_keys() -> None:
    with pytest.raises(ValueError, match="secret"):
        _validate_configuration(
            "https://ajax-test.supabase.co",
            "sb_secret_12345678901234567890",
        )


def test_clean_install_uses_bundled_public_social_configuration(tmp_path, monkeypatch) -> None:
    path = tmp_path / "secure-settings.bin"
    monkeypatch.delenv("AJAX_SUPABASE_URL", raising=False)
    monkeypatch.delenv("AJAX_SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("AJAX_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr(social_module, "_bundled_config_path", lambda: tmp_path / "missing.json")

    url, key, source = _load_configuration(path)

    assert url == "https://zqgyqhptfvcsjvontlbg.supabase.co"
    assert key.startswith("sb_publishable_")
    assert source == "bundled-public-client"
    assert not path.exists()


def test_environment_social_configuration_overrides_bundled_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AJAX_SUPABASE_URL", "https://override.supabase.co")
    monkeypatch.setenv(
        "AJAX_SUPABASE_PUBLISHABLE_KEY",
        "sb_publishable_12345678901234567890",
    )

    url, key, source = _load_configuration(tmp_path / "secure-settings.bin")

    assert url == "https://override.supabase.co"
    assert key == "sb_publishable_12345678901234567890"
    assert source == "environment"


def test_clearing_social_override_restores_bundled_client(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(social_module, "SupabaseSocialProvider", HealthyProvider)
    service = SocialService(config_path=tmp_path / "secure-settings.bin")
    service.provider = HealthyProvider(
        "https://override.supabase.co",
        "sb_publishable_12345678901234567890",
    )

    service.clear_configuration()

    assert service.configured
    assert service.provider.url == "https://zqgyqhptfvcsjvontlbg.supabase.co"
    assert service.config_source == "bundled-public-client"


def test_legacy_social_configuration_is_migrated_to_dpapi(tmp_path, monkeypatch) -> None:
    secure_path = tmp_path / "secure-settings.bin"
    legacy_path = tmp_path / "ajax-social.json"
    legacy_path.write_text(
        json.dumps(
            {
                "url": "https://ajax-test.supabase.co",
                "publishable_key": "sb_publishable_12345678901234567890",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(social_module, "secure_settings_path", lambda: secure_path)
    monkeypatch.setattr(social_module, "_user_config_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(social_module, "_legacy_user_config_path", lambda: legacy_path)
    monkeypatch.setattr(social_module, "_bundled_config_path", lambda: tmp_path / "bundled.json")
    monkeypatch.setattr(social_module, "SupabaseSocialProvider", HealthyProvider)

    service = SocialService()

    assert service.configured
    assert not legacy_path.exists()
    assert b"sb_publishable_" not in secure_path.read_bytes()


def test_friend_package_contains_executable_and_public_configuration(tmp_path) -> None:
    executable = tmp_path / "AJAX_SOURCE.exe"
    executable.write_bytes(b"ajax-executable")
    provider = HealthyProvider(
        "https://ajax-test.supabase.co",
        "sb_publishable_12345678901234567890",
    )
    service = SocialService(provider=provider, config_path=tmp_path / "social.json")

    package = service.build_friend_package(
        output_path=tmp_path / "friends.zip",
        executable_path=executable,
    )

    import zipfile

    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {
            "THRIVEBERG_Terminal.exe",
            "ajax-social.json",
            "LEEME.txt",
        }
        config = json.loads(archive.read("ajax-social.json"))
    assert config["url"] == "https://ajax-test.supabase.co"
    assert config["publishable_key"].startswith("sb_publishable_")
