from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit


def require_https_url(url: str, *, allowed_hosts: Iterable[str] | None = None) -> str:
    """Return a validated HTTPS URL or raise before network/browser access."""
    value = str(url).strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Only absolute HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in URLs")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc

    hostname = parsed.hostname.rstrip(".").lower()
    if _is_non_public_ip(hostname) or hostname.endswith((".local", ".internal")):
        raise ValueError("Local and private IP addresses are not allowed")

    if allowed_hosts is not None:
        normalized = tuple(str(host).rstrip(".").lower() for host in allowed_hosts)
        if not any(hostname == host or hostname.endswith(f".{host}") for host in normalized):
            raise ValueError(f"URL host is not allowed: {hostname}")
    return value


def _is_non_public_ip(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname == "localhost"
    return not address.is_global
