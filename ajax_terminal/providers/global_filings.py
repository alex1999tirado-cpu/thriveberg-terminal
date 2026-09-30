from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import re
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

from ajax_terminal.config import setting

from ajax_terminal.models.filing import Filing, FilingCollection
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.sec import SECFilingsProvider
from ajax_terminal.providers.yahoo import YahooProvider
from ajax_terminal.utils.url_security import require_https_url


_SUFFIX_COUNTRIES = {
    ".AD": "AE",
    ".AT": "AT",
    ".AX": "AU",
    ".BA": "AR",
    ".BD": "HU",
    ".BK": "TH",
    ".BO": "IN",
    ".BR": "BE",
    ".CA": "EG",
    ".CL": "LK",
    ".CN": "CA",
    ".CO": "DK",
    ".DE": "DE",
    ".F": "DE",
    ".HE": "FI",
    ".HK": "HK",
    ".IC": "IS",
    ".IR": "IE",
    ".IS": "TR",
    ".JK": "ID",
    ".JO": "ZA",
    ".KL": "MY",
    ".KQ": "KR",
    ".KS": "KR",
    ".L": "GB",
    ".LJ": "SI",
    ".LS": "PT",
    ".MC": "ES",
    ".MX": "MX",
    ".MI": "IT",
    ".NE": "CA",
    ".NS": "IN",
    ".NZ": "NZ",
    ".OL": "NO",
    ".PA": "FR",
    ".PR": "CZ",
    ".QA": "QA",
    ".RG": "LV",
    ".RO": "RO",
    ".SA": "BR",
    ".SI": "SG",
    ".SN": "CL",
    ".SR": "SA",
    ".SS": "CN",
    ".ST": "SE",
    ".SW": "CH",
    ".SZ": "CN",
    ".T": "JP",
    ".TA": "IL",
    ".TL": "EE",
    ".TO": "CA",
    ".TW": "TW",
    ".TWO": "TW",
    ".V": "CA",
    ".VI": "AT",
    ".VS": "LT",
    ".WA": "PL",
    ".AS": "NL",
}

_ESEF_COUNTRIES = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GB",
    "GR",
    "HR",
    "HU",
    "IE",
    "IS",
    "IT",
    "LI",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "NO",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}

_PORTALS = {
    "AE": ("ADX / DFM DISCLOSURES", "https://www.adx.ae/english/market-information/disclosures"),
    "AR": ("CNV ARGENTINA", "https://www.argentina.gob.ar/cnv"),
    "AU": ("ASX ANNOUNCEMENTS", "https://www.asx.com.au/markets/trade-our-cash-market/announcements"),
    "BR": ("CVM BRAZIL", "https://www.gov.br/cvm/pt-br/assuntos/companhias"),
    "CA": ("SEDAR+", "https://www.sedarplus.ca/landingpage/"),
    "CH": ("SIX EXCHANGE REGULATION", "https://www.ser-ag.com/en/resources/notifications-market-participants/official-notices.html"),
    "CL": ("CMF CHILE", "https://www.cmfchile.cl/portal/principal/613/w3-channel.html"),
    "CN": ("CNINFO", "https://www.cninfo.com.cn/new/index"),
    "EG": ("EGX DISCLOSURES", "https://www.egx.com.eg/en/Disclosure.aspx"),
    "HK": ("HKEXNEWS", "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"),
    "ID": ("IDX REPORTS", "https://www.idx.co.id/en/listed-companies/financial-statements-and-annual-report"),
    "IL": ("ISA MAGNA", "https://www.magna.isa.gov.il/"),
    "IN": ("NSE CORPORATE FILINGS", "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"),
    "JP": ("EDINET FSA", "https://disclosure2.edinet-fsa.go.jp/week0020.aspx"),
    "KR": ("FSS DART", "https://dart.fss.or.kr/"),
    "LK": ("CSE FILINGS", "https://www.cse.lk/pages/company-profile/company-profile.component.html"),
    "MY": ("BURSA MALAYSIA", "https://www.bursamalaysia.com/market_information/announcements/company_announcement"),
    "MX": ("BMV ISSUERS", "https://www.bmv.com.mx/en/issuers/information-of-issuers"),
    "NZ": ("NZX ANNOUNCEMENTS", "https://www.nzx.com/announcements"),
    "QA": ("QSE DISCLOSURES", "https://www.qe.com.qa/disclosures"),
    "SA": ("SAUDI EXCHANGE", "https://www.saudiexchange.sa/wps/portal/saudiexchange/ourmarkets/main-market-watch/issuer-financial-calendars"),
    "SG": ("SGX ANNOUNCEMENTS", "https://www.sgx.com/securities/company-announcements"),
    "TH": ("SET COMPANY DISCLOSURES", "https://www.set.or.th/en/market/get-quote/stock/overview"),
    "TR": ("KAP", "https://www.kap.org.tr/en/"),
    "TW": ("TWSE MOPS", "https://mops.twse.com.tw/mops/#/web/home"),
    "ZA": ("JSE SENS", "https://senspdf.jse.co.za/documents/SENS_Headlines.aspx"),
}

