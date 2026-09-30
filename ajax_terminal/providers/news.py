from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as ET

from ajax_terminal.models.news import NewsItem, infer_news_category
from ajax_terminal.models.quote import DataQuality
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.utils.url_security import require_https_url


_NEWS_HOSTS = ("feeds.finance.yahoo.com", "news.google.com")


class RSSNewsProvider:
    name = "Yahoo Finance RSS"

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        query = urllib.parse.quote(topic or "SPY,QQQ,DIA,EURUSD=X,CL=F,GC=F")
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={query}&region=US&lang=en-US"
        try:
            xml_text = await _fetch_text(url)
            return _parse_rss(xml_text, self.name, topic, limit)
        except Exception as exc:  # pragma: no cover - depends on network availability
            raise ProviderError(str(exc)) from exc


class GoogleNewsRSSProvider:
    name = "Google News RSS"

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        query = _news_query(topic)
        encoded = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        try:
            xml_text = await _fetch_text(url)
            return _parse_rss(xml_text, self.name, topic, limit)
        except Exception as exc:  # pragma: no cover - depends on network availability
            raise ProviderError(str(exc)) from exc


class NewsFallbackProvider:
    name = "THRIVEBERG News Fallback"

    def __init__(self) -> None:
        self.providers = [RSSNewsProvider(), GoogleNewsRSSProvider()]

    async def headlines(self, topic: str | None = None, limit: int = 20) -> list[NewsItem]:
        last_error: Exception | None = None
        for provider in self.providers:
            try:
                return await provider.headlines(topic, limit)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise ProviderError(str(last_error)) from last_error
        return [NewsItem.unavailable(topic or "")]


async def _fetch_text(url: str, timeout: int = 8) -> str:
    safe_url = require_https_url(url, allowed_hosts=_NEWS_HOSTS)

    def _read() -> str:
        request = urllib.request.Request(safe_url, headers={"User-Agent": "THRIVEBERG-Terminal/0.9"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            return response.read().decode("utf-8", errors="replace")

    return await asyncio.to_thread(_read)


def _parse_rss(xml_text: str, provider: str, topic: str | None, limit: int) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title") or "Untitled"
        link = item.findtext("link") or ""
        source = item.findtext("source") or provider
        summary = _clean_html(item.findtext("description") or "")
        pub_date = item.findtext("pubDate")
        timestamp = datetime.now(timezone.utc)
        if pub_date:
            try:
                timestamp = parsedate_to_datetime(pub_date).astimezone(timezone.utc)
            except Exception:
                pass
        topic_tag = (topic or "GENERAL").upper()
        category = infer_news_category(title, [topic_tag])
        items.append(
            NewsItem(
                timestamp=timestamp,
                source=source,
                headline=html.unescape(title).strip(),
                link=link,
                tags=list(dict.fromkeys([topic_tag, category])),
                summary=summary,
                provider=provider,
                quality=DataQuality.DELAYED,
                category=category,
            )
        )
    if not items:
        raise ProviderError("RSS feed returned no items")
    return items


def _news_query(topic: str | None) -> str:
    if not topic or topic.upper() in {"TOP", "MARKETS", "MARKET"}:
        return "global financial markets when:1d"
    mappings = {
        "ECONOMY": "global economy inflation GDP jobs when:3d",
        "CENTRAL BANKS": "Federal Reserve ECB BOE BOJ central banks when:3d",
        "COMPANIES": "stocks companies earnings markets when:2d",
        "TECH": "technology stocks semiconductors AI markets when:2d",
        "POLITICS": "geopolitics tariffs sanctions markets when:2d",
    }
    selected = mappings.get(topic.upper(), topic)
    return f"{selected} finance" if "when:" not in selected else selected


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())
