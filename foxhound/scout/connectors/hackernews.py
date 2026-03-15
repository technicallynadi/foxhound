"""Hacker News Scout connector.

Fetches top, show, and ask stories from the HN Firebase API.
Filters by score and comment thresholds, deduplicates across
sources and fetch cycles. All HN content is external_untrusted.
"""

import asyncio
import html
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

VALID_SOURCES = ("topstories", "showstories", "askstories")

DEFAULT_REQUEST_TIMEOUT = 10
DEFAULT_BATCH_SIZE = 20
DEFAULT_SEEN_RETENTION_DAYS = 30

HTML_TAG_RE = re.compile(r"<[^>]+>")

SEEN_ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_seen_items (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (source_type, source_id)
);
"""


class HNConnectorConfig(ConnectorConfig):
    """Hacker News-specific configuration."""

    min_score: int = Field(default=50, description="Minimum score threshold")
    min_comments: int = Field(default=10, description="Minimum comment count")
    sources: list[str] = Field(
        default_factory=lambda: list(VALID_SOURCES),
        description="HN source feeds to scan",
    )
    max_items_per_source: int = Field(
        default=100, description="Max items to fetch per source feed"
    )
    request_timeout: int = Field(
        default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout in seconds"
    )
    batch_size: int = Field(
        default=DEFAULT_BATCH_SIZE, description="Concurrent fetch batch size"
    )
    seen_retention_days: int = Field(
        default=DEFAULT_SEEN_RETENTION_DAYS, description="Days to keep seen item records"
    )

    model_config = {"extra": "forbid"}


def sanitize_title(raw_title: str) -> str:
    """Decode HTML entities and strip tags from a title."""
    decoded = html.unescape(raw_title)
    return HTML_TAG_RE.sub("", decoded).strip()


class HackerNewsConnector:
    """Scout connector for Hacker News.

    Fetches stories from the public HN Firebase API, filters by
    score/comment thresholds, deduplicates across sources, and
    tracks previously seen items in SQLite.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = HNConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        """Return the connector identifier."""
        return "hackernews"

    def configure(self, config: HNConnectorConfig) -> None:
        """Apply configuration."""
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        """Fetch and filter stories from all configured HN sources."""
        all_ids: dict[int, str] = {}  # id -> first source that found it

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            # Fetch story IDs from each source
            for source in self._config.sources:
                if source not in VALID_SOURCES:
                    logger.warning("Skipping invalid source: %s", source)
                    continue
                ids = await self._fetch_source_ids(client, source)
                for item_id in ids[: self._config.max_items_per_source]:
                    if item_id not in all_ids:
                        all_ids[item_id] = source

            # Remove already-seen items
            if self._db:
                all_ids = self._filter_seen(all_ids)

            if not all_ids:
                return []

            # Fetch item details in batches
            items = await self._fetch_items_batched(client, list(all_ids.keys()))

        # Filter and convert
        opportunities: list[RawOpportunity] = []
        for item in items:
            source_feed = all_ids.get(item.get("id", 0), "unknown")
            opp = self._item_to_opportunity(item, source_feed)
            if opp:
                opportunities.append(opp)

        # Record seen items
        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _fetch_source_ids(
        self, client: httpx.AsyncClient, source: str
    ) -> list[int]:
        """Fetch story IDs from a single source endpoint."""
        url = f"{HN_API_BASE}/{source}.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            ids = resp.json()
            return ids if isinstance(ids, list) else []
        except Exception:
            logger.exception("Failed to fetch %s", source)
            return []

    async def _fetch_items_batched(
        self, client: httpx.AsyncClient, item_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Fetch item details in concurrent batches."""
        items: list[dict[str, Any]] = []
        batch_size = self._config.batch_size

        for i in range(0, len(item_ids), batch_size):
            batch = item_ids[i : i + batch_size]
            tasks = [self._fetch_item(client, iid) for iid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    items.append(result)

        return items

    async def _fetch_item(
        self, client: httpx.AsyncClient, item_id: int
    ) -> dict[str, Any]:
        """Fetch a single item by ID."""
        url = f"{HN_API_BASE}/item/{item_id}.json"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _item_to_opportunity(
        self, item: dict[str, Any], source_feed: str
    ) -> RawOpportunity | None:
        """Convert an HN item to a RawOpportunity, applying filters."""
        if not item or not item.get("id"):
            return None

        # Skip non-stories, dead, and deleted items
        if item.get("type") != "story":
            return None
        if item.get("dead") or item.get("deleted"):
            return None

        score = item.get("score", 0)
        comment_count = item.get("descendants", 0)

        if score < self._config.min_score:
            return None
        if comment_count < self._config.min_comments:
            return None

        title = sanitize_title(item.get("title", ""))
        if not title:
            return None

        posted_at = datetime.fromtimestamp(
            item.get("time", 0), tz=timezone.utc
        ).isoformat()

        return RawOpportunity(
            source_type="hackernews",
            source_url=f"https://news.ycombinator.com/item?id={item['id']}",
            title=title,
            description=None,
            raw_metadata={
                "hn_id": item["id"],
                "score": score,
                "comment_count": comment_count,
                "author": item.get("by", ""),
                "external_url": item.get("url", ""),
                "posted_at": posted_at,
                "source_feed": source_feed,
            },
            discovered_at=datetime.now(timezone.utc),
            trust_level="external_untrusted",
        )

    async def search(self, query: str, limit: int = 30) -> list[RawOpportunity]:
        """Search HN stories via the Algolia API."""
        url = "https://hn.algolia.com/api/v1/search"
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": str(min(limit, 100)),
        }

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("HN search failed for query: %s", query)
                return []

        opportunities: list[RawOpportunity] = []
        for hit in data.get("hits", []):
            item = {
                "id": int(hit.get("objectID", 0)),
                "type": "story",
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "score": hit.get("points", 0),
                "descendants": hit.get("num_comments", 0),
                "by": hit.get("author", ""),
                "time": hit.get("created_at_i", 0),
            }
            opp = self._item_to_opportunity(item, "search")
            if opp:
                opportunities.append(opp)

        return opportunities

    # -- SQLite seen-items tracking --

    def _ensure_schema(self) -> None:
        """Create the scout_seen_items table if it doesn't exist."""
        if self._db:
            self._db.execute(SEEN_ITEMS_SCHEMA)
            self._db.commit()

    def _filter_seen(self, ids: dict[int, str]) -> dict[int, str]:
        """Remove IDs that have already been seen."""
        if not self._db or not ids:
            return ids

        placeholders = ",".join("?" for _ in ids)
        cursor = self._db.execute(
            f"SELECT source_id FROM scout_seen_items "
            f"WHERE source_type = 'hackernews' AND source_id IN ({placeholders})",
            [str(i) for i in ids],
        )
        seen = {row[0] for row in cursor.fetchall()}
        return {iid: src for iid, src in ids.items() if str(iid) not in seen}

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        """Record newly fetched items as seen."""
        if not self._db or not opportunities:
            return

        now = datetime.now(timezone.utc).isoformat()
        for opp in opportunities:
            hn_id = opp.raw_metadata.get("hn_id")
            if hn_id is None:
                continue
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("hackernews", str(hn_id), now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen item %s", hn_id)
        self._db.commit()

    def prune_seen(self) -> int:
        """Remove seen items older than retention period. Returns count pruned."""
        if not self._db:
            return 0

        cutoff = datetime.now(timezone.utc).isoformat()
        # Calculate cutoff by subtracting retention days
        from datetime import timedelta

        cutoff_dt = datetime.now(timezone.utc) - timedelta(
            days=self._config.seen_retention_days
        )
        cutoff = cutoff_dt.isoformat()

        cursor = self._db.execute(
            "DELETE FROM scout_seen_items "
            "WHERE source_type = 'hackernews' AND first_seen_at < ?",
            (cutoff,),
        )
        self._db.commit()
        return cursor.rowcount