for _esef_country in _ESEF_COUNTRIES:
    _PORTALS.setdefault(
        _esef_country,
        ("ESEF / NATIONAL OAM", "https://filings.xbrl.org/"),
    )


class GlobalFilingsProvider:
    name = "GLOBAL REGULATORY FILINGS"

    def __init__(self) -> None:
        self.sec = SECFilingsProvider()
        self.esef = ESEFFilingsProvider()
        self.companies_house = CompaniesHouseFilingsProvider()

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        limit: int = 20,
    ) -> FilingCollection:
        clean = symbol.strip().upper()
        country = country_for_symbol(clean)
        if country == "US":
            return await self.sec.filings(clean, forms, limit)
        if country == "GB" and self.companies_house.configured:
            result = await self.companies_house.filings(clean, forms, limit)
            if result.filings:
                return result
        if country in _ESEF_COUNTRIES:
            result = await self.esef.filings(clean, forms, limit, country=country)
            if result.filings:
                return result
        provider, portal = _PORTALS.get(
            country,
            ("IOSCO REGULATOR DIRECTORY", "https://www.iosco.org/about/?subsection=membership"),
        )
        profile = await _company_profile(clean)
        return FilingCollection(
            symbol=clean,
            company_name=profile.name or clean,
            cik="",
            filings=[],
            provider=provider,
            quality=DataQuality.UNAVAILABLE,
            message=(
                f"No machine-readable connector is configured for {provider}. "
                "Open the official disclosure portal to retrieve the issuer's annual, "
                "interim, or quarterly reports."
            ),
            jurisdiction=country,
            portal_url=portal,
        )


class ESEFFilingsProvider:
    name = "ESEF / FILINGS.XBRL.ORG"
    GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
    FILINGS_URL = "https://filings.xbrl.org/api/entities/{lei}/filings"

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        limit: int = 20,
        *,
        country: str | None = None,
    ) -> FilingCollection:
        clean = symbol.strip().upper()
        selected_country = country or country_for_symbol(clean)
        if not any(form.upper().removesuffix("/A") == "10-K" for form in forms):
            return FilingCollection(
                clean,
                clean,
                "",
                [],
                provider=self.name,
                message="This jurisdiction publishes annual or half-year reports, not SEC 10-Q forms.",
                jurisdiction=selected_country,
            )
        profile = await _company_profile(clean)
        company_name = profile.name or clean
        lei, legal_name = await asyncio.to_thread(self._resolve_lei, company_name, selected_country)
        if not lei:
            return FilingCollection(
                clean,
                company_name,
                "",
                [],
                provider=self.name,
                message="No matching LEI/ESEF issuer was found for this listing.",
                jurisdiction=selected_country,
                portal_url="https://filings.xbrl.org/",
            )
        payload = await asyncio.to_thread(
            _get_json,
            self.FILINGS_URL.format(lei=urllib.parse.quote(lei))
            + "?"
            + urllib.parse.urlencode({"page[size]": min(max(limit * 3, 20), 100), "sort": "-period_end"}),
        )
        filings_by_period: dict[str, Filing] = {}
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes", {})
            if not isinstance(attributes, dict):
                continue
            report_url = str(attributes.get("viewer_url") or attributes.get("report_url") or "")
            if report_url.startswith("/"):
                report_url = f"https://filings.xbrl.org{report_url}"
            period_end = _parse_date(attributes.get("period_end"))
            filed = _parse_datetime_date(attributes.get("date_added")) or period_end
            if not report_url or filed is None:
                continue
            filing_country = str(attributes.get("country") or selected_country).upper()
            filing = Filing(
                symbol=clean,
                company_name=legal_name or company_name,
                cik=lei,
                form="AFR / ESEF",
                filing_date=filed,
                report_date=period_end,
                accession_number=str(attributes.get("fxo_id") or item.get("id") or ""),
                primary_document=report_url.rsplit("/", 1)[-1],
                description="Official-format annual financial report (ESEF/iXBRL)",
                url=report_url,
                jurisdiction=filing_country,
            )
            period_key = period_end.isoformat() if period_end else filing.accession_number
            current = filings_by_period.get(period_key)
            if current is None or (
                filing.jurisdiction == selected_country and current.jurisdiction != selected_country
            ):
                filings_by_period[period_key] = filing
        filings = sorted(
            filings_by_period.values(),
            key=lambda item: (item.report_date or item.filing_date, item.filing_date),
            reverse=True,
        )
        return FilingCollection(
            clean,
            legal_name or company_name,
            lei,
            filings[:limit],
            provider=self.name,
            quality=DataQuality.REALTIME if filings else DataQuality.UNAVAILABLE,
            message="" if filings else "No ESEF annual reports were returned for this issuer.",
            jurisdiction=selected_country,
            portal_url="https://filings.xbrl.org/",
        )

    def _resolve_lei(self, company_name: str, country: str) -> tuple[str, str]:
        base_query = {
            "filter[entity.legalAddress.country]": country,
            "page[size]": 20,
        }
        payload = _get_json(
            f"{self.GLEIF_URL}?"
            + urllib.parse.urlencode({**base_query, "filter[entity.legalName]": company_name})
        )
        if not payload.get("data"):
            payload = _get_json(
                f"{self.GLEIF_URL}?"
                + urllib.parse.urlencode({**base_query, "filter[fulltext]": company_name})
            )
        candidates: list[tuple[float, str, str]] = []
        wanted = _normalized_name(company_name)
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes", {})
            entity = attributes.get("entity", {}) if isinstance(attributes, dict) else {}
            legal = entity.get("legalName", {}) if isinstance(entity, dict) else {}
            legal_name = str(legal.get("name") or "") if isinstance(legal, dict) else ""
            lei = str(item.get("id") or attributes.get("lei") or "")
            if lei and legal_name:
                score = SequenceMatcher(None, wanted, _normalized_name(legal_name)).ratio()
                candidates.append((score, lei, legal_name))
        if not candidates:
            return "", ""
        score, lei, legal_name = max(candidates)
        return (lei, legal_name) if score >= 0.45 else ("", "")


