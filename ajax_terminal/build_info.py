from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ajax_terminal import __version__


@dataclass(frozen=True, slots=True)
class BuildInfo:
    version: str
    beta: int
    channel: str
    commit: str = ""

    @property
    def label(self) -> str:
        suffix = f" Beta {self.beta:03d}" if self.beta else " Development"
        return f"{self.version}{suffix}"


def current_build_info() -> BuildInfo:
    override = os.getenv("THRIVEBERG_BETA_VERSION", "").strip()
    if override.isdigit():
        return BuildInfo(__version__, int(override), "beta")
    for path in _build_info_candidates():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            beta = int(payload.get("beta", 0))
        except (TypeError, ValueError):
            continue
        return BuildInfo(
            str(payload.get("version") or __version__),
            max(beta, 0),
            str(payload.get("channel") or ("beta" if beta else "development")),
            str(payload.get("commit") or ""),
        )
    return BuildInfo(__version__, 0, "development")


def _build_info_candidates() -> tuple[Path, ...]:
    candidates = [Path(__file__).resolve().parent / "assets" / "build-info.json"]
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        candidates.insert(0, Path(bundle_root) / "ajax_terminal" / "assets" / "build-info.json")
    return tuple(candidates)
