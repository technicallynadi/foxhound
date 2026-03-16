"""Scout data fetching layer with rate-limited scheduling.

Separates fetch (external API calls) from score (local LLM processing).
Uses timestamp-based freshness checks to avoid redundant API calls.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from foxhound.adapters.github_connector import GitHubConnector, HttpClient, HttpResponse
from foxhound.scout.connectors.base import RawOpportunity
from foxhound.scout.connectors.devto import DevToConnector
from foxhound.scout.connectors.github_events import (
    GitHubEventsConnector,
)
from foxhound.scout.connectors.hackernews import HackerNewsConnector
from foxhound.scout.connectors.lobsters import LobstersConnector
from foxhound.scout.connectors.newsapi import NewsAPIConnector
from foxhound.scout.connectors.producthunt import (
    ProductHuntConnector,
)
from foxhound.scout.connectors.reddit import RedditConnector
from foxhound.scout.connectors.rss import RSSConnector
from foxhound.storage.database import Database, RawOpportunityStore

logger = logging.getLogger(__name__)

DEFAULT_FETCH_INTERVAL_HOURS = 6
DEFAULT_RETENTION_DAYS = 7
MAX_BACKOFF_RETRIES = 3


class SourceConfig(BaseModel):
    """Configuration for a single scout source."""

    enabled: bool = Field(default=True)
    fetch_interval_hours: float = Field(default=DEFAULT_FETCH_INTERVAL_HOURS)
    subreddits: list[str] | None = Field(
        default=None, description="Subreddits to scan (reddit source only)"
    )

    model_config = {"extra": "forbid"}


class ScoutConfig(BaseModel):
    """Scout pipeline configuration from foxhound.yaml."""

    fetch_interval_hours: float = Field(default=DEFAULT_FETCH_INTERVAL_HOURS)
    retention_days: int = Field(default=DEFAULT_RETENTION_DAYS)
    limit: int = Field(default=5, description="Max results per source")
    deep_dive_count: int = Field(default=5, description="Number of top items to scrape")
    topics: list[str] = Field(
        default_factory=list,
        description="Topics to prioritize for deep dive and alerts",
    )
    sources: dict[str, SourceConfig] = Field(default_factory=lambda: {
        "github_trending": SourceConfig(),
        "reddit": SourceConfig(fetch_interval_hours=12),
        "hackernews": SourceConfig(),
        "devto": SourceConfig(fetch_interval_hours=12),
        "lobsters": SourceConfig(),
        "github_events": SourceConfig(),
        "newsapi": SourceConfig(enabled=False, fetch_interval_hours=24),
        "producthunt": SourceConfig(enabled=False, fetch_interval_hours=24),
        "rss": SourceConfig(fetch_interval_hours=12),
    })

    model_config = {"extra": "forbid"}

    def get_source_interval(self, source: str) -> float:
        """Get fetch interval for a source, falling back to global default."""
        src = self.sources.get(source)
        if src:
            return src.fetch_interval_hours
        return self.fetch_interval_hours

    def is_source_enabled(self, source: str) -> bool:
        """Check if a source is enabled."""
        src = self.sources.get(source)
        return src.enabled if src else False


@dataclass
class FetchResult:
    """Result from a single source fetch operation."""

    source: str
    items_fetched: int = 0
    new_items: int = 0
    updated_items: int = 0
    rate_limit_hits: int = 0
    error: str | None = None
    skipped_fresh: bool = False


@dataclass
class FetchSummary:
    """Summary of all fetch operations across sources."""

    results: list[FetchResult] = field(default_factory=list)
    total_new: int = 0
    total_updated: int = 0
    pruned: int = 0


def _make_dedupe_hash(source: str, source_id: str) -> str:
    """Create a dedupe hash from source and source_id."""
    return hashlib.sha256(f"{source}:{source_id}".encode()).hexdigest()[:16]


def _make_raw_id() -> str:
    """Generate a unique raw opportunity ID."""
    return f"raw_{uuid4().hex[:12]}"


class BackoffError(Exception):
    """Raised when all retries are exhausted after rate limiting."""


def _fetch_with_backoff(
    client: HttpClient,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    timeout: int = 30,
) -> HttpResponse:
    """Fetch with exponential backoff on 429 responses."""
    for attempt in range(MAX_BACKOFF_RETRIES + 1):
        response = client.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code != 429:
            return response
        if attempt < MAX_BACKOFF_RETRIES:
            wait = 2 ** attempt
            logger.warning(
                "Rate limited (429) on %s, retry %d/%d in %ds",
                url, attempt + 1, MAX_BACKOFF_RETRIES, wait,
            )
            time.sleep(wait)
    return response


class ScoutFetcher:
    """Fetches data from external sources and stores raw results.

    Separates fetch (API calls) from score (local processing).
    Respects per-source freshness intervals and rate limits.
    """

    def __init__(
        self,
        db: Database,
        http_client: HttpClient,
        config: ScoutConfig | None = None,
        github_token: str | None = None,
        reddit_client_id: str | None = None,
        reddit_client_secret: str | None = None,
    ) -> None:
        self._db = db
        self._store = RawOpportunityStore(db)
        self._config = config or ScoutConfig()
        self._http_client = http_client
        self._github = GitHubConnector(http_client, token=github_token)
        self._reddit = RedditConnector(
            http_client,
            client_id=reddit_client_id,
            client_secret=reddit_client_secret,
        )
        self._hackernews = HackerNewsConnector()
        self._devto = DevToConnector()
        self._lobsters = LobstersConnector()
        self._github_events = GitHubEventsConnector()
        self._newsapi = NewsAPIConnector()
        self._producthunt = ProductHuntConnector()
        self._rss = RSSConnector()

    def fetch_all(
        self,
        force_refresh: bool = False,
        language: str | None = None,
        min_stars: int = 10,
        limit: int = 30,
        query: str | None = None,
    ) -> FetchSummary:
        """Fetch from all enabled sources, respecting freshness intervals.

        Args:
            force_refresh: Bypass freshness checks and fetch regardless.
            language: Filter GitHub results by language.
            min_stars: Minimum stars for GitHub trending.
            limit: Max results per source.
            query: Search keyword to filter across all sources.
        """
        summary = FetchSummary()

        source_fetchers: dict[str, Any] = {
            "github_trending": lambda: self._fetch_github(
                language=language, min_stars=min_stars, limit=limit, query=query,
            ),
            "reddit": lambda: self._fetch_reddit(limit=limit, query=query),
            "hackernews": lambda: self._fetch_hackernews(limit=limit, query=query),
            "devto": lambda: self._fetch_async_connector(self._devto, "devto", limit),
            "lobsters": lambda: self._fetch_async_connector(
                self._lobsters, "lobsters", limit,
            ),
            "github_events": lambda: self._fetch_async_connector(
                self._github_events, "github_events", limit,
            ),
            "newsapi": lambda: self._fetch_async_connector(
                self._newsapi, "newsapi", limit,
            ),
            "producthunt": lambda: self._fetch_async_connector(
                self._producthunt, "producthunt", limit,
            ),
            "rss": lambda: self._fetch_async_connector(self._rss, "rss", limit),
        }

        for source, fetcher_fn in source_fetchers.items():
            if not self._config.is_source_enabled(source):
                continue

            if not force_refresh and self._is_fresh(source):
                summary.results.append(FetchResult(
                    source=source, skipped_fresh=True,
                ))
                continue

            try:
                result = fetcher_fn()
                summary.results.append(result)
                summary.total_new += result.new_items
                summary.total_updated += result.updated_items
            except Exception as exc:
                logger.error("Fetch failed for %s: %s", source, exc)
                summary.results.append(FetchResult(
                    source=source, error=str(exc),
                ))

        pruned = self._store.prune_expired()
        summary.pruned = pruned

        return summary

    def _is_fresh(self, source: str) -> bool:
        """Check if cached data for a source is still within freshness interval."""
        meta = self._store.get_fetch_metadata(source)
        if not meta:
            return False
        last = datetime.fromisoformat(meta["last_fetched_at"])
        interval = self._config.get_source_interval(source)
        return datetime.now() - last < timedelta(hours=interval)

    def _fetch_github(
        self,
        language: str | None = None,
        min_stars: int = 10,
        limit: int = 30,
        query: str | None = None,
    ) -> FetchResult:
        """Fetch trending repos from GitHub."""
        result = FetchResult(source="github_trending")

        repos = self._github.search_trending(
            language=language, min_stars=min_stars, limit=limit, query=query,
        )
        result.items_fetched = len(repos)

        expires_at = (
            datetime.now() + timedelta(days=self._config.retention_days)
        ).isoformat()
        now = datetime.now().isoformat()

        for repo in repos:
            dedupe_hash = _make_dedupe_hash("github_trending", repo.name)
            velocity = self._github.calculate_star_velocity(repo)

            payload = {
                "name": repo.name,
                "description": repo.description,
                "stars": repo.stars,
                "forks": repo.forks,
                "language": repo.language,
                "license_type": repo.license_type,
                "open_issues": repo.open_issues,
                "created_at": repo.created_at,
                "html_url": repo.html_url,
                "topics": repo.topics,
                "star_velocity": velocity,
            }

            is_new = self._store.upsert(
                raw_id=_make_raw_id(),
                source="github_trending",
                source_url=repo.html_url,
                source_id=repo.name,
                title=repo.name,
                raw_payload=json.dumps(payload),
                fetched_at=now,
                expires_at=expires_at,
                dedupe_hash=dedupe_hash,
            )
            if is_new:
                result.new_items += 1
            else:
                result.updated_items += 1

        self._store.update_fetch_metadata(
            source="github_trending",
            items_fetched=len(repos),
            rate_limit_hits=result.rate_limit_hits,
        )
        return result

    def _fetch_reddit(self, limit: int = 25, query: str | None = None) -> FetchResult:
        """Fetch posts from configured subreddits."""
        result = FetchResult(source="reddit")

        reddit_config = self._config.sources.get("reddit")
        subreddits = None
        if reddit_config and hasattr(reddit_config, "subreddits"):
            subreddits = getattr(reddit_config, "subreddits", None)

        posts = self._reddit.scan_all_subreddits(
            subreddits=subreddits, limit_per_sub=limit,
        )

        if query:
            query_lower = query.lower()
            posts = [
                p for p in posts
                if query_lower in p.title.lower() or query_lower in p.selftext.lower()
            ]

        result.items_fetched = len(posts)

        expires_at = (
            datetime.now() + timedelta(days=self._config.retention_days)
        ).isoformat()
        now = datetime.now().isoformat()

        for post in posts:
            dedupe_hash = _make_dedupe_hash("reddit", post.post_id)
            velocity = self._reddit.calculate_upvote_velocity(post)

            payload = {
                "post_id": post.post_id,
                "title": post.title,
                "subreddit": post.subreddit,
                "author": post.author,
                "url": post.url,
                "selftext": post.selftext[:500],
                "upvotes": post.upvotes,
                "comment_count": post.comment_count,
                "created_utc": post.created_utc,
                "github_repos": post.github_repos,
                "upvote_velocity": velocity,
            }

            is_new = self._store.upsert(
                raw_id=_make_raw_id(),
                source="reddit",
                source_url=post.url,
                source_id=post.post_id,
                title=post.title,
                raw_payload=json.dumps(payload),
                fetched_at=now,
                expires_at=expires_at,
                dedupe_hash=dedupe_hash,
            )
            if is_new:
                result.new_items += 1
            else:
                result.updated_items += 1

        self._store.update_fetch_metadata(
            source="reddit",
            items_fetched=len(posts),
            rate_limit_hits=result.rate_limit_hits,
        )
        return result

    def _fetch_async_connector(
        self, connector: Any, source: str, limit: int = 30
    ) -> FetchResult:
        """Fetch from any async BaseScoutConnector and store results."""
        import asyncio

        result = FetchResult(source=source)

        try:
            opportunities: list[RawOpportunity] = asyncio.run(connector.fetch())
        except Exception as exc:
            logger.error("%s fetch failed: %s", source, exc)
            result.error = str(exc)
            return result

        result.items_fetched = len(opportunities)

        expires_at = (
            datetime.now() + timedelta(days=self._config.retention_days)
        ).isoformat()
        now = datetime.now().isoformat()

        for opp in opportunities[:limit]:
            source_id = opp.source_url
            dedupe_hash = _make_dedupe_hash(source, source_id)

            is_new = self._store.upsert(
                raw_id=_make_raw_id(),
                source=source,
                source_url=opp.source_url,
                source_id=source_id,
                title=opp.title,
                raw_payload=json.dumps(opp.raw_metadata),
                fetched_at=now,
                expires_at=expires_at,
                dedupe_hash=dedupe_hash,
            )
            if is_new:
                result.new_items += 1
            else:
                result.updated_items += 1

        self._store.update_fetch_metadata(
            source=source,
            items_fetched=result.items_fetched,
            rate_limit_hits=result.rate_limit_hits,
        )
        return result

    def _fetch_hackernews(self, limit: int = 30, query: str | None = None) -> FetchResult:
        """Fetch top stories from Hacker News."""
        import asyncio

        result = FetchResult(source="hackernews")

        try:
            if query:
                opportunities = asyncio.run(self._hackernews.search(query, limit=limit))
            else:
                opportunities = asyncio.run(self._hackernews.fetch())
        except Exception as exc:
            logger.error("Hacker News fetch failed: %s", exc)
            result.error = str(exc)
            return result

        result.items_fetched = len(opportunities)

        expires_at = (
            datetime.now() + timedelta(days=self._config.retention_days)
        ).isoformat()
        now = datetime.now().isoformat()

        for opp in opportunities[:limit]:
            hn_id = str(opp.raw_metadata.get("hn_id", ""))
            dedupe_hash = _make_dedupe_hash("hackernews", hn_id)

            payload = {
                "hn_id": opp.raw_metadata.get("hn_id"),
                "title": opp.title,
                "score": opp.raw_metadata.get("score", 0),
                "comment_count": opp.raw_metadata.get("comment_count", 0),
                "author": opp.raw_metadata.get("author", ""),
                "external_url": opp.raw_metadata.get("external_url", ""),
                "posted_at": opp.raw_metadata.get("posted_at", ""),
                "source_feed": opp.raw_metadata.get("source_feed", ""),
            }

            is_new = self._store.upsert(
                raw_id=_make_raw_id(),
                source="hackernews",
                source_url=opp.source_url,
                source_id=hn_id,
                title=opp.title,
                raw_payload=json.dumps(payload),
                fetched_at=now,
                expires_at=expires_at,
                dedupe_hash=dedupe_hash,
            )
            if is_new:
                result.new_items += 1
            else:
                result.updated_items += 1

        self._store.update_fetch_metadata(
            source="hackernews",
            items_fetched=result.items_fetched,
            rate_limit_hits=result.rate_limit_hits,
        )
        return result
