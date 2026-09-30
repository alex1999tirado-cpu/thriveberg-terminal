from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ajax_terminal.models.quote import DataQuality


@dataclass(slots=True)
class NewsItem:
    timestamp: datetime
    source: str
    headline: str
    link: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    category: str = "MARKETS"
    author: str = ""

    @classmethod
    def unavailable(cls, topic: str = "") -> "NewsItem":
        tag = topic.upper() if topic else "GENERAL"
        return cls(
            timestamp=datetime.now(timezone.utc),
            source="THRIVEBERG",
            headline="No live news provider available",
            tags=[tag, "UNAVAILABLE"],
            provider="THRIVEBERG",
            quality=DataQuality.UNAVAILABLE,
            category="GENERAL",
        )


def infer_news_category(headline: str, tags: list[str] | None = None) -> str:
    text = " ".join([headline, *(tags or [])]).upper()
    categories = (
        ("CENTRAL BANKS", ("FED ", "FEDERAL RESERVE", "ECB", "BOE", "BOJ", "CENTRAL BANK", "RATE CUT", "RATE HIKE")),
        ("ECONOMY", ("INFLATION", "CPI", "GDP", "JOBS", "PAYROLL", "UNEMPLOYMENT", "RECESSION", "PMI")),
        ("RATES", ("TREASURY", "BOND", "YIELD", "GILT", "BUND")),
        ("FX", ("FOREX", "CURRENCY", "DOLLAR", "EURO ", "YEN ", "STERLING")),
        ("COMMODITIES", ("OIL", "BRENT", "GOLD", "COPPER", "NATURAL GAS", "OPEC")),
        ("TECH", ("TECH", "AI ", "ARTIFICIAL INTELLIGENCE", "CHIP", "SEMICONDUCTOR")),
        ("POLITICS", ("ELECTION", "SANCTION", "WAR ", "TARIFF", "GOVERNMENT", "GEOPOLIT")),
        ("EQUITIES", ("STOCK", "SHARE", "EARNINGS", "PROFIT", "REVENUE", "IPO")),
    )
    for category, keywords in categories:
        if any(keyword in text for keyword in keywords):
            return category
    return "MARKETS"
