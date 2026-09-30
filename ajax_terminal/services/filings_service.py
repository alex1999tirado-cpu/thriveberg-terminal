from __future__ import annotations

import logging
from datetime import date, datetime

from ajax_terminal.models.filing import Filing, FilingCollection
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.global_filings import GlobalFilingsProvider
from ajax_terminal.providers.sec import SECFilingsProvider
from ajax_terminal.storage.cache import SQLiteCache


LOGGER = logging.getLogger(__name__)


class FilingsService:
    TTL = 6 * 3600

    def __init__(
        self,
        cache: SQLiteCache | None = None,
        provider: SECFilingsProvider | GlobalFilingsProvider | None = None,
    ) -> None:
        self.cache = cache or SQLiteCache()
        self.provider = provider or GlobalFilingsProvider()

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        limit: int = 20,
    ) -> FilingCollection:
        clean = symbol.strip().upper()
        normalized_forms = tuple(sorted(form.upper() for form in forms))
        key = f"filings:v2:{clean}:{'-'.join(normalized_forms)}"
        cached = self.cache.get_json(key)
        if isinstance(cached, dict):
            return _collection_from_dict(cached, DataQuality.CACHED)
        try:
            result = await self.provider.filings(clean, normalized_forms, limit)
            if result.quality != DataQuality.UNAVAILABLE:
                self.cache.set_json(key, _collection_to_dict(result), self.TTL)
            return result
        except Exception as exc:
            LOGGER.warning("filings provider=%s symbol=%s error=%s", self.provider.name, clean, exc)
        stale = self.cache.get_stale_json(key)
        if isinstance(stale, dict):
            result = _collection_from_dict(stale, DataQuality.CACHED)
            result.message = "The regulatory source is unavailable; showing the last cached filing index."
            return result
        return FilingCollection(
            symbol=clean,
            company_name=clean,
            cik="",
            filings=[],
            provider=self.provider.name,
            message="The regulatory filing source is currently unavailable. No substitute data was shown.",
        )


def _collection_to_dict(collection: FilingCollection) -> dict[str, object]:
    return {
        "symbol": collection.symbol,
        "company_name": collection.company_name,
        "cik": collection.cik,
        "provider": collection.provider,
        "jurisdiction": collection.jurisdiction,
        "portal_url": collection.portal_url,
        "timestamp": collection.timestamp.isoformat(),
        "filings": [
            {
                "symbol": filing.symbol,
                "company_name": filing.company_name,
                "cik": filing.cik,
                "form": filing.form,
                "filing_date": filing.filing_date.isoformat(),
                "report_date": filing.report_date.isoformat() if filing.report_date else None,
                "accession_number": filing.accession_number,
                "primary_document": filing.primary_document,
                "description": filing.description,
                "url": filing.url,
                "jurisdiction": filing.jurisdiction,
            }
            for filing in collection.filings
        ],
    }


def _collection_from_dict(payload: dict[str, object], quality: DataQuality) -> FilingCollection:
    filings: list[Filing] = []
    for row in payload.get("filings", []):
        if not isinstance(row, dict):
            continue
        try:
            filings.append(
                Filing(
                    symbol=str(row["symbol"]),
                    company_name=str(row["company_name"]),
                    cik=str(row["cik"]),
                    form=str(row["form"]),
                    filing_date=date.fromisoformat(str(row["filing_date"])),
                    report_date=date.fromisoformat(str(row["report_date"])) if row.get("report_date") else None,
                    accession_number=str(row["accession_number"]),
                    primary_document=str(row["primary_document"]),
                    description=str(row.get("description", "")),
                    url=str(row.get("url", "")),
                    jurisdiction=str(row.get("jurisdiction", payload.get("jurisdiction", "US"))),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    timestamp_value = payload.get("timestamp")
    try:
        timestamp = datetime.fromisoformat(str(timestamp_value))
    except (TypeError, ValueError):
        timestamp = datetime.now().astimezone()
    return FilingCollection(
        symbol=str(payload.get("symbol", "")),
        company_name=str(payload.get("company_name", "")),
        cik=str(payload.get("cik", "")),
        filings=filings,
        provider=str(payload.get("provider", "SEC EDGAR")),
        quality=quality,
        jurisdiction=str(payload.get("jurisdiction", "US")),
        portal_url=str(payload.get("portal_url", "")),
        timestamp=timestamp,
    )
