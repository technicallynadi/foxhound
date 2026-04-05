import logging

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github.v3+json"}


async def fetch_github_issues(topic: str, limit: int = 30) -> list[dict]:
    """Search GitHub issues by topic, sorted by most commented."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/search/issues",
                params={
                    "q": f"{topic} type:issue",
                    "sort": "comments",
                    "per_page": limit,
                },
                headers=HEADERS,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
    except Exception as e:
        logger.warning("GitHub issue search failed for topic=%s: %s", topic, e)
        return []

    return [_parse_issue(item) for item in items if item.get("body")]


async def fetch_github_discussions(topic: str, limit: int = 20) -> list[dict]:
    """Search GitHub Discussions via the search API.

    GitHub Discussions are searchable through the issues search endpoint
    with type:discussions, or through the general search.
    We also search for common pain-signal discussion titles.
    """
    results: list[dict] = []

    queries = [
        f"{topic} type:discussions",
        f"{topic} feature request type:discussions",
        f"{topic} bug workaround type:discussions",
    ]

    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in queries:
            if len(results) >= limit:
                break
            try:
                resp = await client.get(
                    f"{GITHUB_API}/search/issues",
                    params={
                        "q": query,
                        "sort": "comments",
                        "per_page": min(limit - len(results), 15),
                    },
                    headers=HEADERS,
                )
                if resp.status_code == 422:
                    # GitHub doesn't support type:discussions in all cases
                    continue
                resp.raise_for_status()

                for item in resp.json().get("items", []):
                    item_id = str(item.get("id", ""))
                    if item_id in seen_ids or not item.get("body"):
                        continue
                    seen_ids.add(item_id)
                    results.append(_parse_issue(item, source_type="github_discussion"))

            except Exception as e:
                logger.debug("GitHub discussion search failed for query=%s: %s", query, e)
                continue

    return results


async def find_relevant_repos(topic: str, limit: int = 10) -> list[dict]:
    """Search for relevant GitHub repos to extract READMEs and metadata.

    Returns repo info including the URL for TinyFish to scrape the README.
    Prioritizes repos with many stars/issues (indicates active user base with pain).
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/search/repositories",
                params={
                    "q": f"{topic} in:name,description,readme",
                    "sort": "stars",
                    "per_page": limit,
                },
                headers=HEADERS,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
    except Exception as e:
        logger.warning("GitHub repo search failed for topic=%s: %s", topic, e)
        return []

    repos = []
    for item in items:
        full_name = item.get("full_name", "")
        repos.append({
            "repo": full_name,
            "url": item.get("html_url", ""),
            "readme_url": f"https://github.com/{full_name}#readme",
            "description": item.get("description", "") or "",
            "stars": item.get("stargazers_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "language": item.get("language", ""),
            "topics": item.get("topics", []),
        })

    return repos


async def fetch_repo_issues_with_pain(repo: str, limit: int = 15) -> list[dict]:
    """Fetch issues from a specific repo that are likely to contain pain signals.

    Searches for issues with pain/feature-request/bug language.
    """
    pain_queries = [
        f"repo:{repo} is:issue is:open label:bug",
        f"repo:{repo} is:issue is:open label:enhancement",
        f"repo:{repo} is:issue \"feature request\" OR \"workaround\" OR \"alternative\" OR \"limitation\"",
    ]

    results: list[dict] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in pain_queries:
            if len(results) >= limit:
                break
            try:
                resp = await client.get(
                    f"{GITHUB_API}/search/issues",
                    params={
                        "q": query,
                        "sort": "comments",
                        "per_page": min(limit - len(results), 10),
                    },
                    headers=HEADERS,
                )
                if resp.status_code in (422, 403):
                    continue
                resp.raise_for_status()

                for item in resp.json().get("items", []):
                    item_id = str(item.get("id", ""))
                    if item_id in seen_ids or not item.get("body"):
                        continue
                    seen_ids.add(item_id)
                    parsed = _parse_issue(item)
                    parsed["repo"] = repo
                    results.append(parsed)

            except Exception as e:
                logger.debug("Repo issue search failed for %s: %s", repo, e)
                continue

    return results


def _parse_issue(item: dict, source_type: str = "github_issue") -> dict:
    repo_url = item.get("repository_url", "")
    repo = repo_url.replace("https://api.github.com/repos/", "") if repo_url else ""

    title = item.get("title", "")
    body = item.get("body", "") or ""

    # Merge title and body for richer text
    text = f"{title}\n\n{body}" if title and body else (body or title)

    return {
        "source_id": str(item.get("id", "")),
        "url": item.get("html_url", ""),
        "title": title,
        "text": text,
        "repo": repo,
        "author": (item.get("user") or {}).get("login", ""),
        "created_at": item.get("created_at", ""),
        "labels": [l.get("name", "") for l in item.get("labels", [])],
        "comments_count": item.get("comments", 0),
        "source_type": source_type,
    }
