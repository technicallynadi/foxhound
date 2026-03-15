"""Tests for the Dev.to Scout connector."""

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.devto import DevToConnector, DevToConnectorConfig


def _make_article(
    article_id: int = 100,
    title: str = "Test Article",
    url: str = "https://dev.to/user/test-article-abc",
    reactions: int = 50,
    comments: int = 10,
    tags: list[str] | None = None,
    username: str = "testuser",
    published_at: str = "2026-03-15T10:00:00Z",
    reading_time: int = 5,
    description: str = "A test article",
) -> dict:
    return {
        "id": article_id,
        "title": title,
        "url": url,
        "description": description,
        "positive_reactions_count": reactions,
        "comments_count": comments,
        "tag_list": tags or ["python", "ai"],
        "user": {"username": username},
        "published_at": published_at,
        "reading_time_minutes": reading_time,
    }


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestDevToConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_articles(self) -> None:
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python"],
            min_reactions=10,
            min_comments=5,
        ))

        article = _make_article(reactions=50, comments=20)

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([article]),  # python tag
                _mock_response([]),         # rising
            ])

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "devto"
        assert opp.source_url == "https://dev.to/user/test-article-abc"
        assert opp.title == "Test Article"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["devto_id"] == 100
        assert opp.raw_metadata["reactions"] == 50
        assert opp.raw_metadata["comments"] == 20
        assert opp.raw_metadata["author"] == "testuser"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reactions,comments,should_pass",
        [
            (50, 20, True),
            (5, 20, False),    # below min_reactions
            (50, 2, False),    # below min_comments
            (20, 5, True),     # exactly at thresholds
        ],
    )
    async def test_threshold_filtering(
        self, reactions: int, comments: int, should_pass: bool
    ) -> None:
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python"],
            min_reactions=20,
            min_comments=5,
        ))

        article = _make_article(reactions=reactions, comments=comments)

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([article]),
                _mock_response([]),
            ])

            result = await connector.fetch()

        assert len(result) == (1 if should_pass else 0)

    @pytest.mark.asyncio
    async def test_dedup_across_tags(self) -> None:
        """Same article in multiple tags returns only once."""
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python", "ai"],
            min_reactions=1,
            min_comments=0,
        ))

        article = _make_article(article_id=42, reactions=50, comments=10)

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([article]),  # python tag
                _mock_response([article]),  # ai tag (same article)
                _mock_response([]),         # rising
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        """HTTP error on one tag doesn't crash the connector."""
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python", "ai"],
            min_reactions=1,
            min_comments=0,
        ))

        article = _make_article(reactions=50, comments=10)

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response(None, status_code=500),  # python fails
                _mock_response([article]),               # ai works
                _mock_response([]),                      # rising
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self) -> None:
        """Articles with missing optional fields are handled gracefully."""
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python"],
            min_reactions=1,
            min_comments=0,
        ))

        article = {
            "id": 999,
            "title": "Minimal Article",
            "url": "https://dev.to/user/minimal",
            "positive_reactions_count": 30,
            "comments_count": 5,
            # missing: description, tag_list, user, published_at, reading_time_minutes
        }

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([article]),
                _mock_response([]),
            ])

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].raw_metadata["author"] == ""
        assert result[0].raw_metadata["tags"] == []

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        """Previously seen items are skipped on subsequent fetches."""
        db = _make_db()
        connector = DevToConnector(db_conn=db)
        connector.configure(DevToConnectorConfig(
            tags=["python"],
            min_reactions=1,
            min_comments=0,
        ))

        article = _make_article(article_id=42, reactions=50, comments=10)

        async def _run():
            with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(side_effect=[
                    _mock_response([article]),
                    _mock_response([]),
                ])
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert DevToConnector().connector_name() == "devto"

    @pytest.mark.asyncio
    async def test_source_url_points_to_devto(self) -> None:
        connector = DevToConnector()
        connector.configure(DevToConnectorConfig(
            tags=["python"], min_reactions=1, min_comments=0,
        ))

        article = _make_article(url="https://dev.to/user/my-post-abc123")

        with patch("foxhound.scout.connectors.devto.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response([article]),
                _mock_response([]),
            ])

            result = await connector.fetch()

        assert result[0].source_url == "https://dev.to/user/my-post-abc123"
