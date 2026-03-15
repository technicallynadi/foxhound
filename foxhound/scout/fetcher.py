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
from foxhound.adapters.reddit_connector import RedditConnector
from foxhound.storage.database import Database, RawOpportunityStore

logger = logging.getLogger(__name__)

DEFAULT_FETCH_INTERVAL_HOURS = 6
DEFAULT_RETENTION_DAYS = 7
MAX_BACKOFF_RETRIES = 3


class SourceConfig(BaseModel):
    """Configuration for a single scout source."""

    enabled: bool = Field(default=True)
    fetch_interval_hours: float = Field(default=DEFAULT_FETCH_INTERVAL_HOURS)

    model_config = {"extra": "forbid"}


class ScoutConfig(BaseModel):
    """Scout pipeline configuration from foxhound.yaml."""

    fetch_interval_hours: float = Field(default=DEFAULT_FETCH_INTERVAL_HOURS)
    retention_days: int = Field(default=DEFAULT_RETENTION_DAYS)
    sources: dict[str, SourceConfig] = Field(default_factory=lambda: {
        "github_trending": SourceConfig(),
        "reddit": SourceConfig(fetch_interval_hours=12),
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

    def fetch_all(
        self,
        force_refresh: bool = False,
        language: str | None = None,
        min_stars: int = 10,
        limit: int = 30,
    ) -> FetchSummary:
        """Fetch from all enabled sources, respecting freshness intervals.

        Args:
            force_refresh: Bypass freshness checks and fetch regardless.
            language: Filter GitHub results by language.
            min_stars: Minimum stars for GitHub trending.
            limit: Max results per source.
        """
        summary = FetchSummary()

        source_fetchers: dict[str, Any] = {
            "github_trending": lambda: self._fetch_github(
                language=language, min_stars=min_stars, limit=limit
            ),
            "reddit": lambda: self._fetch_reddit(limit=limit),
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
    ) -> FetchResult:
        """Fetch trending repos from GitHub."""
        result = FetchResult(source="github_trending")

        repos = self._github.search_trending(
            language=language, min_stars=min_stars, limit=limit,
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

    def _fetch_reddit(self, limit: int = 25) -> FetchResult:
        """Fetch posts from configured subreddits."""
        result = FetchResult(source="reddit")

        reddit_config = self._config.sources.get("reddit")
        subreddits = None
        if reddit_config and hasattr(reddit_config, "subreddits"):
            subreddits = getattr(reddit_config, "subreddits", None)

        posts = self._reddit.scan_all_subreddits(
            subreddits=subreddits, limit_per_sub=limit,
        )
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
