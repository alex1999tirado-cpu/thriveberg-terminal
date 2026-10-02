from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ajax_terminal.secure_settings import _protect, _unprotect
from ajax_terminal.services.update_service import REPOSITORY, canonical_manifest_bytes, verify_signed_manifest


_PRIVATE_MAGIC = b"THRIVEBERG-RELEASE-KEY-DPAPI-V1\0"


def initialize_key(private_path: Path, public_path: Path) -> str:
    if private_path.exists() or public_path.exists():
        raise RuntimeError("Refusing to overwrite an existing release signing key")
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(private_path, _PRIVATE_MAGIC + _protect(private_raw))
    _atomic_write(public_path, public_pem)
    return hashlib.sha256(public_pem).hexdigest().upper()


def sign_release(
    private_path: Path,
    public_path: Path,
    installer: Path,
    output_dir: Path,
    *,
    beta: int,
    version: str,
    commit: str,
    notes: tuple[str, ...],
) -> tuple[Path, Path]:
    encrypted = private_path.read_bytes()
    if not encrypted.startswith(_PRIVATE_MAGIC):
        raise RuntimeError("Release signing key has an unknown format")
    private_key = Ed25519PrivateKey.from_private_bytes(_unprotect(encrypted[len(_PRIVATE_MAGIC) :]))
    configured_public = serialization.load_pem_public_key(public_path.read_bytes())
    if configured_public.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ) != private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ):
        raise RuntimeError("Release signing key does not match the embedded public key")
    expected_name = f"THRIVEBERG-Terminal-BETA-{beta:03d}-Setup.exe"
    if installer.name != expected_name:
        raise RuntimeError(f"Expected installer name {expected_name}")
    digest = _sha256(installer)
    tag = f"v{version}-beta.{beta}"
    download_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{installer.name}"
    release_url = f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
    payload: dict[str, object] = {
        "schema": 1,
        "product": "THRIVEBERG Terminal",
        "channel": "beta",
        "version": version,
        "beta": beta,
        "commit": commit,
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "installer_name": installer.name,
        "installer_url": download_url,
        "installer_size": installer.stat().st_size,
        "installer_sha256": digest,
        "release_url": release_url,
        "notes": list(notes),
    }
    signature = private_key.sign(canonical_manifest_bytes(payload))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"THRIVEBERG-BETA-{beta:03d}.update.json"
    signature_path = output_dir / f"{manifest_path.name}.sig"
    _atomic_write(manifest_path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    _atomic_write(signature_path, base64.b64encode(signature) + b"\n")
    verified = verify_signed_manifest(
        manifest_path.read_bytes(), signature_path.read_bytes(), public_key_pem=public_path.read_bytes()
    )
    if verified.installer_sha256 != digest:
        raise RuntimeError("Release signature verification did not reproduce the installer checksum")
    return manifest_path, signature_path


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and use the THRIVEBERG Ed25519 release key")
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--private", required=True, type=Path)
    initialize.add_argument("--public", required=True, type=Path)
    sign = subparsers.add_parser("sign")
    sign.add_argument("--private", required=True, type=Path)
    sign.add_argument("--public", required=True, type=Path)
    sign.add_argument("--installer", required=True, type=Path)
    sign.add_argument("--output-dir", required=True, type=Path)
    sign.add_argument("--beta", required=True, type=int)
    sign.add_argument("--version", required=True)
    sign.add_argument("--commit", default="")
    sign.add_argument("--note", action="append", default=[])
    args = parser.parse_args()
    if args.action == "initialize":
        fingerprint = initialize_key(args.private, args.public)
        print(f"Release public key SHA-256: {fingerprint}")
        return 0
    manifest, signature = sign_release(
        args.private,
        args.public,
        args.installer,
        args.output_dir,
        beta=args.beta,
        version=args.version,
        commit=args.commit,
        notes=tuple(args.note),
    )
    print(f"Manifest: {manifest}")
    print(f"Signature: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
