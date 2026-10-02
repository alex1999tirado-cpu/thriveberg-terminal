from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ajax_terminal.services.update_service import (
    RELEASES_API,
    REPOSITORY,
    SignedRelease,
    UpdateSecurityError,
    canonical_manifest_bytes,
    download_signed_release,
    fetch_update_catalog,
    verify_signed_manifest,
)
from ajax_terminal.services import update_service
from tools.release_signing import initialize_key, sign_release


def _signed_manifest(*, beta: int = 18, installer: bytes = b"signed installer"):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    name = f"THRIVEBERG-Terminal-BETA-{beta:03d}-Setup.exe"
    tag = f"v0.5.0-beta.{beta}"
    payload = {
        "schema": 1,
        "product": "THRIVEBERG Terminal",
        "channel": "beta",
        "version": "0.5.0",
        "beta": beta,
        "commit": "abc123",
        "published_at": "2026-10-02T12:00:00Z",
        "installer_name": name,
        "installer_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}",
        "installer_size": len(installer),
        "installer_sha256": hashlib.sha256(installer).hexdigest().upper(),
        "release_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        "notes": ["Signed update tests"],
    }
    manifest = (json.dumps(payload, indent=2) + "\n").encode()
    signature = base64.b64encode(private.sign(canonical_manifest_bytes(payload)))
    return payload, manifest, signature, public, installer


def test_signed_manifest_verifies_canonical_payload() -> None:
    _payload, manifest, signature, public, _installer = _signed_manifest()

    release = verify_signed_manifest(manifest, signature, public_key_pem=public)

    assert release.beta == 18
    assert release.installer_name.endswith("018-Setup.exe")


def test_signed_manifest_rejects_tampering() -> None:
    payload, _manifest, signature, public, _installer = _signed_manifest()
    payload["installer_size"] = int(payload["installer_size"]) + 1
    tampered = json.dumps(payload).encode()

    with pytest.raises(UpdateSecurityError, match="signature"):
        verify_signed_manifest(tampered, signature, public_key_pem=public)


def test_signed_manifest_rejects_mismatched_installer_name() -> None:
    payload, _manifest, _signature, _public, _installer = _signed_manifest()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    payload["installer_name"] = "THRIVEBERG-Terminal-BETA-999-Setup.exe"
    manifest = json.dumps(payload).encode()
    signature = base64.b64encode(private.sign(canonical_manifest_bytes(payload)))

    with pytest.raises(UpdateSecurityError, match="filename"):
        verify_signed_manifest(manifest, signature, public_key_pem=public)


class _DownloadResponse:
    def __init__(self, payload: bytes, status_code: int) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self.payload[:chunk_size]
        yield self.payload[chunk_size:]


class _CatalogResponse:
    def __init__(self, *, payload=None, content: bytes = b"", url: str = RELEASES_API) -> None:
        self.payload = payload
        self.content = content
        self.url = url
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _CatalogSession:
    def __init__(self, releases, assets: dict[str, bytes]) -> None:
        self.releases = releases
        self.assets = assets

    def get(self, url: str, **_kwargs):
        if url == RELEASES_API:
            return _CatalogResponse(payload=self.releases, url=url)
        return _CatalogResponse(content=self.assets[url], url=url)


class _DownloadSession:
    def __init__(self, payload: bytes, status_code: int = 206) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def get(self, _url: str, *, headers: dict[str, str], timeout, stream: bool):
        self.headers = headers
        return _DownloadResponse(self.payload, self.status_code)


