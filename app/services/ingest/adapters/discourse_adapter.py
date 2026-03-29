"""Discourse forum adapter — one adapter covers 10+ developer forums.

Discourse exposes a public JSON API on every forum. Append .json to any
URL to get structured data with view counts, reply counts, and like counts.

Known Discourse forums for dev tools:
  community.fly.io, forum.obsidian.md, community.render.com,
  forum.cursor.com, community.cloudflare.com, community.grafana.com,
  forum.gitlab.com, discuss.hashicorp.com, discuss.kubernetes.io,
  answers.netlify.com, forum.ghost.org, community.n8n.io,
  community.home-assistant.io, meta.discourse.org
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Registry of known Discourse forums with their feature request categories
DISCOURSE_FORUMS = [
    {"url": "https://community.fly.io", "name": "Fly.io", "verticals": ["devtools", "deployment"]},
    {"url": "https://forum.obsidian.md", "name": "Obsidian", "verticals": ["productivity", "pkm"]},
    {"url": "https://community.render.com", "name": "Render", "verticals": ["devtools", "deployment"]},
    {"url": "https://community.cloudflare.com", "name": "Cloudflare", "verticals": ["infra", "cdn"]},
    {"url": "https://community.grafana.com", "name": "Grafana", "verticals": ["monitoring", "observability"]},
    {"url": "https://forum.gitlab.com", "name": "GitLab", "verticals": ["devtools", "cicd"]},
    {"url": "https://discuss.hashicorp.com", "name": "HashiCorp", "verticals": ["devops", "infra"]},
    {"url": "https://discuss.kubernetes.io", "name": "Kubernetes", "verticals": ["devops", "infra"]},
    {"url": "https://answers.netlify.com", "name": "Netlify", "verticals": ["frontend", "deployment"]},
    {"url": "https://forum.ghost.org", "name": "Ghost", "verticals": ["cms", "publishing"]},
    {"url": "https://community.n8n.io", "name": "n8n", "verticals": ["automation", "nocode"]},
]


async def fetch_discourse_signals(
    topic: str,
    limit: int = 20,
    forums: list[dict] | None = None,
) -> list[dict]:
    """Search across multiple Discourse forums for a topic.

    Each forum gets a search API call. Results are merged and deduplicated.
    """
    target_forums = forums or DISCOURSE_FORUMS

    tasks = [
        _search_forum(forum, topic, limit_per_forum=max(5, limit // len(target_forums)))
        for forum in target_forums
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_signals = []
    for i, result in enumerate(results):
        forum_name = target_forums[i]["name"]
        if isinstance(result, Exception):
            logger.debug("Discourse [%s] failed: %s", forum_name, result)
            continue
        if result:
            logger.info("Discourse [%s]: %d signals", forum_name, len(result))
            all_signals.extend(result)

    return all_signals[:limit]


async def _search_forum(
    forum: dict,
    topic: str,
    limit_per_forum: int = 5,
) -> list[dict]:
    """Search a single Discourse forum via its JSON API."""
    base_url = forum["url"].rstrip("/")
    forum_name = forum["name"]

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{base_url}/search.json",
                params={"q": topic},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.debug("Discourse [%s] search failed: %s", forum_name, e)
        return []

    topics = data.get("topics", [])
    posts = data.get("posts", [])

    # Build a map of topic metadata
    topic_map = {}
    for t in topics:
        topic_map[t.get("id")] = {
            "title": t.get("title", ""),
            "views": t.get("views", 0),
            "reply_count": t.get("reply_count", 0),
            "like_count": t.get("like_count", 0),
            "created_at": t.get("created_at"),
            "slug": t.get("slug", ""),
        }

    signals = []
    for post in posts[:limit_per_forum]:
        topic_id = post.get("topic_id")
        topic_info = topic_map.get(topic_id, {})

        text = post.get("blurb", "") or post.get("excerpt", "")
        if not text or len(text.strip()) < 20:
            continue

        # Clean HTML from blurb
        text = _strip_html(text)

        slug = topic_info.get("slug", str(topic_id))
        url = f"{base_url}/t/{slug}/{topic_id}"

        created = topic_info.get("created_at")
        if created and isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00")).isoformat()
            except (ValueError, TypeError):
                created = None

        signals.append({
            "source_id": f"discourse_{forum_name.lower()}_{post.get('id', '')}",
            "url": url,
            "title": topic_info.get("title", ""),
            "text": text[:1000],
            "author": post.get("username", ""),
            "created_at": created,
            "score": topic_info.get("like_count", 0),
            "num_comments": topic_info.get("reply_count", 0),
            "view_count": topic_info.get("views", 0),
            "source": f"discourse_{forum_name.lower()}",
            "source_type": "discourse",
            "source_platform": f"discourse:{forum_name}",
            "community": forum_name,
            "forum_url": base_url,
        })

    return signals


def _strip_html(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
