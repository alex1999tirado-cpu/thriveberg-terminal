from __future__ import annotations

import base64
import json
import os
import re
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ajax_terminal.models.social import (
    ChatMessage,
    FriendConnection,
    FriendshipStatus,
    SocialSession,
    SocialUser,
)
from ajax_terminal.providers.supabase_social import SupabaseSocialProvider
from ajax_terminal.public_client_config import bundled_supabase_configuration
from ajax_terminal.secure_settings import SecureSettings, SecureSettingsError, secure_settings_path


class SocialService:
    def __init__(
        self,
        provider: SupabaseSocialProvider | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path is not None else secure_settings_path()
        self.config_source = ""
        if provider is None:
            url, key, source = _load_configuration(self.config_path)
            provider = SupabaseSocialProvider(url, key) if url and key else None
            self.config_source = source
        else:
            self.config_source = "injected"
        self.provider = provider
        self.session: SocialSession | None = None

    @property
    def configured(self) -> bool:
        return self.provider is not None

    @property
    def signed_in(self) -> bool:
        return self.session is not None

    async def configure(self, url: str, publishable_key: str) -> None:
        clean_url, clean_key = _validate_configuration(url, publishable_key)
        provider = SupabaseSocialProvider(clean_url, clean_key)
        await provider.health_check()
        _write_configuration(self.config_path, clean_url, clean_key)
        self.provider = provider
        self.session = None
        self.config_source = str(self.config_path)

    def clear_configuration(self) -> None:
        store = SecureSettings(self.config_path)
        store.delete("AJAX_SUPABASE_URL")
        store.delete("AJAX_SUPABASE_PUBLISHABLE_KEY")
        store.delete("AJAX_SUPABASE_ANON_KEY")
        url, key = bundled_supabase_configuration()
        clean_url, clean_key = _validate_configuration(url, key)
        self.provider = SupabaseSocialProvider(clean_url, clean_key)
        self.session = None
        self.config_source = "bundled-public-client"

    def build_friend_package(
        self,
        output_path: Path | str | None = None,
        executable_path: Path | str | None = None,
    ) -> Path:
        provider = self._provider()
        executable = Path(executable_path) if executable_path is not None else Path(sys.executable)
        if executable_path is None and not getattr(sys, "frozen", False):
            raise RuntimeError("Friend ZIP is available from the packaged THRIVEBERG executable")
        if not executable.is_file():
            raise RuntimeError("THRIVEBERG executable was not found")
        destination = (
            Path(output_path)
            if output_path is not None
            else executable.parent / "THRIVEBERG_Terminal_FRIENDS.zip"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        public_config = json.dumps(
            {"url": provider.url, "publishable_key": provider.anon_key},
            indent=2,
        ) + "\n"
        instructions = (
            "THRIVEBERG TERMINAL - FRIEND PACKAGE\n\n"
            "1. Extract both files into the same folder.\n"
            "2. Open THRIVEBERG_Terminal.exe.\n"
            "3. Enter SOCIAL, create an account and add friends by username.\n\n"
            "The included key is a public client key. Passwords are handled by Supabase Auth.\n"
        )
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(executable, "THRIVEBERG_Terminal.exe")
            archive.writestr("ajax-social.json", public_config)
            archive.writestr("LEEME.txt", instructions)
        temporary.replace(destination)
        return destination

    async def register(
        self,
        email: str,
        password: str,
        username: str,
        display_name: str = "",
    ) -> tuple[SocialSession | None, str]:
        provider = self._provider()
        clean_email = email.strip().lower()
        clean_username = _normalize_username(username)
        _validate_credentials(clean_email, password, clean_username)
        session = await provider.sign_up(
            clean_email,
            password,
            clean_username,
            display_name.strip()[:50] or clean_username,
        )
        self.session = session
        if session is None:
            return None, "Account created. Confirm your email, then sign in."
        return session, "Account created and signed in."

    async def sign_in(self, email: str, password: str) -> SocialSession:
        provider = self._provider()
        if not email.strip() or not password:
            raise ValueError("Email and password are required")
        self.session = await provider.sign_in(email.strip().lower(), password)
        return self.session

    async def sign_out(self) -> None:
        if self.provider is not None and self.session is not None:
            await self.provider.sign_out(self.session)
        self.session = None

    async def search_users(self, query: str) -> list[SocialUser]:
        provider, session = self._authenticated()
        users = await provider.search_users(session, query)
        connections = await self.connections()
        by_id = {item.user.user_id: item for item in connections}
        return [
            replace(
                user,
                friendship=by_id[user.user_id].friendship,
                request_id=by_id[user.user_id].request_id,
            )
            if user.user_id in by_id
            else user
            for user in users
        ]

    async def connections(self) -> list[FriendConnection]:
        provider, session = self._authenticated()
        rows = await provider.connection_rows(session)
        other_ids = [
            str(row.get("receiver_id")) if row.get("sender_id") == session.user_id else str(row.get("sender_id"))
            for row in rows
        ]
        profiles = await provider.profiles_by_ids(session, other_ids)
        connections: list[FriendConnection] = []
        for row, other_id in zip(rows, other_ids):
            user = profiles.get(other_id)
            if user is None:
                continue
            status = str(row.get("status", ""))
            if status == "accepted":
                friendship = FriendshipStatus.FRIENDS
            elif row.get("sender_id") == session.user_id:
                friendship = FriendshipStatus.OUTGOING
            else:
                friendship = FriendshipStatus.INCOMING
            connections.append(
                FriendConnection(
                    request_id=str(row.get("id", "")),
                    user=replace(user, friendship=friendship, request_id=str(row.get("id", ""))),
                    friendship=friendship,
                )
            )
        return connections

    async def send_friend_request(self, user: SocialUser) -> None:
        provider, session = self._authenticated()
        await provider.send_friend_request(session, user.user_id)

    async def respond_to_request(self, request_id: str, accept: bool) -> None:
        provider, session = self._authenticated()
        await provider.update_friend_request(session, request_id, "accepted" if accept else "rejected")

    async def messages(self, user: SocialUser) -> list[ChatMessage]:
        provider, session = self._authenticated()
        return await provider.messages(session, user.user_id)

    async def send_message(self, user: SocialUser, body: str, shared_command: str = "") -> None:
        provider, session = self._authenticated()
        clean_body = " ".join(body.strip().split())[:2000]
        clean_command = " ".join(shared_command.strip().upper().split())[:96]
        if not clean_body and not clean_command:
            raise ValueError("Write a message or attach a THRIVEBERG command")
        await provider.send_message(session, user.user_id, clean_body, clean_command)

    def _provider(self) -> SupabaseSocialProvider:
        if self.provider is None:
            raise RuntimeError("Social service is not configured")
        return self.provider

    def _authenticated(self) -> tuple[SupabaseSocialProvider, SocialSession]:
        provider = self._provider()
        if self.session is None:
            raise RuntimeError("Sign in to use the social workspace")
        return provider, self.session


def _normalize_username(value: str) -> str:
    clean = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,24}", clean):
        raise ValueError("Username must be 3-24 characters using letters, numbers, dot, dash or underscore")
    return clean


def _validate_credentials(email: str, password: str, username: str) -> None:
    if "@" not in email or len(email) > 254:
        raise ValueError("Enter a valid email address")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    if not username:
        raise ValueError("Username is required")


def _user_config_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home())
    return base / "THRIVEBERG Terminal" / "social.json"


