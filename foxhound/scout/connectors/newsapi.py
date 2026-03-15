"""NewsAPI Scout connector.

Fetches technology news articles from the NewsAPI.org API.
Requires an API key (free tier: 100 requests/day).
All NewsAPI content is external_untrusted.
"""

import logging
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import Field

from foxhound.scout.connectors.base import ConnectorConfig, RawOpportunity

logger = logging.getLogger(__name__)

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30


class NewsAPIConnectorConfig(ConnectorConfig):
    """NewsAPI-specific configuration."""

    enabled: bool = Field(default=False, description="Disabled by default — requires API key")
    api_key_env: str = Field(default="NEWSAPI_API_KEY", description="Env var for API key")
    queries: list[str] = Field(
        default_factory=lambda: ["developer tools", "open source project", "AI agent"],
        description="Search queries to run",
    )
    max_results_per_query: int = Field(default=20, description="Max results per query")
    fetch_interval_hours: int = Field(default=24, description="Conservative for free tier")
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout")
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}


class NewsAPIConnector:
    """Scout connector for NewsAPI.org.

    Searches for technology news articles using configurable queries.
    Disabled by default — requires a free API key from newsapi.org.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = NewsAPIConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "newsapi"

    def configure(self, config: NewsAPIConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        env_var = self._config.api_key_env
        if not env_var.endswith(("_KEY", "_TOKEN", "_SECRET")):
            logger.warning("Refusing unsafe api_key_env: %s", env_var)
            return []
        api_key = os.environ.get(env_var, "")
        if not api_key:
            logger.warning(
                "NewsAPI key not found in env var %s — skipping",
                self._config.api_key_env,
            )
            return []

        seen_urls: set[str] = set()
        opportunities: list[RawOpportunity] = []

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            for query in self._config.queries:
                articles = await self._search(client, api_key, query)
                for article in articles:
                    opp = self._article_to_opportunity(article, query, seen_urls)
                    if opp:
                        opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    async def _search(
        self, client: httpx.AsyncClient, api_key: str, query: str
    ) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "sortBy": "relevancy",
            "pageSize": str(self._config.max_results_per_query),
            "apiKey": api_key,
        }
        try:
            resp = await client.get(NEWSAPI_EVERYTHING_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("articles", [])
        except Exception:
            logger.exception("NewsAPI search failed for query: %s", query)
            return []

    def _article_to_opportunity(
        self, article: dict[str, Any], query: str, seen_urls: set[str]
    ) -> RawOpportunity | None:
        url = article.get("url", "")
        if not url or url in seen_urls:
            return None

        if self._db and self._is_seen(url):
            return None

        seen_urls.add(url)

        return RawOpportunity(
            source_type="newsapi",
            source_url=url,
            title=article.get("title", ""),
            description=article.get("description", ""),
            raw_metadata={
                "source_name": article.get("source", {}).get("name", ""),
                "author": article.get("author", ""),
                "published_at": article.get("publishedAt", ""),
                "query_matched": query,
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
            "SELECT 1 FROM scout_seen_items WHERE source_type = 'newsapi' AND source_id = ?",
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
                    ("newsapi", opp.source_url, now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen article %s", opp.source_url)
        self._db.commit()
