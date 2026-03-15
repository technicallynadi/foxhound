"""Product Hunt Scout connector.

Fetches top-voted product launches from the Product Hunt GraphQL API.
Requires a developer token. All Product Hunt content is external_untrusted.
"""

import logging
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

PRODUCTHUNT_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30

POSTS_QUERY = """
query($postedAfter: DateTime!) {
  posts(order: VOTES, postedAfter: $postedAfter) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        website
        createdAt
        topics {
          edges {
            node {
              name
            }
          }
        }
      }
    }
  }
}
"""


class ProductHuntConnectorConfig(ConnectorConfig):
    """Product Hunt-specific configuration."""

    enabled: bool = Field(default=False, description="Disabled by default — requires API token")
    api_key_env: str = Field(
        default="PRODUCTHUNT_API_TOKEN", description="Env var for API token"
    )
    min_votes: int = Field(default=50, description="Minimum vote count")
    lookback_days: int = Field(default=7, description="Fetch posts from last N days")
    fetch_interval_hours: int = Field(default=24)
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout")
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}


class ProductHuntConnector:
    """Scout connector for Product Hunt.

    Fetches recently launched products via the GraphQL API,
    filtered by vote count. Disabled by default — requires
    a developer token from producthunt.com.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = ProductHuntConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "producthunt"

    def configure(self, config: ProductHuntConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        env_var = self._config.api_key_env
        if not env_var.endswith(("_KEY", "_TOKEN", "_SECRET")):
            logger.warning("Refusing unsafe api_key_env: %s", env_var)
            return []
        token = os.environ.get(env_var, "")
        if not token:
            logger.warning(
                "Product Hunt token not found in env var %s — skipping",
                self._config.api_key_env,
            )
            return []

        opportunities: list[RawOpportunity] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            posts = await self._fetch_posts(client, token)
            for node in posts:
                opp = self._node_to_opportunity(node, seen_ids)
                if opp:
                    opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _fetch_posts(
        self, client: httpx.AsyncClient, token: str
    ) -> list[dict[str, Any]]:
        posted_after = (
            datetime.now(UTC) - timedelta(days=self._config.lookback_days)
        ).isoformat()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": POSTS_QUERY,
            "variables": {"postedAfter": posted_after},
        }

        try:
            resp = await client.post(PRODUCTHUNT_GRAPHQL_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            edges = data.get("data", {}).get("posts", {}).get("edges", [])
            return [edge["node"] for edge in edges if "node" in edge]
        except Exception:
            logger.exception("Failed to fetch Product Hunt posts")
            return []

    def _node_to_opportunity(
        self, node: dict[str, Any], seen_ids: set[str]
    ) -> RawOpportunity | None:
        ph_id = node.get("id", "")
        if not ph_id or ph_id in seen_ids:
            return None

        votes = node.get("votesCount", 0)
        if votes < self._config.min_votes:
            return None

        if self._db and self._is_seen(ph_id):
            return None

        seen_ids.add(ph_id)

        topics_edges = node.get("topics", {}).get("edges", [])
        topics = [t["node"]["name"] for t in topics_edges if "node" in t]

        return RawOpportunity(
            source_type="producthunt",
            source_url=node.get("url", ""),
            title=node.get("name", ""),
            description=node.get("tagline", ""),
            raw_metadata={
                "ph_id": ph_id,
                "votes": votes,
                "comments": node.get("commentsCount", 0),
                "website": node.get("website", ""),
                "topics": topics,
                "created_at": node.get("createdAt", ""),
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

    def _is_seen(self, ph_id: str) -> bool:
        if not self._db:
            return False
        cursor = self._db.execute(
            "SELECT 1 FROM scout_seen_items "
            "WHERE source_type = 'producthunt' AND source_id = ?",
            (ph_id,),
        )
        return cursor.fetchone() is not None

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        if not self._db or not opportunities:
            return
        now = datetime.now(UTC).isoformat()
        for opp in opportunities:
            pid = opp.raw_metadata.get("ph_id")
            if pid is None:
                continue
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("producthunt", str(pid), now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen product %s", pid)
        self._db.commit()
