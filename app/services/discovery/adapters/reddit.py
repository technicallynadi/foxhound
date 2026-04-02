"""Reddit API adapter — free, no auth required.

Uses Reddit's public JSON API (append .json to any URL):
  https://www.reddit.com/search.json?q=...&sort=relevance
  https://www.reddit.com/r/{sub}/search.json?q=...

No OAuth needed for read-only. Rate limit: ~60 req/min with user agent.
Returns structured post data — title, body, comments, scores.

Use this instead of TinyFish for Reddit data (faster, free, reliable).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": settings.REDDIT_USER_AGENT or "foxhound/0.1",
}


async def search_reddit(
    query: str,
    subreddit: str | None = None,
    sort: str = "relevance",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search Reddit for posts matching a query.

    Args:
        query: Search terms (e.g. "Eucalyptus interview experience")
        subreddit: Specific subreddit to search (e.g. "cscareerquestions")
        sort: "relevance", "hot", "new", "top"
        limit: Max results (up to 25)

    Returns list of posts with title, body, url, score, comments.
    """
    if subreddit:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "sort": sort, "limit": min(limit, 25), "restrict_sr": "on"}
    else:
        url = "https://www.reddit.com/search.json"
        params = {"q": query, "sort": sort, "limit": min(limit, 25)}

    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Reddit search failed: %s", e)
            return []

    data = resp.json()
    posts = []

    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        posts.append({
            "title": post.get("title", ""),
            "body": (post.get("selftext") or "")[:2000],
            "url": f"https://www.reddit.com{post.get('permalink', '')}",
            "subreddit": post.get("subreddit", ""),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "created_utc": post.get("created_utc", 0),
        })

    return posts


async def get_post_comments(
    permalink: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch top comments for a Reddit post.

    Args:
        permalink: Reddit permalink (e.g. "/r/cscareerquestions/comments/abc123/...")
        limit: Max comments to return

    Returns list of comments with body and score.
    """
    # Clean permalink
    if permalink.startswith("https://www.reddit.com"):
        permalink = permalink.replace("https://www.reddit.com", "")
    url = f"https://www.reddit.com{permalink}.json"

    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
        try:
            resp = await client.get(url, params={"limit": limit})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Reddit comments fetch failed: %s", e)
            return []

    data = resp.json()
    comments = []

    # Reddit returns [post_listing, comments_listing]
    if len(data) >= 2:
        for child in data[1].get("data", {}).get("children", [])[:limit]:
            comment = child.get("data", {})
            body = comment.get("body", "")
            if body and body != "[deleted]" and body != "[removed]":
                comments.append({
                    "body": body[:1000],
                    "score": comment.get("score", 0),
                    "author": comment.get("author", ""),
                })

    return comments


async def search_company_interviews(company_name: str) -> dict[str, Any]:
    """Search Reddit for interview experiences at a company.

    Searches multiple relevant subreddits in parallel.
    Returns combined results with posts and top comments.
    """
    subreddits = [None, "cscareerquestions", "interviews", "experienceddevs"]
    queries = [
        f"{company_name} interview",
        f"{company_name} interview questions experience",
    ]

    all_posts: list[dict] = []

    # Run searches in parallel
    tasks = []
    for query in queries[:2]:
        for sub in subreddits[:3]:
            tasks.append(search_reddit(query, subreddit=sub, limit=5))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_posts.extend(result)

    # Deduplicate by URL and sort by score
    seen = set()
    unique = []
    for post in all_posts:
        if post["url"] not in seen and post["title"]:
            seen.add(post["url"])
            unique.append(post)

    unique.sort(key=lambda p: p["score"], reverse=True)
    top_posts = unique[:8]

    # Fetch comments for top 3 posts
    if top_posts:
        comment_tasks = [
            get_post_comments(p["url"], limit=5)
            for p in top_posts[:3]
        ]
        comment_results = await asyncio.gather(*comment_tasks, return_exceptions=True)
        for i, comments in enumerate(comment_results):
            if isinstance(comments, list) and i < len(top_posts):
                top_posts[i]["top_comments"] = comments

    return {
        "company": company_name,
        "posts_found": len(top_posts),
        "posts": top_posts,
    }


async def search_company_culture(company_name: str) -> dict[str, Any]:
    """Search Reddit for work culture and WLB at a company."""
    queries = [
        f"{company_name} work culture work life balance",
        f"{company_name} working at review",
    ]

    all_posts: list[dict] = []
    tasks = [search_reddit(q, limit=5) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, list):
            all_posts.extend(result)

    seen = set()
    unique = []
    for post in all_posts:
        if post["url"] not in seen and post["title"]:
            seen.add(post["url"])
            unique.append(post)

    unique.sort(key=lambda p: p["score"], reverse=True)
    top_posts = unique[:5]

    # Fetch comments for top 2
    if top_posts:
        comment_tasks = [get_post_comments(p["url"], limit=5) for p in top_posts[:2]]
        comment_results = await asyncio.gather(*comment_tasks, return_exceptions=True)
        for i, comments in enumerate(comment_results):
            if isinstance(comments, list) and i < len(top_posts):
                top_posts[i]["top_comments"] = comments

    return {
        "company": company_name,
        "posts_found": len(top_posts),
        "posts": top_posts,
    }
