from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from ajax_terminal.models.news import NewsItem
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.news import GoogleNewsRSSProvider, RSSNewsProvider
from ajax_terminal.storage.cache import SQLiteCache

LOGGER = logging.getLogger(__name__)


class NewsService:
    NEWS_TTL = 120

    def __init__(self, cache: SQLiteCache | None = None) -> None:
        self.cache = cache or SQLiteCache()
        self.providers = [RSSNewsProvider(), GoogleNewsRSSProvider()]

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        calls = [provider.headlines(topic, limit) for provider in self.providers]
        results = await asyncio.gather(*calls, return_exceptions=True)
        collected: list[NewsItem] = []
        for provider, result in zip(self.providers, results):
            if isinstance(result, Exception):
                LOGGER.warning("news fallback provider=%s topic=%s error=%s", provider.name, topic, result)
                continue
            collected.extend(result)

        real_items = [
            item for item in collected if item.quality not in {DataQuality.MOCK, DataQuality.UNAVAILABLE}
        ]
        if real_items:
            items = _deduplicate(real_items)[:limit]
            self._cache_items(topic, items)
            return items

        # Mock providers are never configured in production, but tests may inject one.
        injected_test_items = [item for item in collected if item.quality == DataQuality.MOCK]
        if injected_test_items:
            return _deduplicate(injected_test_items)[:limit]

        cached = self._cached_items(topic)
        if cached:
            return cached[:limit]
        return []

    def _cache_items(self, topic: str | None, items: list[NewsItem]) -> None:
        payload = [
            {
                "timestamp": item.timestamp.isoformat(),
                "source": item.source,
                "headline": item.headline,
                "link": item.link,
                "tags": item.tags,
                "summary": item.summary,
                "provider": item.provider,
                "category": item.category,
                "author": item.author,
            }
            for item in items
        ]
        try:
            self.cache.set_json(_cache_key(topic), payload, self.NEWS_TTL)
        except Exception as exc:
            LOGGER.warning("news cache write failed topic=%s error=%s", topic, exc)

    def _cached_items(self, topic: str | None) -> list[NewsItem]:
        try:
            payload = self.cache.get_stale_json(_cache_key(topic))
        except Exception as exc:
            LOGGER.warning("news cache read failed topic=%s error=%s", topic, exc)
            return []
        if not isinstance(payload, list):
            return []
        items: list[NewsItem] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            try:
                items.append(
                    NewsItem(
                        timestamp=datetime.fromisoformat(str(row["timestamp"])),
                        source=str(row.get("source", "UNKNOWN")),
                        headline=str(row["headline"]),
                        link=str(row.get("link", "")),
                        tags=list(row.get("tags", [])),
                        summary=str(row.get("summary", "")),
                        provider=str(row.get("provider", "CACHE")),
                        quality=DataQuality.CACHED,
                        category=str(row.get("category", "MARKETS")),
                        author=str(row.get("author", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(items, key=lambda item: item.timestamp, reverse=True)


def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    unique: dict[str, NewsItem] = {}
    for item in sorted(items, key=lambda story: story.timestamp, reverse=True):
        key = re.sub(r"[^A-Z0-9]+", " ", item.headline.upper()).strip()
        if key and key not in unique:
            unique[key] = item
    return list(unique.values())


def _cache_key(topic: str | None) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "-", (topic or "TOP").upper()).strip("-")
    return f"news:v3:{normalized or 'TOP'}"
