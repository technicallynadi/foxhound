"""Tests for the GitHub Events Scout connector."""

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.github_events import (
    GitHubEventsConnector,
    GitHubEventsConnectorConfig,
)


def _make_event(
    event_id: str = "ev1",
    event_type: str = "ReleaseEvent",
    repo_name: str = "org/repo",
    actor: str = "ghuser",
    created_at: str = "2026-03-15T10:00:00Z",
    payload: dict | None = None,
) -> dict:
    if payload is None:
        if event_type == "ReleaseEvent":
            payload = {"release": {"tag_name": "v1.0.0", "body": "Initial release"}}
        elif event_type == "CreateEvent":
            payload = {"ref_type": "repository", "description": "A new repo"}
        else:
            payload = {}
    return {
        "id": event_id,
        "type": event_type,
        "repo": {"name": repo_name},
        "actor": {"login": actor},
        "created_at": created_at,
        "payload": payload,
    }


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestGitHubEventsConnector:
    @pytest.mark.asyncio
    async def test_fetch_release_event(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["ReleaseEvent"],
        ))

        event = _make_event(event_type="ReleaseEvent")

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([event]))

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "github_events"
        assert opp.source_url == "https://github.com/org/repo"
        assert "v1.0.0" in opp.title
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["event_type"] == "ReleaseEvent"
        assert opp.raw_metadata["release_tag"] == "v1.0.0"

    @pytest.mark.asyncio
    async def test_fetch_create_event_repository(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["CreateEvent"],
        ))

        event = _make_event(
            event_id="ev2",
            event_type="CreateEvent",
            payload={"ref_type": "repository", "description": "Cool project"},
        )

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([event]))

            result = await connector.fetch()

        assert len(result) == 1
        assert "New repository" in result[0].title

    @pytest.mark.asyncio
    async def test_create_event_branch_ignored(self) -> None:
        """CreateEvent for branches (not repos) is ignored."""
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["CreateEvent"],
        ))

        event = _make_event(
            event_type="CreateEvent",
            payload={"ref_type": "branch", "ref": "feature-x"},
        )

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([event]))

            result = await connector.fetch()

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_fetch_public_event(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["PublicEvent"],
        ))

        event = _make_event(event_id="ev3", event_type="PublicEvent", payload={})

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([event]))

            result = await connector.fetch()

        assert len(result) == 1
        assert "went public" in result[0].title

    @pytest.mark.asyncio
    async def test_event_type_filtering(self) -> None:
        """Events not in configured event_types are skipped."""
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["ReleaseEvent"],
        ))

        events = [
            _make_event(event_id="ev1", event_type="ReleaseEvent"),
            _make_event(event_id="ev2", event_type="WatchEvent", payload={}),
            _make_event(event_id="ev3", event_type="PushEvent", payload={}),
        ]

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(events))

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].raw_metadata["event_type"] == "ReleaseEvent"

    @pytest.mark.asyncio
    async def test_dedup_by_event_id(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["ReleaseEvent"],
        ))

        event = _make_event(event_id="dup1")
        events = [event, event]  # duplicate

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(events))

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig())

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(None, status_code=500))

            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_auth_header_with_token(self) -> None:
        connector = GitHubEventsConnector()
        connector.configure(GitHubEventsConnectorConfig())

        with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([]))

            await connector.fetch()

            call_kwargs = mock_client.get.call_args
            assert "Bearer ghp_test123" in call_kwargs.kwargs.get("headers", {}).get("Authorization", "")

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        db = _make_db()
        connector = GitHubEventsConnector(db_conn=db)
        connector.configure(GitHubEventsConnectorConfig(
            event_types=["ReleaseEvent"],
        ))

        event = _make_event(event_id="seen1")

        async def _run():
            with patch("foxhound.scout.connectors.github_events.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=_mock_response([event]))
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert GitHubEventsConnector().connector_name() == "github_events"
