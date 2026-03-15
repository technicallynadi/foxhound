"""RSS/Atom Feed Scout connector.

Fetches articles from user-configured RSS and Atom feeds using feedparser.
The most flexible connector — users can add any feed URL.
All RSS content is external_untrusted.
"""

import html
import logging
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30

HTML_TAG_RE = re.compile(r"<[^>]+>")


_ALLOWED_SCHEMES = ("http://", "https://")


class FeedConfig(BaseModel):
    """Configuration for a single RSS/Atom feed."""

    url: str
    name: str

    model_config = {"extra": "forbid"}

    def is_safe_url(self) -> bool:
        """Validate that the feed URL uses an allowed scheme."""
        return self.url.lower().startswith(_ALLOWED_SCHEMES)


class RSSConnectorConfig(ConnectorConfig):
    """RSS connector configuration."""

    feeds: list[FeedConfig] = Field(
        default_factory=lambda: [
            FeedConfig(url="https://hnrss.org/newest?points=100", name="HN 100+ points"),
            FeedConfig(
                url="https://medium.com/feed/tag/developer-tools", name="Medium: Developer Tools"
            ),
            FeedConfig(
                url="https://medium.com/feed/tag/open-source", name="Medium: Open Source"
            ),
        ],
        description="RSS/Atom feeds to monitor",
    )
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout")
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}


def sanitize_html(text: str) -> str:
    """Strip HTML tags and decode entities."""
    decoded = html.unescape(text)
    return HTML_TAG_RE.sub("", decoded).strip()


class RSSConnector:
    """Scout connector for RSS/Atom feeds.

    Fetches entries from configured feeds using feedparser,
    normalizes to RawOpportunity, and deduplicates by entry URL.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = RSSConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "rss"

    def configure(self, config: RSSConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed — run: pip install feedparser")
            return []

        seen_urls: set[str] = set()
        opportunities: list[RawOpportunity] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            for feed_config in self._config.feeds:
                if not feed_config.is_safe_url():
                    logger.warning("Skipping unsafe feed URL: %s", feed_config.url)
                    continue
                entries = await self._fetch_feed(client, feedparser, feed_config)
                for entry in entries:
                    opp = self._entry_to_opportunity(entry, feed_config, seen_urls)
                    if opp:
                        opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        feedparser: Any,
        feed_config: FeedConfig,
    ) -> list[Any]:
        try:
            resp = await client.get(feed_config.url)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
            return parsed.get("entries", [])
        except Exception:
            logger.exception("Failed to fetch RSS feed: %s", feed_config.name)
            return []

    def _get_entry_attr(self, entry: Any, key: str, default: Any = "") -> Any:
        """Get attribute from a feedparser entry (supports both dict and object)."""
        val = getattr(entry, key, None)
        if val is not None:
            return val
        if isinstance(entry, dict):
            return entry.get(key, default)
        return default

    def _entry_to_opportunity(
        self, entry: Any, feed_config: FeedConfig, seen_urls: set[str]
    ) -> RawOpportunity | None:
        link = self._get_entry_attr(entry, "link", "")
        if not link or link in seen_urls:
            return None

        if self._db and self._is_seen(link):
            return None

        seen_urls.add(link)

        title = sanitize_html(self._get_entry_attr(entry, "title", ""))
        summary = self._get_entry_attr(entry, "summary", "")
        description = sanitize_html(summary)[:500] if summary else ""

        tags_raw = self._get_entry_attr(entry, "tags", [])
        tags = []
        if isinstance(tags_raw, list):
            for t in tags_raw:
                term = t.get("term", "") if isinstance(t, dict) else getattr(t, "term", "")
                if term:
                    tags.append(term)

        author = self._get_entry_attr(entry, "author", "")
        published = self._get_entry_attr(entry, "published", "")

        return RawOpportunity(
            source_type="rss",
            source_url=link,
            title=title,
            description=description,
            raw_metadata={
                "feed_name": feed_config.name,
                "feed_url": feed_config.url,
                "author": author,
                "published_at": published,
                "tags": tags,
            },
            discovered_at=datetime.now(UTC),
            trust_level="external_untrusted",
        )

    # -- SQLite seen-items tracking --

    def _ensure_schema(self) -> None:
        if self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS scout_seen_items ("
                "source_type TEXT NOT NULL, "
                "source_id TEXT NOT NULL, "
                "first_seen_at TEXT NOT NULL, "
                "PRIMARY KEY (source_type, source_id))"
            )
            self._db.commit()

    def _is_seen(self, url: str) -> bool:
        if not self._db:
            return False
        cursor = self._db.execute(
            "SELECT 1 FROM scout_seen_items WHERE source_type = 'rss' AND source_id = ?",
            (url,),
        )
        return cursor.fetchone() is not None

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        if not self._db or not opportunities:
            return
        now = datetime.now(UTC).isoformat()
        for opp in opportunities:
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("rss", opp.source_url, now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen RSS entry %s", opp.source_url)
        self._db.commit()
