from __future__ import annotations

import pytest

from ajax_terminal.providers.supabase_social import SupabaseSocialProvider
from ajax_terminal.utils.url_security import require_https_url


def test_https_url_accepts_exact_and_subdomain_allowlist_matches() -> None:
    assert require_https_url(
        "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        allowed_hosts=("finance.yahoo.com",),
    ).startswith("https://query1.finance.yahoo.com/")


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/data",
        "file:///etc/passwd",
        "https://user:password@example.com/data",
        "https://localhost/data",
        "https://127.0.0.1/data",
        "https://10.0.0.2/data",
        "https://[::1]/data",
    ),
)
def test_https_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        require_https_url(url)


def test_https_url_rejects_allowlist_suffix_confusion() -> None:
    with pytest.raises(ValueError):
        require_https_url(
            "https://finance.yahoo.com.attacker.example/data",
            allowed_hosts=("finance.yahoo.com",),
        )


def test_supabase_provider_requires_https() -> None:
    with pytest.raises(ValueError):
        SupabaseSocialProvider("http://example.supabase.co", "public-key")
