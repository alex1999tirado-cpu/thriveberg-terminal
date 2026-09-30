from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ajax_terminal.models.quote import DataQuality


@dataclass(frozen=True, slots=True)
class Filing:
    symbol: str
    company_name: str
    cik: str
    form: str
    filing_date: date
    report_date: date | None
    accession_number: str
    primary_document: str
    description: str = ""
    url: str = ""
    jurisdiction: str = "US"

    @property
    def document_url(self) -> str:
        if self.url:
            return self.url
        accession = self.accession_number.replace("-", "")
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(self.cik)}/{accession}/{self.primary_document}"
        )


@dataclass(slots=True)
class FilingCollection:
    symbol: str
    company_name: str
    cik: str
    filings: list[Filing]
    provider: str = "SEC EDGAR"
    quality: DataQuality = DataQuality.UNAVAILABLE
    message: str = ""
    jurisdiction: str = "US"
    portal_url: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
