"""Hacker News adapter via Algolia API.

Free, no auth required, no CAPTCHAs, structured JSON with engagement metrics.
https://hn.algolia.com/api
"""

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

ALGOLIA_API = "https://hn.algolia.com/api/v1"


async def fetch_hn_stories(
    topic: str,
    limit: int = 20,
    min_points: int = 5,
) -> list[dict]:
    """Search HN stories (posts) by topic, sorted by relevance."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{ALGOLIA_API}/search",
                params={
                    "query": topic,
                    "tags": "story",
                    "hitsPerPage": limit,
                    "numericFilters": f"points>={min_points}",
                },
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
    except Exception as e:
        logger.warning("HN story search failed for '%s': %s", topic, e)
        return []

    return [_parse_story(hit) for hit in hits if hit.get("title")]


async def fetch_hn_comments(
    topic: str,
    limit: int = 30,
    min_points: int = 3,
) -> list[dict]:
    """Search HN comments by topic — where the real pain signals live."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{ALGOLIA_API}/search",
                params={
                    "query": topic,
                    "tags": "comment",
                    "hitsPerPage": limit,
                    "numericFilters": f"points>={min_points}",
                },
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
    except Exception as e:
        logger.warning("HN comment search failed for '%s': %s", topic, e)
        return []

    return [_parse_comment(hit) for hit in hits if hit.get("comment_text")]


async def fetch_hn_signals(topic: str, limit: int = 30) -> list[dict]:
    """Fetch both stories and comments, merge and deduplicate."""
    import asyncio

    stories, comments = await asyncio.gather(
        fetch_hn_stories(topic, limit=limit // 2),
        fetch_hn_comments(topic, limit=limit // 2),
    )
    # Deduplicate by object ID
    seen = set()
    merged = []
    for item in stories + comments:
        if item["source_id"] not in seen:
            seen.add(item["source_id"])
            merged.append(item)
    return merged[:limit]


def _parse_story(hit: dict) -> dict:
    created = None
    if hit.get("created_at_i"):
        created = datetime.fromtimestamp(hit["created_at_i"], tz=UTC).isoformat()

    return {
        "source_id": f"hn_{hit.get('objectID', '')}",
        "url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
        "title": hit.get("title", ""),
        "text": hit.get("title", ""),
        "author": hit.get("author", ""),
        "created_utc": hit.get("created_at_i", 0),
        "created_at": created,
        "score": hit.get("points", 0),
        "num_comments": hit.get("num_comments", 0),
        "source": "hackernews",
        "source_type": "hn_story",
        "source_platform": "hackernews",
    }


def _parse_comment(hit: dict) -> dict:
    created = None
    if hit.get("created_at_i"):
        created = datetime.fromtimestamp(hit["created_at_i"], tz=UTC).isoformat()

    # Clean HTML from comment text
    text = hit.get("comment_text", "")
    text = _strip_html(text)

    return {
        "source_id": f"hn_{hit.get('objectID', '')}",
        "url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
        "title": f"Comment on: {hit.get('story_title', 'HN thread')}",
        "text": text[:1000],
        "author": hit.get("author", ""),
        "created_utc": hit.get("created_at_i", 0),
        "created_at": created,
        "score": hit.get("points", 0),
        "num_comments": 0,
        "source": "hackernews",
        "source_type": "hn_comment",
        "source_platform": "hackernews",
        "parent_story_id": hit.get("story_id"),
        "parent_story_title": hit.get("story_title", ""),
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags from HN comment text."""
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
