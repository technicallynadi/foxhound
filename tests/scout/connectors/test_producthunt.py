"""Tests for the Product Hunt Scout connector."""

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.producthunt import (
    ProductHuntConnector,
    ProductHuntConnectorConfig,
)


def _make_post_node(
    ph_id: str = "ph1",
    name: str = "Cool Product",
    tagline: str = "The best product ever",
    url: str = "https://www.producthunt.com/posts/cool-product",
    votes: int = 100,
    comments: int = 20,
    website: str = "https://coolproduct.com",
    topics: list[str] | None = None,
    created_at: str = "2026-03-15T00:00:00Z",
) -> dict:
    topic_edges = [
        {"node": {"name": t}} for t in (topics or ["Developer Tools", "AI"])
    ]
    return {
        "id": ph_id,
        "name": name,
        "tagline": tagline,
        "description": "Full description",
        "url": url,
        "votesCount": votes,
        "commentsCount": comments,
        "website": website,
        "createdAt": created_at,
        "topics": {"edges": topic_edges},
    }


def _make_graphql_response(nodes: list[dict]) -> dict:
    edges = [{"node": node} for node in nodes]
    return {"data": {"posts": {"edges": edges}}}


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("POST", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestProductHuntConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_posts(self) -> None:
        connector = ProductHuntConnector()
        connector.configure(ProductHuntConnectorConfig(min_votes=50))

        node = _make_post_node(votes=150)

        with patch("foxhound.scout.connectors.producthunt.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "test-token"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                return_value=_mock_response(_make_graphql_response([node]))
            )

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "producthunt"
        assert opp.source_url == "https://www.producthunt.com/posts/cool-product"
        assert opp.title == "Cool Product"
        assert opp.description == "The best product ever"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["ph_id"] == "ph1"
        assert opp.raw_metadata["votes"] == 150
        assert opp.raw_metadata["website"] == "https://coolproduct.com"
        assert opp.raw_metadata["topics"] == ["Developer Tools", "AI"]

    @pytest.mark.asyncio
    async def test_missing_api_token_returns_empty(self) -> None:
        connector = ProductHuntConnector()
        connector.configure(ProductHuntConnectorConfig())

        with patch.dict("os.environ", {}, clear=True):
            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "votes,should_pass",
        [
            (100, True),
            (49, False),   # below min_votes
            (50, True),    # exactly at threshold
        ],
    )
    async def test_vote_threshold_filtering(self, votes: int, should_pass: bool) -> None:
        connector = ProductHuntConnector()
        connector.configure(ProductHuntConnectorConfig(min_votes=50))

        node = _make_post_node(votes=votes)

        with patch("foxhound.scout.connectors.producthunt.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "test-token"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                return_value=_mock_response(_make_graphql_response([node]))
            )

            result = await connector.fetch()

        assert len(result) == (1 if should_pass else 0)

    @pytest.mark.asyncio
    async def test_dedup_by_id(self) -> None:
        connector = ProductHuntConnector()
        connector.configure(ProductHuntConnectorConfig(min_votes=1))

        node = _make_post_node(ph_id="dup1", votes=100)

        with patch("foxhound.scout.connectors.producthunt.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "test-token"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                return_value=_mock_response(_make_graphql_response([node, node]))
            )

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        connector = ProductHuntConnector()
        connector.configure(ProductHuntConnectorConfig())

        with patch("foxhound.scout.connectors.producthunt.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "test-token"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                return_value=_mock_response(None, status_code=500)
            )

            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        db = _make_db()
        connector = ProductHuntConnector(db_conn=db)
        connector.configure(ProductHuntConnectorConfig(min_votes=1))

        node = _make_post_node(ph_id="seen1", votes=100)

        async def _run():
            with patch("foxhound.scout.connectors.producthunt.httpx.AsyncClient") as mock_cls, \
                 patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "test-token"}):
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(
                    return_value=_mock_response(_make_graphql_response([node]))
                )
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert ProductHuntConnector().connector_name() == "producthunt"
