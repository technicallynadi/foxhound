import logging

import httpx

from app.services.ingest.community_router import route_query

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "foxhound/0.1 (opportunity-discovery)"}
BASE_URL = "https://www.reddit.com"
MIN_SIGNAL_THRESHOLD = 10


DEFAULT_DEV_SUBREDDITS = [
    "programming",
    "webdev",
    "devops",
    "sysadmin",
    "ExperiencedDevs",
    "selfhosted",
    "SaaS",
    "startups",
    "dataengineering",
    "MachineLearning",
]


async def fetch_reddit_posts(topic: str, limit: int = 25) -> list[dict]:
    """Fetch Reddit posts using community-routed strategy + default dev subreddits.

    Always searches core dev subreddits directly, plus any routed communities.
    """
    plan = route_query(topic)
    results: dict[str, dict] = {}

    # Combine routed communities with default dev subreddits
    routed_subs = plan.get("primary", []) + plan.get("secondary", []) + plan.get("fallback", [])
    all_subs = list(dict.fromkeys(routed_subs + DEFAULT_DEV_SUBREDDITS))  # dedup, keep order

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        # Search each subreddit (stop early if we have enough)
        for sub in all_subs:
            if len(results) >= limit:
                break
            tier = "primary" if sub in routed_subs else "default"
            await _fetch_subreddit(client, sub, topic, results, limit, tier=tier)

    logger.info(
        "Reddit ingested %d posts across %d communities for '%s' (strategy=%s)",
        len(results),
        _count_communities(results),
        topic,
        plan.get("strategy", "unknown"),
    )

    # Enrich top posts with comment content (where the real pain signals live)
    posts = list(results.values())
    top_posts = sorted(posts, key=lambda p: p.get("score", 0) + p.get("num_comments", 0), reverse=True)

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        for post in top_posts[:5]:  # enrich top 5 by engagement
            comments = await _fetch_top_comments(client, post)
            if comments:
                # Append comment text to the post's text for richer signal
                comment_text = "\n\n---\nTop comments:\n" + "\n\n".join(
                    f"[{c['score']} pts] {c['text']}" for c in comments[:5]
                )
                post["text"] = post["text"] + comment_text
                post["_comment_count_fetched"] = len(comments)

    return posts


async def _fetch_subreddit(
    client: httpx.AsyncClient,
    subreddit: str,
    topic: str,
    results: dict[str, dict],
    limit: int,
    tier: str,
) -> None:
    """Fetch posts from a specific subreddit — search first, then top/hot."""
    # Strategy 1: Search within subreddit for the topic (most relevant)
    await _fetch_search(
        client,
        subreddit,
        topic,
        limit,
        results,
        tier,
    )

    # Strategy 2: Top posts only if search found nothing
    if len(results) < 3:
        await _fetch_listing(
            client,
            subreddit,
            "top",
            {"t": "year", "limit": limit},
            results,
            tier,
        )


async def _fetch_listing(
    client: httpx.AsyncClient,
    subreddit: str,
    sort: str,
    params: dict,
    results: dict[str, dict],
    tier: str,
) -> None:
    try:
        resp = await client.get(
            f"{BASE_URL}/r/{subreddit}/{sort}.json",
            params=params,
        )
        resp.raise_for_status()
        for post in resp.json().get("data", {}).get("children", []):
            parsed = _parse_post(post.get("data", {}), tier)
            if parsed and parsed["source_id"] not in results:
                results[parsed["source_id"]] = parsed
    except Exception as e:
        logger.debug("Reddit r/%s/%s failed: %s", subreddit, sort, e)


async def _fetch_search(
    client: httpx.AsyncClient,
    subreddit: str,
    query: str,
    limit: int,
    results: dict[str, dict],
    tier: str,
) -> None:
    try:
        resp = await client.get(
            f"{BASE_URL}/r/{subreddit}/search.json",
            params={
                "q": query,
                "restrict_sr": "on",
                "sort": "relevance",
                "limit": limit,
            },
        )
        resp.raise_for_status()
        for post in resp.json().get("data", {}).get("children", []):
            parsed = _parse_post(post.get("data", {}), tier)
            if parsed and parsed["source_id"] not in results:
                results[parsed["source_id"]] = parsed
    except Exception as e:
        logger.debug("Reddit r/%s/search failed for '%s': %s", subreddit, query, e)


def _parse_post(data: dict, tier: str = "primary") -> dict | None:
    if not data or not data.get("id"):
        return None

    title = data.get("title", "")
    selftext = data.get("selftext", "")

    if title and selftext:
        text = f"{title}\n\n{selftext}"
    else:
        text = title or selftext

    # Skip very short posts (low signal)
    if len(text.strip()) < 30:
        return None

    return {
        "source_id": data["id"],
        "url": f"https://www.reddit.com{data.get('permalink', '')}",
        "title": title,
        "text": text,
        "community": data.get("subreddit", ""),
        "author": data.get("author", ""),
        "created_utc": data.get("created_utc", 0),
        "score": data.get("score", 0),
        "num_comments": data.get("num_comments", 0),
        "community_tier": tier,
        "is_main_community": tier == "primary",
    }


async def _fetch_top_comments(
    client: httpx.AsyncClient,
    post: dict,
    limit: int = 5,
) -> list[dict]:
    """Fetch the top comments for a Reddit post — this is where pain signals live."""
    permalink = post.get("url", "")
    if not permalink or "reddit.com" not in permalink:
        return []

    try:
        # Reddit JSON API: append .json to any post URL
        json_url = permalink.rstrip("/") + ".json"
        resp = await client.get(json_url, params={"limit": limit, "sort": "top"})
        resp.raise_for_status()
        data = resp.json()

        # Reddit returns [post_listing, comment_listing]
        if not isinstance(data, list) or len(data) < 2:
            return []

        comments = []
        for child in data[1].get("data", {}).get("children", []):
            cdata = child.get("data", {})
            body = cdata.get("body", "")
            if not body or len(body.strip()) < 30:
                continue
            comments.append(
                {
                    "text": body[:500],
                    "author": cdata.get("author", ""),
                    "score": cdata.get("score", 0),
                }
            )

        # Sort by score, return top N
        comments.sort(key=lambda c: c["score"], reverse=True)
        return comments[:limit]

    except Exception as e:
        logger.debug("Comment fetch failed for %s: %s", permalink[:60], e)
        return []


def _count_communities(results: dict[str, dict]) -> int:
    return len({r.get("community", "") for r in results.values()})
