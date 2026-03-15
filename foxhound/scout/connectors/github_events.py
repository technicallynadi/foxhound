"""GitHub Events Scout connector.

Fetches public events from the GitHub Events API. Tracks new repos,
repos going public, and new releases. All GitHub event content is
external_untrusted.
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

GITHUB_EVENTS_URL = "https://api.github.com/events"

DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_SEEN_RETENTION_DAYS = 30

SUPPORTED_EVENT_TYPES = ("CreateEvent", "PublicEvent", "ReleaseEvent", "WatchEvent")


class GitHubEventsConnectorConfig(ConnectorConfig):
    """GitHub Events-specific configuration."""

    event_types: list[str] = Field(
        default_factory=lambda: ["CreateEvent", "PublicEvent", "ReleaseEvent"],
        description="Event types to track",
    )
    min_stars_for_release: int = Field(
        default=50, description="Only track releases from repos with this many stars"
    )
    api_key_env: str = Field(default="GITHUB_TOKEN", description="Env var for GitHub token")
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT, description="HTTP timeout")
    seen_retention_days: int = Field(default=DEFAULT_SEEN_RETENTION_DAYS)

    model_config = {"extra": "forbid"}


class GitHubEventsConnector:
    """Scout connector for GitHub public events.

    Fetches events from the GitHub Events API, filtering by event type.
    Uses a GitHub token if available for higher rate limits.
    """

    def __init__(self, db_conn: sqlite3.Connection | None = None) -> None:
        self._config = GitHubEventsConnectorConfig()
        self._db = db_conn
        if self._db:
            self._ensure_schema()

    def connector_name(self) -> str:
        return "github_events"

    def configure(self, config: GitHubEventsConnectorConfig) -> None:
        self._config = config

    async def fetch(self) -> list[RawOpportunity]:
        headers = self._build_headers()
        opportunities: list[RawOpportunity] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=self._config.request_timeout) as client:
            events = await self._fetch_events(client, headers)
            for event in events:
                opp = self._event_to_opportunity(event, seen_ids)
                if opp:
                    opportunities.append(opp)

        if self._db:
            self._record_seen(opportunities)

        return opportunities

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        env_var = self._config.api_key_env
        if not env_var.endswith(("_KEY", "_TOKEN", "_SECRET")):
            return headers
        token = os.environ.get(env_var, "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _fetch_events(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        try:
            resp = await client.get(
                GITHUB_EVENTS_URL, headers=headers, params={"per_page": "100"}
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to fetch GitHub events")
            return []

    def _event_to_opportunity(
        self, event: dict[str, Any], seen_ids: set[str]
    ) -> RawOpportunity | None:
        event_id = event.get("id", "")
        event_type = event.get("type", "")

        if not event_id or event_id in seen_ids:
            return None
        if event_type not in self._config.event_types:
            return None
        if event_type not in SUPPORTED_EVENT_TYPES:
            return None

        if self._db and self._is_seen(event_id):
            return None

        seen_ids.add(event_id)
        payload = event.get("payload", {})
        repo_name = event.get("repo", {}).get("name", "")
        actor = event.get("actor", {}).get("login", "")
        created_at = event.get("created_at", "")

        if event_type == "CreateEvent":
            return self._handle_create_event(event_id, payload, repo_name, actor, created_at)
        elif event_type == "PublicEvent":
            return self._handle_public_event(event_id, repo_name, actor, created_at)
        elif event_type == "ReleaseEvent":
            return self._handle_release_event(event_id, payload, repo_name, actor, created_at)
        return None

    def _handle_create_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        repo_name: str,
        actor: str,
        created_at: str,
    ) -> RawOpportunity | None:
        if payload.get("ref_type") != "repository":
            return None

        return RawOpportunity(
            source_type="github_events",
            source_url=f"https://github.com/{repo_name}",
            title=f"New repository: {repo_name}",
            description=payload.get("description", "") or "",
            raw_metadata={
                "github_event_id": event_id,
                "event_type": "CreateEvent",
                "repo_name": repo_name,
                "actor": actor,
                "created_at": created_at,
            },
            discovered_at=datetime.now(UTC),
            trust_level="external_untrusted",
        )

    def _handle_public_event(
        self,
        event_id: str,
        repo_name: str,
        actor: str,
        created_at: str,
    ) -> RawOpportunity:
        return RawOpportunity(
            source_type="github_events",
            source_url=f"https://github.com/{repo_name}",
            title=f"Repo went public: {repo_name}",
            description="",
            raw_metadata={
                "github_event_id": event_id,
                "event_type": "PublicEvent",
                "repo_name": repo_name,
                "actor": actor,
                "created_at": created_at,
            },
            discovered_at=datetime.now(UTC),
            trust_level="external_untrusted",
        )

    def _handle_release_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        repo_name: str,
        actor: str,
        created_at: str,
    ) -> RawOpportunity | None:
        release = payload.get("release", {})
        tag_name = release.get("tag_name", "")
        body = (release.get("body", "") or "")[:500]

        return RawOpportunity(
            source_type="github_events",
            source_url=f"https://github.com/{repo_name}",
            title=f"New release: {repo_name} — {tag_name}",
            description=body,
            raw_metadata={
                "github_event_id": event_id,
                "event_type": "ReleaseEvent",
                "repo_name": repo_name,
                "actor": actor,
                "release_tag": tag_name,
                "created_at": created_at,
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

    def _is_seen(self, event_id: str) -> bool:
        if not self._db:
            return False
        cursor = self._db.execute(
            "SELECT 1 FROM scout_seen_items "
            "WHERE source_type = 'github_events' AND source_id = ?",
            (event_id,),
        )
        return cursor.fetchone() is not None

    def _record_seen(self, opportunities: list[RawOpportunity]) -> None:
        if not self._db or not opportunities:
            return
        now = datetime.now(UTC).isoformat()
        for opp in opportunities:
            eid = opp.raw_metadata.get("github_event_id")
            if eid is None:
                continue
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO scout_seen_items "
                    "(source_type, source_id, first_seen_at) VALUES (?, ?, ?)",
                    ("github_events", str(eid), now),
                )
            except sqlite3.Error:
                logger.exception("Failed to record seen event %s", eid)
        self._db.commit()
