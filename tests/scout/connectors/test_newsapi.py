"""Tests for the NewsAPI Scout connector."""

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.newsapi import NewsAPIConnector, NewsAPIConnectorConfig


def _make_article(
    title: str = "Test Article",
    url: str = "https://techcrunch.com/test-article",
    description: str = "A brief description",
    source_name: str = "TechCrunch",
    author: str = "Author Name",
    published_at: str = "2026-03-15T09:00:00Z",
) -> dict:
    return {
        "title": title,
        "url": url,
        "description": description,
        "source": {"id": "techcrunch", "name": source_name},
        "author": author,
        "publishedAt": published_at,
    }


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestNewsAPIConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_articles(self) -> None:
        connector = NewsAPIConnector()
        connector.configure(NewsAPIConnectorConfig(queries=["developer tools"]))

        article = _make_article()

        with patch("foxhound.scout.connectors.newsapi.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"NEWSAPI_API_KEY": "test-key"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(
                return_value=_mock_response({"articles": [article]})
            )

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "newsapi"
        assert opp.source_url == "https://techcrunch.com/test-article"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["source_name"] == "TechCrunch"
        assert opp.raw_metadata["query_matched"] == "developer tools"

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_empty(self) -> None:
        connector = NewsAPIConnector()
        connector.configure(NewsAPIConnectorConfig(queries=["test"]))

        with patch.dict("os.environ", {}, clear=True):
            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_across_queries(self) -> None:
        connector = NewsAPIConnector()
        connector.configure(NewsAPIConnectorConfig(
            queries=["developer tools", "open source"],
        ))

        article = _make_article(url="https://example.com/same-article")

        with patch("foxhound.scout.connectors.newsapi.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"NEWSAPI_API_KEY": "test-key"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response({"articles": [article]}),
                _mock_response({"articles": [article]}),
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        connector = NewsAPIConnector()
        connector.configure(NewsAPIConnectorConfig(
            queries=["query1", "query2"],
        ))

        article = _make_article()

        with patch("foxhound.scout.connectors.newsapi.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"NEWSAPI_API_KEY": "test-key"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response(None, status_code=500),
                _mock_response({"articles": [article]}),
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self) -> None:
        connector = NewsAPIConnector()
        connector.configure(NewsAPIConnectorConfig(queries=["test"]))

        article = {
            "title": "Minimal",
            "url": "https://example.com/minimal",
            "source": {"id": None, "name": "Unknown"},
        }

        with patch("foxhound.scout.connectors.newsapi.httpx.AsyncClient") as mock_cls, \
             patch.dict("os.environ", {"NEWSAPI_API_KEY": "test-key"}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(
                return_value=_mock_response({"articles": [article]})
            )

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].raw_metadata["author"] == ""

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        db = _make_db()
        connector = NewsAPIConnector(db_conn=db)
        connector.configure(NewsAPIConnectorConfig(queries=["test"]))

        article = _make_article()

        async def _run():
            with patch("foxhound.scout.connectors.newsapi.httpx.AsyncClient") as mock_cls, \
                 patch.dict("os.environ", {"NEWSAPI_API_KEY": "test-key"}):
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(
                    return_value=_mock_response({"articles": [article]})
                )
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert NewsAPIConnector().connector_name() == "newsapi"
