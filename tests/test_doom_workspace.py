from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from ajax_terminal.games.doom import workspace as doom_module
from ajax_terminal.games.doom.workspace import (
    DoomAssetError,
    DoomAssets,
    DoomWorkspace,
    build_doom_arguments,
    doom_asset_root,
    validate_doom_assets,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundled_doom_runtime_is_complete_and_verified() -> None:
    assets = validate_doom_assets()
    manifest = json.loads((assets.root / "manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["assets"]}

    assert assets.root == doom_asset_root().resolve()
    assert assets.executable.name == "chocolate-doom.exe"
    assert assets.iwad.name == "freedoom1.wad"
    assert len(paths) == 34
    assert "engine/chocolate-doom.exe" in paths
    assert "content/freedoom1.wad" in paths
    assert "content/doom.wad" not in paths
    assert (assets.root / "source/chocolate-doom-3.1.1-source.zip").is_file()
    assert (assets.root / "licenses/CHOCOLATE-DOOM-COPYING.md").is_file()
    assert (assets.root / "licenses/FREEDOOM-COPYING.txt").is_file()


def test_doom_arguments_isolate_config_and_saved_games(tmp_path: Path) -> None:
    assets = DoomAssets(tmp_path / "assets", tmp_path / "engine.exe", tmp_path / "freedoom1.wad")
    user_root = tmp_path / "profile"
    arguments = build_doom_arguments(assets, user_root, width=320, height=200)

    assert arguments[:2] == ["-iwad", str(assets.iwad)]
    assert arguments[arguments.index("-geometry") + 1] == "640x400"
    assert arguments[arguments.index("-config") + 1] == str(user_root / "default.cfg")
    assert arguments[arguments.index("-extraconfig") + 1] == str(user_root / "chocolate-doom.cfg")
    assert arguments[arguments.index("-savedir") + 1] == str(user_root / "savegames")
    assert "-file" not in arguments


def test_asset_validation_rejects_modified_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "assets"
    executable = root / "engine" / "chocolate-doom.exe"
    iwad = root / "content" / "freedoom1.wad"
    executable.parent.mkdir(parents=True)
    iwad.parent.mkdir(parents=True)
    executable.write_bytes(b"verified engine")
    iwad.write_bytes(b"verified free content")
    manifest = {
        "schema": 1,
        "engine": "test",
        "content": "test",
        "assets": [
            {
                "path": "engine/chocolate-doom.exe",
                "sha256": _digest(executable),
                "size": executable.stat().st_size,
            },
            {"path": "content/freedoom1.wad", "sha256": _digest(iwad), "size": iwad.stat().st_size},
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(doom_module, "DOOM_MANIFEST_SHA256", _digest(manifest_path))

    assert validate_doom_assets(root).iwad == iwad
    executable.write_bytes(b"modified engine")
    with pytest.raises(DoomAssetError, match="failed verification"):
        validate_doom_assets(root)


def test_doom_workspace_can_mount_without_starting_a_process() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = DoomWorkspace(auto_start=False)

    assert not workspace.can_pop_out
    assert workspace.findChild(QLabel) is not None
    workspace.close()
    app.processEvents()
