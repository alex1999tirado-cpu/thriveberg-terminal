from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ajax_terminal.build_info import current_build_info
from ajax_terminal.secure_settings import user_data_directory
from ajax_terminal.services.workstation_service import BetaRelease, scan_beta_releases


REPOSITORY = "alex1999tirado-cpu/thriveberg-terminal-releases"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20"
_MANIFEST_PATTERN = re.compile(r"THRIVEBERG-BETA-(\d{3})\.update\.json$", re.IGNORECASE)
_INSTALLER_PATTERN = re.compile(r"THRIVEBERG-Terminal-BETA-(\d{3})-Setup\.exe$", re.IGNORECASE)
_TAG_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)-beta\.(\d+)$", re.IGNORECASE)
_ALLOWED_DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_SIGNATURE_BYTES = 4096
_MAX_INSTALLER_BYTES = 800 * 1024 * 1024


class UpdateSecurityError(RuntimeError):
    pass


class UpdateNetworkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SignedRelease:
    version: str
    beta: int
    channel: str
    published_at: datetime
    installer_name: str
    installer_url: str
    installer_size: int
    installer_sha256: str
    release_url: str
    notes: tuple[str, ...]
    manifest_bytes: bytes
    signature_bytes: bytes


@dataclass(frozen=True, slots=True)
class UpdateCatalog:
    current_beta: int
    local_releases: tuple[BetaRelease, ...]
    cached_installers: tuple["CachedInstaller", ...]
    remote_release: SignedRelease | None
    checked_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class CachedInstaller:
    beta: int
    path: Path
    release: SignedRelease | None
    error: str = ""

    @property
    def verified(self) -> bool:
        return self.release is not None and not self.error


def update_cache_directory() -> Path:
    return user_data_directory() / "updates" / "BETA"


def canonical_manifest_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def public_key_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "update-public-key.pem"


def verify_signed_manifest(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    *,
    public_key_pem: bytes | None = None,
) -> SignedRelease:
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES or len(signature_bytes) > _MAX_SIGNATURE_BYTES:
        raise UpdateSecurityError("Update metadata exceeds the permitted size")
    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateSecurityError("Update manifest is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateSecurityError("Update manifest root must be an object")
    key_data = public_key_pem
    if key_data is None:
        try:
            key_data = public_key_path().read_bytes()
        except OSError as exc:
            raise UpdateSecurityError("The embedded update public key is missing") from exc
    try:
        key = serialization.load_pem_public_key(key_data)
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError("not Ed25519")
        signature = base64.b64decode(signature_bytes.strip(), validate=True)
        key.verify(signature, canonical_manifest_bytes(payload))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise UpdateSecurityError("Update manifest signature is invalid") from exc
    return _validated_release(payload, manifest_bytes, signature_bytes)


def fetch_update_catalog(
    *,
    current_beta: int | None = None,
    release_dir: Path | None = None,
    session: requests.Session | None = None,
) -> UpdateCatalog:
    beta = current_build_info().beta if current_beta is None else max(int(current_beta), 0)
    local = scan_beta_releases(release_dir)
    cached = scan_cached_installers()
    checked_at = datetime.now(timezone.utc)
    client = session or requests.Session()
    try:
        response = client.get(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "THRIVEBERG-Terminal-Updater"},
            timeout=(5, 15),
        )
        response.raise_for_status()
        releases = response.json()
        if not isinstance(releases, list):
            raise UpdateNetworkError("GitHub returned an invalid release catalog")
        candidates: list[tuple[int, dict[str, object]]] = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            tag_match = _TAG_PATTERN.fullmatch(str(release.get("tag_name") or ""))
            if tag_match is None:
                continue
            release_beta = int(tag_match.group(2))
            if release_beta > beta:
                candidates.append((release_beta, release))
        for release_beta, release in sorted(candidates, key=lambda item: item[0], reverse=True):
            signed = _fetch_signed_release(client, release, release_beta)
            if signed is not None:
                return UpdateCatalog(beta, local, cached, signed, checked_at, "SIGNED UPDATE AVAILABLE")
        return UpdateCatalog(beta, local, cached, None, checked_at, "NO NEW SIGNED UPDATE")
    except (requests.RequestException, ValueError, UpdateNetworkError, UpdateSecurityError) as exc:
        return UpdateCatalog(beta, local, cached, None, checked_at, f"ONLINE CHECK FAILED: {exc}")


