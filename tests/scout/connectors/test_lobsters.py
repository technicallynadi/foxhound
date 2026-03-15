"""Tests for the Lobsters Scout connector."""

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.lobsters import LobstersConnector, LobstersConnectorConfig


def _make_story(
    short_id: str = "abc123",
    title: str = "Test Story",
    url: str = "https://blog.example.com/article",
    score: int = 30,
    comment_count: int = 10,
    tags: list[str] | None = None,
    username: str = "lobsteruser",
    created_at: str = "2026-03-15T08:30:00-05:00",
    comments_url: str = "https://lobste.rs/s/abc123",
) -> dict:
    return {
        "short_id": short_id,
        "title": title,
        "url": url,
        "score": score,
        "comment_count": comment_count,
        "tags": tags or ["python", "ai"],
        "submitter_user": {"username": username},
        "created_at": created_at,
        "comments_url": comments_url,
        "description": "",
    }


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestLobstersConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_stories(self) -> None:
        connector = LobstersConnector()
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest"],
            min_score=10,
            min_comments=3,
        ))

        story = _make_story(score=30, comment_count=10)

        with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([story]))

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "lobsters"
        assert opp.source_url == "https://lobste.rs/s/abc123"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["lobsters_id"] == "abc123"
        assert opp.raw_metadata["score"] == 30
        assert opp.raw_metadata["external_url"] == "https://blog.example.com/article"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "score,comments,should_pass",
        [
            (30, 10, True),
            (5, 10, False),    # below min_score
            (30, 1, False),    # below min_comments
            (10, 3, True),     # exactly at thresholds
        ],
    )
    async def test_threshold_filtering(
        self, score: int, comments: int, should_pass: bool
    ) -> None:
        connector = LobstersConnector()
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest"], min_score=10, min_comments=3,
        ))

        story = _make_story(score=score, comment_count=comments)

        with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([story]))

            result = await connector.fetch()

        assert len(result) == (1 if should_pass else 0)

    @pytest.mark.asyncio
    async def test_dedup_across_feeds(self) -> None:
        connector = LobstersConnector()
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest", "newest"], min_score=1, min_comments=0,
        ))

        story = _make_story(short_id="dup1", score=20, comment_count=5)

        with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([story]),  # hottest
                _mock_response([story]),  # newest (same story)
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        connector = LobstersConnector()
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest", "newest"], min_score=1, min_comments=0,
        ))

        story = _make_story(score=20, comment_count=5)

        with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response(None, status_code=500),  # hottest fails
                _mock_response([story]),                  # newest works
            ])

            result = await connector.fetch()

        assert len(result) == 1

    def test_invalid_feed_rejected_at_config(self) -> None:
        """Invalid feed names are rejected at config parse time."""
        with pytest.raises(Exception, match="Invalid feed"):
            LobstersConnectorConfig(
                feeds=["invalid_feed", "hottest"],
                min_score=1,
                min_comments=0,
            )

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        db = _make_db()
        connector = LobstersConnector(db_conn=db)
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest"], min_score=1, min_comments=0,
        ))

        story = _make_story(short_id="seen1", score=20, comment_count=5)

        async def _run():
            with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=_mock_response([story]))
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert LobstersConnector().connector_name() == "lobsters"

    @pytest.mark.asyncio
    async def test_source_url_is_discussion(self) -> None:
        connector = LobstersConnector()
        connector.configure(LobstersConnectorConfig(
            feeds=["hottest"], min_score=1, min_comments=0,
        ))

        story = _make_story(
            comments_url="https://lobste.rs/s/xyz789",
            url="https://external.blog/post",
        )

        with patch("foxhound.scout.connectors.lobsters.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response([story]))

            result = await connector.fetch()

        assert result[0].source_url == "https://lobste.rs/s/xyz789"
        assert result[0].raw_metadata["external_url"] == "https://external.blog/post"
