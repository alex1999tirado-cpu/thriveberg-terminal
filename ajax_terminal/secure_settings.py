from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import sys
from ctypes import wintypes
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

_MAGIC = b"THRIVEBERG-DPAPI-V1\0"
_ENTROPY = b"THRIVEBERG Terminal secure settings v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecureSettingsError(RuntimeError):
    pass


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

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            raw = self.path.read_bytes()
            if not raw.startswith(_MAGIC):
                raise SecureSettingsError("Secure settings file has an unknown format")
            clear = _unprotect(raw[len(_MAGIC) :])
            payload = json.loads(clear.decode("utf-8"))
        except SecureSettingsError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecureSettingsError("Secure settings could not be read") from exc
        if not isinstance(payload, dict):
            raise SecureSettingsError("Secure settings payload is invalid")
        return {str(key).upper(): str(value) for key, value in payload.items() if value}

    def _write(self, payload: dict[str, str]) -> None:
        clear = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = _MAGIC + _protect(clear)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(encoded)
            temporary.replace(self.path)
        except OSError as exc:
            raise SecureSettingsError("Secure settings could not be saved") from exc


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
        if not target.get(clean_key):
            migrated[clean_key] = clean_value
        output.append(f"{clean_key}=")
    if not migrated:
        return ()
    target.set_many(migrated)
    temporary = env_path.with_suffix(env_path.suffix + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(env_path)
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