def scan_cached_installers(directory: Path | None = None) -> tuple[CachedInstaller, ...]:
    root = directory or update_cache_directory()
    if not root.is_dir():
        return ()
    items: list[CachedInstaller] = []
    for path in root.glob("THRIVEBERG-Terminal-BETA-*-Setup.exe"):
        match = _INSTALLER_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        beta = int(match.group(1))
        manifest_path = path.with_suffix(".update.json")
        signature_path = path.with_suffix(".update.sig")
        try:
            release = verify_signed_manifest(manifest_path.read_bytes(), signature_path.read_bytes())
            if release.beta != beta or release.installer_name != path.name:
                raise UpdateSecurityError("Cached installer metadata does not match its filename")
            if path.stat().st_size != release.installer_size or _sha256(path) != release.installer_sha256:
                raise UpdateSecurityError("Cached installer does not match its signed size/hash")
            items.append(CachedInstaller(beta, path.resolve(), release))
        except (OSError, UpdateSecurityError) as exc:
            items.append(CachedInstaller(beta, path.resolve(), None, str(exc)))
    items.sort(key=lambda item: item.beta, reverse=True)
    return tuple(items)


def download_signed_release(
    release: SignedRelease,
    *,
    destination: Path | None = None,
    session: requests.Session | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    target_dir = destination or update_cache_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = (target_dir / release.installer_name).resolve()
    if final_path.parent != target_dir.resolve():
        raise UpdateSecurityError("Update filename escapes the update directory")
    if final_path.is_file() and _sha256(final_path) == release.installer_sha256:
        return final_path
    partial = final_path.with_suffix(final_path.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    if existing > release.installer_size:
        partial.unlink()
        existing = 0
    headers = {"User-Agent": "THRIVEBERG-Terminal-Updater"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    client = session or requests.Session()
    try:
        response = client.get(release.installer_url, headers=headers, timeout=(10, 60), stream=True)
        response.raise_for_status()
        final_url = str(getattr(response, "url", "") or release.installer_url)
        _validate_https_url(final_url)
        append = existing > 0 and response.status_code == 206
        completed = existing if append else 0
        mode = "ab" if append else "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                completed += len(chunk)
                if completed > release.installer_size or completed > _MAX_INSTALLER_BYTES:
                    raise UpdateSecurityError("Downloaded update exceeds its signed size")
                handle.write(chunk)
                if progress is not None:
                    progress(completed, release.installer_size)
            handle.flush()
    except requests.RequestException as exc:
        raise UpdateNetworkError(f"Update download failed: {exc}") from exc
    if partial.stat().st_size != release.installer_size:
        raise UpdateSecurityError("Downloaded update size does not match the signed manifest")
    if _sha256(partial) != release.installer_sha256:
        partial.unlink(missing_ok=True)
        raise UpdateSecurityError("Downloaded update checksum does not match the signed manifest")
    partial.replace(final_path)
    final_path.with_suffix(".update.json").write_bytes(release.manifest_bytes)
    final_path.with_suffix(".update.sig").write_bytes(release.signature_bytes)
    return final_path


def _fetch_signed_release(
    client: requests.Session,
    release: dict[str, object],
    expected_beta: int,
) -> SignedRelease | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    manifest_asset = None
    signature_asset = None
    expected_manifest_name = f"THRIVEBERG-BETA-{expected_beta:03d}.update.json"
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower() == expected_manifest_name.lower():
            manifest_asset = asset
        elif name.lower() == f"{expected_manifest_name}.sig".lower():
            signature_asset = asset
    if manifest_asset is None or signature_asset is None:
        return None
    manifest = _download_small(client, str(manifest_asset.get("browser_download_url") or ""), _MAX_MANIFEST_BYTES)
    signature = _download_small(client, str(signature_asset.get("browser_download_url") or ""), _MAX_SIGNATURE_BYTES)
    signed = verify_signed_manifest(manifest, signature)
    if signed.beta != expected_beta:
        raise UpdateSecurityError("Signed beta does not match its GitHub release tag")
    return signed


def _download_small(client: requests.Session, url: str, limit: int) -> bytes:
    _validate_https_url(url)
    response = client.get(url, headers={"User-Agent": "THRIVEBERG-Terminal-Updater"}, timeout=(5, 15))
    response.raise_for_status()
    _validate_https_url(str(getattr(response, "url", "") or url))
    content = response.content
    if len(content) > limit:
        raise UpdateSecurityError("Update metadata exceeds the permitted size")
    return content


def _validated_release(
    payload: dict[str, object],
    manifest_bytes: bytes,
    signature_bytes: bytes,
) -> SignedRelease:
    if payload.get("schema") != 1 or payload.get("product") != "THRIVEBERG Terminal":
        raise UpdateSecurityError("Update manifest product or schema is unsupported")
    if payload.get("channel") != "beta":
        raise UpdateSecurityError("Update manifest channel is unsupported")
    raw_beta = payload.get("beta")
    raw_size = payload.get("installer_size")
    if type(raw_beta) is not int or type(raw_size) is not int:
        raise UpdateSecurityError("Update manifest beta and size must be integers")
    try:
        beta = raw_beta
        size = raw_size
        published = datetime.fromisoformat(str(payload["published_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateSecurityError("Update manifest contains invalid version metadata") from exc
    name = str(payload.get("installer_name") or "")
    name_match = _INSTALLER_PATTERN.fullmatch(name)
    if name_match is None or int(name_match.group(1)) != beta:
        raise UpdateSecurityError("Update installer filename does not match its beta")
    if beta <= 0 or size <= 0 or size > _MAX_INSTALLER_BYTES:
        raise UpdateSecurityError("Update manifest contains an invalid beta or size")
    digest = str(payload.get("installer_sha256") or "").upper()
    if not re.fullmatch(r"[A-F0-9]{64}", digest):
        raise UpdateSecurityError("Update manifest checksum is invalid")
    installer_url = str(payload.get("installer_url") or "")
    release_url = str(payload.get("release_url") or "")
    version = str(payload.get("version") or "")
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None or published.tzinfo is None:
        raise UpdateSecurityError("Update manifest version or publication time is invalid")
    _validate_https_url(installer_url)
    _validate_https_url(release_url)
    expected_tag = f"v{version}-beta.{beta}"
    installer_path = urlparse(installer_url).path
    expected_installer_path = f"/{REPOSITORY}/releases/download/{expected_tag}/{name}"
    expected_release_path = f"/{REPOSITORY}/releases/tag/{expected_tag}"
    if installer_path != expected_installer_path or urlparse(release_url).path != expected_release_path:
        raise UpdateSecurityError("Signed update URLs do not match the official release channel")
    if Path(installer_path).name != name:
        raise UpdateSecurityError("Signed download URL does not match the installer filename")
    notes_value = payload.get("notes")
    notes = tuple(str(item)[:500] for item in notes_value) if isinstance(notes_value, list) else ()
    return SignedRelease(
        version, beta, "beta", published, name,
        installer_url, size, digest, release_url, notes, manifest_bytes, signature_bytes,
    )


def _validate_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateSecurityError("Update URL is not an approved HTTPS endpoint")
    if parsed.username or parsed.password:
        raise UpdateSecurityError("Update URL contains credentials")
    if parsed.query or parsed.fragment:
        raise UpdateSecurityError("Update URL contains unsigned query or fragment data")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()
