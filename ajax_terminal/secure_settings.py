from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable


SECRET_SETTING_NAMES = frozenset(
    {
        "ALPHA_VANTAGE_KEY",
        "FINNHUB_KEY",
        "COMPANIES_HOUSE_API_KEY",
        "FMP_KEY",
        "NEWS_API_KEY",
        "FRED_API_KEY",
        "AJAX_SUPABASE_URL",
        "AJAX_SUPABASE_PUBLISHABLE_KEY",
        "AJAX_SUPABASE_ANON_KEY",
    }
)

_MAGIC_V1 = b"THRIVEBERG-DPAPI-V1\0"
_MAGIC_V2 = b"THRIVEBERG-DPAPI-V2\0"
_ENTROPY = b"THRIVEBERG Terminal secure settings v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecureSettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecureSettingsStatus:
    path: Path
    exists: bool
    format_version: int
    decryptable: bool
    configured_names: tuple[str, ...]
    migrated_from_v1: bool = False
    error: str = ""


def user_data_directory() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home())
    return base / "THRIVEBERG Terminal"


def secure_settings_path() -> Path:
    return user_data_directory() / "secure-settings.bin"


class SecureSettings:
    """Small per-user secret store protected by Windows DPAPI."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else secure_settings_path()
        self._lock = RLock()

    def get(self, name: str, default: str = "") -> str:
        with self._lock:
            value = self._read().get(name.upper(), default)
        return str(value).strip() if value is not None else default

    def configured(self, name: str) -> bool:
        return bool(self.get(name))

    def set(self, name: str, value: str) -> None:
        self.set_many({name: value})

    def set_many(self, values: dict[str, str]) -> None:
        with self._lock:
            payload = self._read()
            for name, value in values.items():
                key = name.strip().upper()
                if not key:
                    continue
                clean = value.strip()
                if clean:
                    payload[key] = clean
                else:
                    payload.pop(key, None)
            self._write(payload)

    def delete(self, name: str) -> None:
        self.set(name, "")

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._read()))

    def status(self) -> SecureSettingsStatus:
        with self._lock:
            if not self.path.is_file():
                return SecureSettingsStatus(self.path, False, 2, True, ())
            try:
                payload, version = self._decode(self.path.read_bytes())
                migrated = version == 1
                if migrated:
                    self._upgrade_v1(payload)
                    version = 2
                return SecureSettingsStatus(
                    self.path,
                    True,
                    version,
                    True,
                    tuple(sorted(payload)),
                    migrated_from_v1=migrated,
                )
            except (OSError, SecureSettingsError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return SecureSettingsStatus(self.path, True, 0, False, (), error=str(exc))

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            payload, version = self._decode(self.path.read_bytes())
        except SecureSettingsError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecureSettingsError("Secure settings could not be read") from exc
        if version == 1:
            self._upgrade_v1(payload)
        return payload

    def _decode(self, raw: bytes) -> tuple[dict[str, str], int]:
        if raw.startswith(_MAGIC_V2):
            clear = _unprotect(raw[len(_MAGIC_V2) :])
            envelope = json.loads(clear.decode("utf-8"))
            if not isinstance(envelope, dict) or envelope.get("schema") != 2:
                raise SecureSettingsError("Secure settings payload is invalid")
            payload = envelope.get("values")
            version = 2
        elif raw.startswith(_MAGIC_V1):
            clear = _unprotect(raw[len(_MAGIC_V1) :])
            payload = json.loads(clear.decode("utf-8"))
            version = 1
        else:
            raise SecureSettingsError("Secure settings file has an unknown format")
        if not isinstance(payload, dict):
            raise SecureSettingsError("Secure settings payload is invalid")
        return (
            {str(key).upper(): str(value) for key, value in payload.items() if value},
            version,
        )

    def _write(self, payload: dict[str, str]) -> None:
        envelope = {
            "schema": 2,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "values": payload,
        }
        clear = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = _MAGIC_V2 + _protect(clear)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise SecureSettingsError("Secure settings could not be saved") from exc

    def _upgrade_v1(self, payload: dict[str, str]) -> None:
        original = self.path.read_bytes()
        backup = self.path.with_suffix(self.path.suffix + ".v1.bak")
        backup_temp = backup.with_suffix(backup.suffix + ".tmp")
        try:
            if not backup.exists():
                backup_temp.write_bytes(original)
                backup_temp.replace(backup)
            self._write(payload)
            verified, version = self._decode(self.path.read_bytes())
            if version != 2 or verified != payload:
                raise SecureSettingsError("Secure settings migration verification failed")
        except Exception as exc:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rollback = self.path.with_suffix(self.path.suffix + ".rollback")
            rollback.write_bytes(original)
            rollback.replace(self.path)
            if isinstance(exc, SecureSettingsError):
                raise
            raise SecureSettingsError("Secure settings migration failed and was rolled back") from exc
        finally:
            backup_temp.unlink(missing_ok=True)


def secure_setting(name: str, default: str = "") -> str:
    try:
        return SecureSettings().get(name, default)
    except SecureSettingsError:
        return default


def migrate_env_file(
    path: Path | str,
    *,
    store: SecureSettings | None = None,
    names: Iterable[str] = SECRET_SETTING_NAMES,
) -> tuple[str, ...]:
    """Move recognized plaintext values from a .env file into DPAPI storage."""
    env_path = Path(path)
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ()
    accepted = {name.upper() for name in names}
    target = store or SecureSettings()
    migrated: dict[str, str] = {}
    recognized = False
    output: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(raw_line)
            continue
        key, value = stripped.split("=", 1)
        clean_key = key.removeprefix("export ").strip().upper()
        clean_value = value.strip().strip("'\"")
        if clean_key not in accepted or not clean_value:
            output.append(raw_line)
            continue
        recognized = True
        if not target.get(clean_key):
            migrated[clean_key] = clean_value
        output.append(f"{clean_key}=")
    if not recognized:
        return ()
    if migrated:
        target.set_many(migrated)
        if any(target.get(name) != value for name, value in migrated.items()):
            raise SecureSettingsError("Encrypted settings migration verification failed")
    temporary = env_path.with_suffix(env_path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(env_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise SecureSettingsError("Plaintext settings could not be scrubbed") from exc
    return tuple(sorted(migrated))


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecureSettingsError("Secure settings require Windows DPAPI")
    source, source_buffer = _input_blob(data)
    entropy, entropy_buffer = _input_blob(_ENTROPY)
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    success = crypt32.CryptProtectData(
        ctypes.byref(source),
        "THRIVEBERG Terminal",
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    _ = source_buffer, entropy_buffer
    if not success:
        raise SecureSettingsError(f"Windows could not encrypt settings ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecureSettingsError("Secure settings require Windows DPAPI")
    source, source_buffer = _input_blob(data)
    entropy, entropy_buffer = _input_blob(_ENTROPY)
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    success = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    _ = source_buffer, entropy_buffer
    if not success:
        raise SecureSettingsError(f"Windows could not decrypt settings ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Manage THRIVEBERG encrypted settings")
    parser.add_argument("action", choices=("set", "delete", "status", "migrate"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--stdin", action="store_true")
    args = parser.parse_args()
    store = SecureSettings()
    if args.action == "status":
        for name in store.names():
            print(f"{name}=CONFIGURED")
        return 0
    if args.action == "migrate":
        migrated = migrate_env_file(args.env_file, store=store)
        print("Migrated: " + (", ".join(migrated) if migrated else "none"))
        return 0
    if not args.name:
        parser.error("name is required")
    if args.action == "delete":
        store.delete(args.name)
        print(f"{args.name.upper()} removed")
        return 0
    value = sys.stdin.read() if args.stdin else getpass.getpass(f"{args.name.upper()}: ")
    if not value.strip():
        parser.error("value cannot be empty")
    store.set(args.name, value)
    print(f"{args.name.upper()} stored with Windows DPAPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
