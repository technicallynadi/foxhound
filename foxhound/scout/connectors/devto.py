"""Dev.to Scout connector.

Fetches trending and tagged articles from the Dev.to API.
Filters by reaction and comment thresholds, deduplicates
across tag queries. All Dev.to content is external_untrusted.
"""

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

DEVTO_API_BASE = "https://dev.to/api"

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30


class DevToConnectorConfig(ConnectorConfig):
    """Dev.to-specific configuration."""

    tags: list[str] = Field(
        default_factory=lambda: ["opensource", "ai", "webdev", "productivity", "tools"],
        description="Tags to scan for articles",
    )
    min_reactions: int = Field(default=20, description="Minimum positive reactions")
    min_comments: int = Field(default=5, description="Minimum comment count")
    max_items_per_tag: int = Field(default=30, description="Max items fetched per tag")
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout")
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}


class DevToConnector:
    """Scout connector for Dev.to.

    Fetches articles by tag and trending feeds from the public Dev.to API,
    filters by reaction/comment thresholds, and deduplicates across tags.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = DevToConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "devto"

    def configure(self, config: DevToConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        seen_ids: set[int] = set()
        opportunities: list[RawOpportunity] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            for tag in self._config.tags:
                items = await self._fetch_tag(client, tag)
                for item in items:
                    opp = self._item_to_opportunity(item, seen_ids)
                    if opp:
                        opportunities.append(opp)

            # Also fetch rising articles (no tag filter)
            rising = await self._fetch_rising(client)
            for item in rising:
                opp = self._item_to_opportunity(item, seen_ids)
                if opp:
                    opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _fetch_tag(
        self, client: httpx.AsyncClient, tag: str
    ) -> list[dict[str, Any]]:
        url = f"{DEVTO_API_BASE}/articles"
        params = {"tag": tag, "top": "7", "per_page": str(self._config.max_items_per_tag)}
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to fetch Dev.to tag: %s", tag)
            return []

    async def _fetch_rising(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        url = f"{DEVTO_API_BASE}/articles"
        params = {"state": "rising", "per_page": "50"}
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to fetch Dev.to rising articles")
            return []

    def _item_to_opportunity(
        self, item: dict[str, Any], seen_ids: set[int]
    ) -> RawOpportunity | None:
        article_id = item.get("id")
        if not article_id or article_id in seen_ids:
            return None

        reactions = item.get("positive_reactions_count", 0)
        comments = item.get("comments_count", 0)

        if reactions < self._config.min_reactions:
            return None
        if comments < self._config.min_comments:
            return None

        if self._db and self._is_seen(article_id):
            return None

        seen_ids.add(article_id)

        return RawOpportunity(
            source_type="devto",
            source_url=item.get("url", ""),
            title=item.get("title", ""),
            description=item.get("description", ""),
            raw_metadata={
                "devto_id": article_id,
                "reactions": reactions,
                "comments": comments,
                "tags": item.get("tag_list", []),
                "author": item.get("user", {}).get("username", ""),
                "published_at": item.get("published_at", ""),
                "reading_time": item.get("reading_time_minutes", 0),
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

    def _is_seen(self, article_id: int) -> bool:
        if not self._db:
            return False
        cursor = self._db.execute(
            "SELECT 1 FROM scout_seen_items WHERE source_type = 'devto' AND source_id = ?",
            (str(article_id),),
        )
        return cursor.fetchone() is not None

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        if not self._db or not opportunities:
            return
        now = datetime.now(UTC).isoformat()
        for opp in opportunities:
            devto_id = opp.raw_metadata.get("devto_id")
            if devto_id is None:
                continue
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("devto", str(devto_id), now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen item %s", devto_id)
        self._db.commit()
