from __future__ import annotations

import os
import sys
from pathlib import Path

from ajax_terminal.secure_settings import SECRET_SETTING_NAMES, SecureSettings, secure_setting


def application_roots() -> tuple[Path, ...]:
    """Return stable config/runtime roots in source and frozen builds."""
    candidates: list[Path] = []
    configured = os.getenv("AJAX_HOME")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path.cwd())
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend((executable_dir, executable_dir.parent))
    candidates.append(Path(__file__).resolve().parents[1])

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except OSError:
            root = candidate.absolute()
        key = os.path.normcase(str(root))
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return tuple(roots)


def setting(name: str, default: str = "") -> str:
    """Read process overrides, encrypted user settings, then legacy .env files."""
    environment = os.getenv(name)
    if environment is not None:
        return environment.strip()
    encrypted = secure_setting(name)
    if encrypted:
        return encrypted
    for root in application_roots():
        env_path = root / ".env"
        if not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.removeprefix("export ").strip() != name:
                continue
            clean = value.strip()
            if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {"'", '"'}:
                clean = clean[1:-1]
            if clean and name.upper() in SECRET_SETTING_NAMES:
                try:
                    SecureSettings().set(name, clean)
                except RuntimeError:
                    pass
            return clean
    return default
