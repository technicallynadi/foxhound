"""HN Who's Hiring adapter.

Uses the HN Algolia API to find the latest "Who is hiring?" thread
and extract job postings from top-level comments.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)

ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ALGOLIA_ITEM_URL = "https://hn.algolia.com/api/v1/items"


class HNHiringAdapter:
    source_name = "hn_hiring"

    async def fetch_listings(self) -> list[dict]:
        """Find the latest Who's Hiring thread and extract job posts."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Find the latest "Who is hiring?" thread by whoishiring
            resp = await client.get(
                ALGOLIA_SEARCH_URL,
                params={
                    "query": "Ask HN: Who is hiring?",
                    "tags": "story,author_whoishiring",
                    "hitsPerPage": 1,
                },
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])

            if not hits:
                logger.warning("HN: No Who's Hiring thread found")
                return []

            thread_id = hits[0]["objectID"]
            logger.info("HN: Found Who's Hiring thread %s", thread_id)

            # Fetch the thread's comments
            item_resp = await client.get(f"{ALGOLIA_ITEM_URL}/{thread_id}")
            item_resp.raise_for_status()
            children = item_resp.json().get("children", [])

        listings = []
        for comment in children[:200]:  # Cap at 200 comments
            text = comment.get("text", "")
            if not text or len(text) < 50:
                continue

            parsed = _parse_hn_comment(text)
            if not parsed:
                continue

            company = parsed["company"]
            title = parsed["title"]

            listings.append(
                {
                    "external_id": str(comment.get("id", "")),
                    "title": title,
                    "company": company,
                    "company_url": None,
                    "description": text,
                    "description_html": text,
                    "location": parsed.get("location", ""),
                    "remote_type": parsed.get("remote_type"),
                    "apply_url": parsed.get("apply_url", ""),
                    "ats_type": None,
                    "auto_apply_supported": False,
                    "source": "hn_hiring",
                    "source_url": f"https://news.ycombinator.com/item?id={comment.get('id', '')}",
                    "posted_at": comment.get("created_at"),
                    "dedup_hash": compute_dedup_hash(company, title, parsed.get("location")),
                }
            )

        logger.info("HN: extracted %d job listings from %d comments", len(listings), len(children))
        return listings


def _parse_hn_comment(text: str) -> dict | None:
    """Parse a Who's Hiring comment into structured job data.

    HN hiring comments typically follow: Company | Title | Location | Remote | URL
    """
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", text).strip()
    lines = clean.split("\n")
    if not lines:
        return None

    # First line usually has: Company | Role | Location | ...
    header = lines[0]
    parts = [p.strip() for p in re.split(r"\s*\|\s*", header)]

    if len(parts) < 2:
        return None

    company = parts[0]
    title = parts[1] if len(parts) > 1 else ""
    location = parts[2] if len(parts) > 2 else ""

    # Detect remote
    remote_type = None
    full_text_lower = clean.lower()
    if "remote" in full_text_lower:
        remote_type = "remote"
    elif "hybrid" in full_text_lower:
        remote_type = "hybrid"

    # Find URL in comment
    urls = re.findall(r"https?://[^\s<>\"']+", clean)
    apply_url = urls[0] if urls else ""

    return {
        "company": company,
        "title": title,
        "location": location,
        "remote_type": remote_type,
        "apply_url": apply_url,
    }