def test_update_download_resumes_and_rechecks_signed_hash(tmp_path: Path) -> None:
    _payload, manifest, signature, public, installer = _signed_manifest(installer=b"abcdefghij")
    release = verify_signed_manifest(manifest, signature, public_key_pem=public)
    partial = tmp_path / f"{release.installer_name}.part"
    partial.write_bytes(installer[:4])
    session = _DownloadSession(installer[4:])
    progress: list[tuple[int, int]] = []

    installed = download_signed_release(
        release,
        destination=tmp_path,
        session=session,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert session.headers["Range"] == "bytes=4-"
    assert installed.read_bytes() == installer
    assert progress[-1] == (len(installer), len(installer))
    assert installed.with_suffix(".update.json").is_file()


def test_update_download_rejects_path_traversal(tmp_path: Path) -> None:
    release = SignedRelease(
        "0.5.0", 18, "beta", datetime.now(timezone.utc), "../escape.exe",
        "https://github.com/example/project/escape.exe", 1, "00" * 32,
        "https://github.com/example/project", (), b"{}", b"signature",
    )

    with pytest.raises(UpdateSecurityError, match="escapes"):
        download_signed_release(release, destination=tmp_path, session=_DownloadSession(b"x"))


def test_catalog_accepts_only_a_newer_signed_release(tmp_path: Path, monkeypatch) -> None:
    _payload, manifest, signature, public, _installer = _signed_manifest(beta=19)
    manifest_url = "https://github.com/update-manifest"
    signature_url = "https://github.com/update-signature"
    releases = [{
        "tag_name": "v0.5.0-beta.19",
        "draft": False,
        "assets": [
            {"name": "THRIVEBERG-BETA-019.update.json", "browser_download_url": manifest_url},
            {"name": "THRIVEBERG-BETA-019.update.json.sig", "browser_download_url": signature_url},
        ],
    }]
    session = _CatalogSession(releases, {manifest_url: manifest, signature_url: signature})
    key_path = tmp_path / "public.pem"
    key_path.write_bytes(public)
    monkeypatch.setattr(update_service, "public_key_path", lambda: key_path)
    monkeypatch.setattr(update_service, "scan_cached_installers", lambda: ())

    available = fetch_update_catalog(current_beta=18, release_dir=tmp_path, session=session)
    current = fetch_update_catalog(current_beta=19, release_dir=tmp_path, session=session)

    assert available.remote_release is not None
    assert available.remote_release.beta == 19
    assert available.status == "SIGNED UPDATE AVAILABLE"
    assert current.remote_release is None
    assert current.status == "NO NEW SIGNED UPDATE"


def test_catalog_surfaces_a_tampered_signature_as_failure(tmp_path: Path, monkeypatch) -> None:
    _payload, manifest, signature, public, _installer = _signed_manifest(beta=19)
    manifest_url = "https://github.com/update-manifest"
    signature_url = "https://github.com/update-signature"
    releases = [{
        "tag_name": "v0.5.0-beta.19",
        "draft": False,
        "assets": [
            {"name": "THRIVEBERG-BETA-019.update.json", "browser_download_url": manifest_url},
            {"name": "THRIVEBERG-BETA-019.update.json.sig", "browser_download_url": signature_url},
        ],
    }]
    tampered_payload = json.loads(manifest)
    tampered_payload["installer_size"] += 1
    tampered_manifest = json.dumps(tampered_payload).encode()
    session = _CatalogSession(releases, {manifest_url: tampered_manifest, signature_url: signature})
    key_path = tmp_path / "public.pem"
    key_path.write_bytes(public)
    monkeypatch.setattr(update_service, "public_key_path", lambda: key_path)
    monkeypatch.setattr(update_service, "scan_cached_installers", lambda: ())

    catalog = fetch_update_catalog(current_beta=18, release_dir=tmp_path, session=session)

    assert catalog.remote_release is None
    assert catalog.status.startswith("ONLINE CHECK FAILED: Update manifest signature is invalid")


def test_release_signer_keeps_private_key_encrypted_and_self_verifies(tmp_path: Path) -> None:
    private_path = tmp_path / "release-key.bin"
    public_path = tmp_path / "release-public.pem"
    initialize_key(private_path, public_path)
    installer = tmp_path / "THRIVEBERG-Terminal-BETA-018-Setup.exe"
    installer.write_bytes(b"release payload")

    manifest, signature = sign_release(
        private_path,
        public_path,
        installer,
        tmp_path,
        beta=18,
        version="0.5.0",
        commit="abc123",
        notes=("Verified",),
    )

    release = verify_signed_manifest(
        manifest.read_bytes(), signature.read_bytes(), public_key_pem=public_path.read_bytes()
    )
    assert private_path.read_bytes().startswith(b"THRIVEBERG-RELEASE-KEY-DPAPI-V1\0")
    assert b"release payload" not in private_path.read_bytes()
    assert release.installer_sha256 == hashlib.sha256(installer.read_bytes()).hexdigest().upper()
