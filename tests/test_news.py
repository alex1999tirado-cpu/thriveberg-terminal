from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ajax_terminal.models.news import NewsItem, infer_news_category
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.news import _decode_feed, _parse_rss
from ajax_terminal.services.news_service import NewsService
from ajax_terminal.storage.cache import SQLiteCache


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Fed signals rates will remain unchanged</title>
      <link>https://example.com/fed-rates</link>
      <pubDate>Fri, 25 Sep 2026 14:30:00 GMT</pubDate>
      <source>Example Wire</source>
      <description><![CDATA[<p>Officials kept policy steady &amp; published forecasts.</p>]]></description>
    </item>
  </channel>
</rss>
"""


def test_rss_parser_extracts_source_summary_and_category() -> None:
    items = _parse_rss(RSS_SAMPLE, "TEST RSS", "FED", 10)

    assert len(items) == 1
    assert items[0].source == "Example Wire"
    assert items[0].summary == "Officials kept policy steady & published forecasts."
    assert items[0].category == "CENTRAL BANKS"
    assert items[0].quality == DataQuality.DELAYED
    assert infer_news_category("Gold rises as oil retreats") == "COMMODITIES"


def test_news_service_aggregates_sorts_and_deduplicates(tmp_path) -> None:
    now = datetime.now(timezone.utc)

    class Provider:
        def __init__(self, name: str, items: list[NewsItem]) -> None:
            self.name = name
            self.items = items

        async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
            return self.items

    duplicate_old = NewsItem(
        now - timedelta(minutes=2),
        "Wire A",
        "Markets rally after policy decision",
        quality=DataQuality.DELAYED,
    )
    duplicate_new = NewsItem(
        now,
        "Wire B",
        "Markets rally after policy decision",
        quality=DataQuality.DELAYED,
    )
    second = NewsItem(
        now - timedelta(minutes=1),
        "Wire C",
        "Oil slips as inventories rise",
        quality=DataQuality.DELAYED,
    )
    service = NewsService(cache=SQLiteCache(tmp_path / "news.sqlite3"))
    service.providers = [Provider("A", [duplicate_old, second]), Provider("B", [duplicate_new])]

    items = asyncio.run(service.headlines("MARKETS", limit=10))

    assert [item.headline for item in items] == [
        "Markets rally after policy decision",
        "Oil slips as inventories rise",
    ]
    assert items[0].source == "Wire B"


def test_news_service_uses_cached_real_stories_before_mock(tmp_path) -> None:
    database = tmp_path / "cached-news.sqlite3"
    now = datetime.now(timezone.utc)

    class LiveProvider:
        name = "Live"

        async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
            return [
                NewsItem(
                    now,
                    "Live Wire",
                    "Cached market story",
                    link="https://example.com/story",
                    quality=DataQuality.DELAYED,
                )
            ]

    class BrokenProvider:
        name = "Broken"

        async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
            raise RuntimeError("offline")

    live = NewsService(cache=SQLiteCache(database))
    live.providers = [LiveProvider()]
    assert asyncio.run(live.headlines("AAPL"))[0].quality == DataQuality.DELAYED

    offline = NewsService(cache=SQLiteCache(database))
    offline.providers = [BrokenProvider()]
    cached = asyncio.run(offline.headlines("AAPL"))

    assert cached[0].headline == "Cached market story"
    assert cached[0].quality == DataQuality.CACHED


def test_news_feed_falls_back_to_windows_encoding_without_replacement_characters() -> None:
    payload = b"Corteva stock isn\x92t down"
    assert _decode_feed(payload) == "Corteva stock isn\u2019t down"
