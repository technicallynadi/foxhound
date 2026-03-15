"""Lobsters Scout connector.

Fetches hottest and newest stories from the Lobsters JSON API.
Filters by score and comment thresholds, deduplicates across
feeds. All Lobsters content is external_untrusted.
"""

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

LOBSTERS_BASE = "https://lobste.rs"

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30


VALID_FEEDS = ("hottest", "newest", "active")


class LobstersConnectorConfig(ConnectorConfig):
    """Lobsters-specific configuration."""

    feeds: list[str] = Field(
        default_factory=lambda: ["hottest", "newest"],
        description="Lobsters feeds to scan",
    )
    min_score: int = Field(default=10, description="Minimum score threshold")
    min_comments: int = Field(default=3, description="Minimum comment count")
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT)
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}

    @__import__("pydantic").field_validator("feeds")
    @classmethod
    def validate_feeds(cls, v: list[str]) -> list[str]:
        """Reject invalid feed names at config parse time."""
        for feed in v:
            if feed not in VALID_FEEDS:
                raise ValueError(
                    f"Invalid feed '{feed}'. Must be one of: "
                    f"{', '.join(VALID_FEEDS)}"
                )
        return v


class LobstersConnector:
    """Scout connector for Lobsters.

    Fetches stories from the public Lobsters JSON API, filters by
    score/comment thresholds, and deduplicates across feeds.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = LobstersConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "lobsters"

    def configure(self, config: LobstersConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        seen_ids: set[str] = set()
        opportunities: list[RawOpportunity] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            for feed in self._config.feeds:
                if feed not in VALID_FEEDS:
                    logger.warning("Skipping invalid Lobsters feed: %s", feed)
                    continue
                items = await self._fetch_feed(client, feed)
                for item in items:
                    opp = self._item_to_opportunity(item, seen_ids)
                    if opp:
                        opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed: str
    ) -> list[dict[str, Any]]:
        url = f"{LOBSTERS_BASE}/{feed}.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to fetch Lobsters feed: %s", feed)
            return []

    def _item_to_opportunity(
        self, item: dict[str, Any], seen_ids: set[str]
    ) -> RawOpportunity | None:
        short_id = item.get("short_id", "")
        if not short_id or short_id in seen_ids:
            return None

        score = item.get("score", 0)
        comments = item.get("comment_count", 0)

        if score < self._config.min_score:
            return None
        if comments < self._config.min_comments:
            return None

        if self._db and self._is_seen(short_id):
            return None

        seen_ids.add(short_id)

        comments_url = item.get("comments_url", f"{LOBSTERS_BASE}/s/{short_id}")

        return RawOpportunity(
            source_type="lobsters",
            source_url=comments_url,
            title=item.get("title", ""),
            description=item.get("description", ""),
            raw_metadata={
                "lobsters_id": short_id,
                "score": score,
                "comments": comments,
                "tags": item.get("tags", []),
                "author": (
                    item["submitter_user"]["username"]
                    if isinstance(item.get("submitter_user"), dict)
                    else str(item.get("submitter_user", ""))
                ),
                "external_url": item.get("url", ""),
                "created_at": item.get("created_at", ""),
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

    def _is_seen(self, short_id: str) -> bool:
        if not self._db:
            return False
        cursor = self._db.execute(
            "SELECT 1 FROM scout_seen_items WHERE source_type = 'lobsters' AND source_id = ?",
            (short_id,),
        )
        return cursor.fetchone() is not None

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        if not self._db or not opportunities:
            return
        now = datetime.now(UTC).isoformat()
        for opp in opportunities:
            lid = opp.raw_metadata.get("lobsters_id")
            if lid is None:
                continue
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("lobsters", str(lid), now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen item %s", lid)
        self._db.commit()
