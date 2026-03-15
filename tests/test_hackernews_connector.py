"""Tests for the Hacker News Scout connector."""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from foxhound.scout.connectors.hackernews import (
    HN_API_BASE,
    HNConnectorConfig,
    HackerNewsConnector,
    sanitize_title,
)


# -- Fixtures --


def _make_hn_item(
    item_id: int = 100,
    title: str = "Test Story",
    score: int = 75,
    descendants: int = 20,
    item_type: str = "story",
    url: str = "https://example.com",
    by: str = "testuser",
    time: int = 1700000000,
    dead: bool = False,
    deleted: bool = False,
) -> dict:
    item = {
        "id": item_id,
        "type": item_type,
        "title": title,
        "score": score,
        "descendants": descendants,
        "url": url,
        "by": by,
        "time": time,
    }
    if dead:
        item["dead"] = True
    if deleted:
        item["deleted"] = True
    return item


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _mock_response(data, status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response."""
    import json

    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "https://fake"),
    )


# -- Title sanitization --


class TestSanitizeTitle:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Hello &amp; World", "Hello & World"),
            ("It&#x27;s a test", "It's a test"),
            ("&lt;script&gt;alert&lt;/script&gt;", "alert"),
            ("No entities here", "No entities here"),
            ("<b>Bold</b> text", "Bold text"),
            ("&amp;amp; double", "&amp; double"),
            ("  spaces  ", "spaces"),
        ],
    )
    def test_sanitize(self, raw: str, expected: str) -> None:
        assert sanitize_title(raw) == expected


# -- Connector fetch logic --


class TestHackerNewsConnector:
    @pytest.mark.asyncio
    async def test_fetch_parses_items(self) -> None:
        """Items passing thresholds are returned as RawOpportunity objects."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=2,
            min_score=50,
            min_comments=10,
        ))

        items = [_make_hn_item(item_id=1, score=100, descendants=30)]

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([1]),        # topstories IDs
                _mock_response(items[0]),   # item 1
            ])

            result = await connector.fetch()

        assert len(result) == 1
        opp = result[0]
        assert opp.source_type == "hackernews"
        assert opp.source_url == "https://news.ycombinator.com/item?id=1"
        assert opp.title == "Test Story"
        assert opp.trust_level == "external_untrusted"
        assert opp.raw_metadata["hn_id"] == 1
        assert opp.raw_metadata["score"] == 100
        assert opp.raw_metadata["comment_count"] == 30
        assert opp.raw_metadata["external_url"] == "https://example.com"
        assert opp.raw_metadata["source_feed"] == "topstories"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "score,comments,should_pass",
        [
            (100, 20, True),
            (49, 20, False),   # below min_score
            (100, 5, False),   # below min_comments
            (49, 5, False),    # below both
            (50, 10, True),    # exactly at thresholds
        ],
    )
    async def test_score_comment_filtering(
        self, score: int, comments: int, should_pass: bool
    ) -> None:
        """Items below score or comment thresholds are excluded."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=5,
            min_score=50,
            min_comments=10,
        ))

        item = _make_hn_item(item_id=42, score=score, descendants=comments)

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([42]),
                _mock_response(item),
            ])

            result = await connector.fetch()

        assert len(result) == (1 if should_pass else 0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["dead", "deleted"])
    async def test_dead_deleted_filtering(self, field: str) -> None:
        """Dead and deleted items are skipped."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"], max_items_per_source=5
        ))

        item = _make_hn_item(item_id=99, score=200, descendants=50)
        item[field] = True

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([99]),
                _mock_response(item),
            ])

            result = await connector.fetch()

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_dedup_across_sources(self) -> None:
        """An item appearing in multiple sources is only returned once."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories", "showstories"],
            max_items_per_source=5,
            min_score=1,
            min_comments=0,
        ))

        item = _make_hn_item(item_id=77, score=200, descendants=50)

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([77]),       # topstories
                _mock_response([77]),       # showstories (same ID)
                _mock_response(item),       # item fetched once
            ])

            result = await connector.fetch()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_source_error_resilience(self) -> None:
        """If one source fails, others still return results."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories", "showstories"],
            max_items_per_source=5,
            min_score=1,
            min_comments=0,
        ))

        good_item = _make_hn_item(item_id=10, score=100, descendants=20)

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response(None, status_code=500),  # topstories fails
                _mock_response([10]),                     # showstories works
                _mock_response(good_item),
            ])

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].raw_metadata["hn_id"] == 10

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        """Empty source returns empty list, no crash."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(sources=["topstories"]))

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(return_value=_mock_response([]))

            result = await connector.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_source_url_is_hn_discussion(self) -> None:
        """source_url is always the HN discussion link, not the external URL."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=2,
            min_score=1,
            min_comments=0,
        ))

        item = _make_hn_item(
            item_id=555, score=100, descendants=20,
            url="https://blog.example.com/article",
        )

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([555]),
                _mock_response(item),
            ])

            result = await connector.fetch()

        assert len(result) == 1
        assert result[0].source_url == "https://news.ycombinator.com/item?id=555"
        assert result[0].raw_metadata["external_url"] == "https://blog.example.com/article"

    @pytest.mark.asyncio
    async def test_html_entity_in_title(self) -> None:
        """HTML entities in titles are decoded."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=2,
            min_score=1,
            min_comments=0,
        ))

        item = _make_hn_item(
            item_id=200, score=100, descendants=20,
            title="Show HN: It&#x27;s &amp; <b>bold</b>",
        )

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([200]),
                _mock_response(item),
            ])

            result = await connector.fetch()

        assert result[0].title == "Show HN: It's & bold"


class TestSeenItemsDedup:
    @pytest.mark.asyncio
    async def test_seen_items_not_refetched(self) -> None:
        """Previously seen items are skipped on subsequent fetches."""
        db = _make_db()
        connector = HackerNewsConnector(db_conn=db)
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=5,
            min_score=1,
            min_comments=0,
        ))

        item = _make_hn_item(item_id=42, score=100, descendants=20)

        async def _run_fetch():
            with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                mock_client.get = AsyncMock(side_effect=[
                    _mock_response([42]),
                    _mock_response(item),
                ])

                return await connector.fetch()

        # First fetch returns the item
        result1 = await _run_fetch()
        assert len(result1) == 1

        # Second fetch: item is in seen table, should be filtered out before fetching
        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([42]),  # same ID returned by source
            ])

            result2 = await connector.fetch()

        assert len(result2) == 0

    def test_prune_seen(self) -> None:
        """Pruning removes old entries."""
        db = _make_db()
        connector = HackerNewsConnector(db_conn=db)
        connector.configure(HNConnectorConfig(seen_retention_days=0))

        # Insert an old entry
        db.execute(
            "INSERT INTO scout_seen_items (source_type, source_id, first_seen_at) "
            "VALUES (?, ?, ?)",
            ("hackernews", "old_item", "2020-01-01T00:00:00+00:00"),
        )
        db.commit()

        pruned = connector.prune_seen()
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_non_story_types_skipped(self) -> None:
        """Items with type != 'story' are filtered out."""
        connector = HackerNewsConnector()
        connector.configure(HNConnectorConfig(
            sources=["topstories"],
            max_items_per_source=5,
            min_score=1,
            min_comments=0,
        ))

        job_item = _make_hn_item(item_id=300, score=100, descendants=20, item_type="job")

        with patch("foxhound.scout.connectors.hackernews.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_client.get = AsyncMock(side_effect=[
                _mock_response([300]),
                _mock_response(job_item),
            ])

            result = await connector.fetch()

        assert len(result) == 0
