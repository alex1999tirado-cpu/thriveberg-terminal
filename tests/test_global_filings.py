from __future__ import annotations

import asyncio

from ajax_terminal.models.equity import CompanyProfile
from ajax_terminal.providers import global_filings
from ajax_terminal.providers.global_filings import (
    ESEFFilingsProvider,
    GlobalFilingsProvider,
    country_for_symbol,
)


def test_country_resolution_uses_exchange_suffixes() -> None:
    assert country_for_symbol("KRI.AT") == "AT"
    assert country_for_symbol("SAN.MC") == "ES"
    assert country_for_symbol("7203.T") == "JP"
    assert country_for_symbol("005930.KS") == "KR"
    assert country_for_symbol("RELIANCE.NS") == "IN"
    assert country_for_symbol("VALE3.SA") == "BR"
    assert country_for_symbol("UNKNOWN.XYZ") == "ZZ"
    assert country_for_symbol("AAPL") == "US"


def test_esef_provider_returns_annual_report_links(monkeypatch) -> None:
    async def profile(_symbol: str) -> CompanyProfile:
        return CompanyProfile("SAN.MC", "Banco Santander S.A.", country="Spain")

    monkeypatch.setattr(global_filings, "_company_profile", profile)
    monkeypatch.setattr(
        ESEFFilingsProvider,
        "_resolve_lei",
        lambda self, name, country: ("5493006QMFDDMYWIAM13", "BANCO SANTANDER S.A."),
    )
    monkeypatch.setattr(
        global_filings,
        "_get_json",
        lambda _url, _headers=None: {
            "data": [
                {
                    "id": "123",
                    "attributes": {
                        "viewer_url": "/entity/2025/report.html",
                        "period_end": "2025-12-31",
                        "date_added": "2026-03-01T10:00:00Z",
                        "fxo_id": "SAN-2025",
                    },
                }
            ]
        },
    )

    result = asyncio.run(ESEFFilingsProvider().filings("SAN.MC", ("10-K",), country="ES"))

    assert result.jurisdiction == "ES"
    assert result.filings[0].form == "AFR / ESEF"
    assert result.filings[0].document_url == "https://filings.xbrl.org/entity/2025/report.html"


def test_global_provider_exposes_official_portal_when_no_free_api(monkeypatch) -> None:
    async def profile(symbol: str) -> CompanyProfile:
        return CompanyProfile(symbol, "Shopify Inc.", country="Canada")

    monkeypatch.setattr(global_filings, "_company_profile", profile)
    result = asyncio.run(GlobalFilingsProvider().filings("SHOP.TO"))

    assert result.provider == "SEDAR+"
    assert result.jurisdiction == "CA"
    assert result.portal_url.startswith("https://www.sedarplus.ca/")


def test_unknown_foreign_suffix_never_falls_back_to_sec(monkeypatch) -> None:
    async def profile(symbol: str) -> CompanyProfile:
        return CompanyProfile(symbol, "Unknown Issuer")

    monkeypatch.setattr(global_filings, "_company_profile", profile)
    result = asyncio.run(GlobalFilingsProvider().filings("ISSUER.XYZ"))

    assert result.jurisdiction == "ZZ"
    assert result.provider == "IOSCO REGULATOR DIRECTORY"
    assert "sec" not in result.provider.lower()
