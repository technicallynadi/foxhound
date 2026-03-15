"""Tests for the RSS/Atom Feed Scout connector."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from foxhound.scout.connectors.rss import (
    FeedConfig,
    RSSConnector,
    RSSConnectorConfig,
    sanitize_html,
)


def _make_entry(
    title: str = "Test Article",
    link: str = "https://blog.example.com/test",
    summary: str = "A brief summary",
    author: str = "blogauthor",
    published: str = "2026-03-15T10:00:00Z",
    tags: list[str] | None = None,
) -> SimpleNamespace:
    tag_list = [SimpleNamespace(term=t) for t in (tags or [])]
    return SimpleNamespace(
        title=title,
        link=link,
        summary=summary,
        author=author,
        published=published,
        tags=tag_list,
    )


def _mock_response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=content.encode(),
        request=httpx.Request("GET", "https://fake"),
    )


def _make_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


FEED_CONFIG = FeedConfig(url="https://example.com/feed.xml", name="Test Feed")


class TestSanitizeHtml:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Hello &amp; World", "Hello & World"),
            ("<b>Bold</b> text", "Bold text"),
            ("No entities", "No entities"),
            ("  spaces  ", "spaces"),
            ("&lt;code&gt;block&lt;/code&gt;", "block"),
        ],
    )
    def test_sanitize(self, raw: str, expected: str) -> None:
        assert sanitize_html(raw) == expected


class TestRSSConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_entries(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        entry = _make_entry(tags=["python", "devtools"])
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss>xml</rss>"))

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "rss"
        assert opp.source_url == "https://blog.example.com/test"
        assert opp.title == "Test Article"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["feed_name"] == "Test Feed"
        assert opp.raw_metadata["author"] == "blogauthor"
        assert opp.raw_metadata["tags"] == ["python", "devtools"]

    @pytest.mark.asyncio
    async def test_dedup_across_feeds(self) -> None:
        feed1 = FeedConfig(url="https://example.com/feed1.xml", name="Feed 1")
        feed2 = FeedConfig(url="https://example.com/feed2.xml", name="Feed 2")

        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[feed1, feed2]))

        entry = _make_entry(link="https://same-article.com/post")
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss>xml</rss>"))

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_resilience(self) -> None:
        feed1 = FeedConfig(url="https://broken.com/feed.xml", name="Broken")
        feed2 = FeedConfig(url="https://good.com/feed.xml", name="Good")

        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[feed1, feed2]))

        entry = _make_entry()
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[
                _mock_response("error", status_code=500),
                _mock_response("<rss>xml</rss>"),
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_missing_feedparser_returns_empty(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        with patch.dict("sys.modules", {"feedparser": None}):
            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_html_in_title_sanitized(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        entry = _make_entry(title="<b>Bold</b> &amp; <i>italic</i>")
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss/>"))

            result = await connector.fetch()

        assert result[0].title == "Bold & italic"

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        entry = SimpleNamespace(
            title="Minimal",
            link="https://example.com/minimal",
        )
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss/>"))

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].raw_metadata["author"] == ""
        assert result[0].raw_metadata["tags"] == []

    @pytest.mark.asyncio
    async def test_description_truncated_to_500(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        long_summary = "x" * 1000
        entry = _make_entry(summary=long_summary)
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss/>"))

            result = await connector.fetch()

        assert len(result[0].description) <= 500

    @pytest.mark.asyncio
    async def test_seen_items_dedup(self) -> None:
        db = _make_db()
        connector = RSSConnector(db_conn=db)
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        entry = _make_entry(link="https://example.com/seen-article")
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        async def _run():
            with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
                 patch.dict("sys.modules", {"feedparser": mock_feedparser}):
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=_mock_response("<rss/>"))
                return await connector.fetch()

        result1 = await _run()
        assert len(result1) == 1

        result2 = await _run()
        assert len(result2) == 0

    def test_connector_name(self) -> None:
        assert RSSConnector().connector_name() == "rss"

    @pytest.mark.asyncio
    async def test_entry_without_link_skipped(self) -> None:
        connector = RSSConnector()
        connector.configure(RSSConnectorConfig(feeds=[FEED_CONFIG]))

        entry = SimpleNamespace(title="No Link")
        mock_feedparser = MagicMock()
        mock_feedparser.parse.return_value = {"entries": [entry]}

        with patch("foxhound.scout.connectors.rss.httpx.AsyncClient") as mock_cls, \
             patch.dict("sys.modules", {"feedparser": mock_feedparser}):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response("<rss/>"))

            result = await connector.fetch()

        assert len(result) == 0