class CompaniesHouseFilingsProvider:
    name = "UK COMPANIES HOUSE"
    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or setting("COMPANIES_HOUSE_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        limit: int = 20,
    ) -> FilingCollection:
        clean = symbol.strip().upper()
        profile = await _company_profile(clean)
        search = await asyncio.to_thread(
            self._request,
            "/search/companies?" + urllib.parse.urlencode({"q": profile.name, "items_per_page": 10}),
        )
        items = search.get("items", [])
        if not items:
            return FilingCollection(clean, profile.name, "", [], provider=self.name, jurisdiction="GB")
        company = max(
            items,
            key=lambda item: SequenceMatcher(
                None,
                _normalized_name(profile.name),
                _normalized_name(str(item.get("title", ""))),
            ).ratio(),
        )
        company_number = str(company.get("company_number") or "")
        history = await asyncio.to_thread(
            self._request,
            f"/company/{company_number}/filing-history?"
            + urllib.parse.urlencode({"category": "accounts", "items_per_page": min(limit, 100)}),
        )
        portal = f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history"
        filings: list[Filing] = []
        for item in history.get("items", []):
            filed = _parse_date(item.get("date"))
            if filed is None:
                continue
            filings.append(
                Filing(
                    clean,
                    str(company.get("title") or profile.name),
                    company_number,
                    "ANNUAL ACCOUNTS",
                    filed,
                    _parse_date(item.get("action_date")),
                    str(item.get("transaction_id") or ""),
                    "filing-history",
                    str(item.get("description") or "Company accounts"),
                    portal,
                    "GB",
                )
            )
        return FilingCollection(
            clean,
            str(company.get("title") or profile.name),
            company_number,
            filings,
            provider=self.name,
            quality=DataQuality.REALTIME if filings else DataQuality.UNAVAILABLE,
            jurisdiction="GB",
            portal_url=portal,
        )

    def _request(self, path: str) -> dict[str, Any]:
        credentials = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return _get_json(f"{self.BASE_URL}{path}", {"Authorization": f"Basic {credentials}"})


def country_for_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    country = next(
        (
            country
            for suffix, country in sorted(
                _SUFFIX_COUNTRIES.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            )
            if clean.endswith(suffix)
        ),
        None,
    )
    if country:
        return country
    # Unrecognised exchange suffixes must never be sent to SEC EDGAR as US issuers.
    if re.search(r"\.[A-Z]{1,5}$", clean):
        return "ZZ"
    return "US"


async def _company_profile(symbol: str):
    try:
        return await YahooProvider().company_profile(symbol)
    except Exception:
        from ajax_terminal.models.equity import CompanyProfile

        return CompanyProfile(symbol, symbol)


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    safe_url = require_https_url(
        url,
        allowed_hosts=(
            "api.gleif.org",
            "filings.xbrl.org",
            "api.company-information.service.gov.uk",
        ),
    )
    request = urllib.request.Request(
        safe_url,
        headers={
            "User-Agent": "THRIVEBERG Terminal filings@thriveberg.local",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
        body = response.read()
        encoding = response.headers.get("Content-Encoding", "").lower()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body)
    payload = json.loads(body.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _normalized_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _parse_datetime_date(value: object) -> date | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date() if value else None
    except ValueError:
        return None