def _legacy_user_config_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home())
    return base / "AJAX Financial Terminal" / "social.json"


def _bundled_config_path() -> Path:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "ajax-social.json"


def _load_configuration(config_path: Path) -> tuple[str, str, str]:
    environment_url = os.getenv("AJAX_SUPABASE_URL", "").strip()
    environment_key = (
        os.getenv("AJAX_SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.getenv("AJAX_SUPABASE_ANON_KEY", "").strip()
    )
    if environment_url and environment_key:
        try:
            url, key = _validate_configuration(environment_url, environment_key)
        except ValueError:
            pass
        else:
            return url, key, "environment"

    try:
        store = SecureSettings(config_path)
        secure_url = store.get("AJAX_SUPABASE_URL")
        secure_key = store.get("AJAX_SUPABASE_PUBLISHABLE_KEY") or store.get(
            "AJAX_SUPABASE_ANON_KEY"
        )
    except SecureSettingsError:
        secure_url = ""
        secure_key = ""
    if secure_url and secure_key:
        try:
            url, key = _validate_configuration(secure_url, secure_key)
        except ValueError:
            pass
        else:
            return url, key, str(config_path)

    candidates: list[Path] = []
    if config_path.suffix.lower() == ".json":
        candidates.append(config_path)
    elif config_path.resolve() == secure_settings_path().resolve():
        candidates.extend((_user_config_path(), _legacy_user_config_path()))
    bundled = _bundled_config_path()
    if bundled.resolve() != config_path.resolve():
        candidates.append(bundled)
    for candidate in candidates:
        payload = _read_configuration(candidate)
        if payload is None:
            continue
        try:
            url, key = _validate_configuration(
                str(payload.get("url") or payload.get("supabase_url") or ""),
                str(
                    payload.get("publishable_key")
                    or payload.get("anon_key")
                    or payload.get("supabase_anon_key")
                    or ""
                ),
            )
        except ValueError:
            continue
        try:
            _write_configuration(config_path, url, key)
            if candidate != bundled and candidate.is_file():
                candidate.unlink()
        except (OSError, SecureSettingsError):
            pass
        return url, key, str(candidate)
    bundled_url, bundled_key = bundled_supabase_configuration()
    try:
        url, key = _validate_configuration(bundled_url, bundled_key)
    except ValueError:
        return "", "", ""
    return url, key, "bundled-public-client"


def _read_configuration(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_configuration(path: Path, url: str, key: str) -> None:
    SecureSettings(path).set_many(
        {
            "AJAX_SUPABASE_URL": url,
            "AJAX_SUPABASE_PUBLISHABLE_KEY": key,
        }
    )


def _validate_configuration(url: str, key: str) -> tuple[str, str]:
    clean_url = url.strip().rstrip("/")
    clean_key = key.strip()
    if not re.fullmatch(r"https://[^\s/]+(?:/[^\s]*)?", clean_url):
        if not re.fullmatch(r"http://(?:localhost|127\.0\.0\.1)(?::\d+)?", clean_url):
            raise ValueError("Use an HTTPS Supabase project URL")
    if len(clean_key) < 20:
        raise ValueError("Enter a valid Supabase publishable key")
    if _is_privileged_key(clean_key):
        raise ValueError("Never use a Supabase secret or service_role key in THRIVEBERG")
    return clean_url, clean_key


def _is_privileged_key(key: str) -> bool:
    if key.startswith("sb_secret_"):
        return True
    if key.startswith("sb_publishable_"):
        return False
    parts = key.split(".")
    if len(parts) != 3:
        return False
    try:
        payload_part = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("role") == "service_role"
