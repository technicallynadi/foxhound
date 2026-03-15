"""Reddit API connector for scout discovery.

Scans subreddits for project posts, extracts repo links,
analyzes upvote velocity. All Reddit content is UNTRUSTED.
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from foxhound.adapters.github_connector import HttpClient, HttpResponse

SCOUT_SUBREDDITS = ["SideProject", "coolgithubprojects", "selfhosted"]

GITHUB_URL_PATTERN = re.compile(
    r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"
)


class RedditPost(BaseModel):
    """Parsed Reddit post with extracted metadata."""

    post_id: str = Field(..., description="Reddit post ID")
    title: str = Field(..., description="Post title")
    subreddit: str = Field(..., description="Subreddit name")
    author: str = Field(default="", description="Post author")
    url: str = Field(default="", description="Post URL")
    selftext: str = Field(default="", description="Post body text")
    upvotes: int = Field(default=0, description="Upvote count")
    comment_count: int = Field(default=0, description="Comment count")
    created_utc: float = Field(default=0.0, description="Creation timestamp")
    github_repos: list[str] = Field(
        default_factory=list, description="Extracted GitHub repo URLs"
    )

    model_config = {"extra": "forbid"}


class RedditConnector:
    """Connector for Reddit API operations.

    Scans configured subreddits for project posts and extracts
    GitHub repository links. All content treated as UNTRUSTED.
    """

    API_BASE = "https://oauth.reddit.com"
    PUBLIC_BASE = "https://www.reddit.com"

    def __init__(
        self,
        http_client: HttpClient,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str = "foxhound-scout/1.0",
    ) -> None:
        self._client = http_client
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._access_token: str | None = None
        self._rate_remaining: int | None = None

    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {"User-Agent": self._user_agent}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    @property
    def rate_remaining(self) -> int | None:
        """Remaining API calls before rate limit."""
        return self._rate_remaining

    def _update_rate_limit(self, response: HttpResponse) -> None:
        """Update rate limit tracking from response headers."""
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            self._rate_remaining = int(float(remaining))

    def is_rate_limited(self) -> bool:
        """Check if we're currently rate limited."""
        return self._rate_remaining is not None and self._rate_remaining <= 1

    def fetch_subreddit_posts(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
    ) -> list[RedditPost]:
        """Fetch posts from a subreddit.

        Uses the public JSON endpoint if no OAuth token is available.
        """
        if self.is_rate_limited():
            return []

        if self._access_token:
            url = f"{self.API_BASE}/r/{subreddit}/{sort}"
        else:
            url = f"{self.PUBLIC_BASE}/r/{subreddit}/{sort}.json"

        response = self._client.get(
            url,
            headers=self._headers(),
            params={"limit": str(min(limit, 100))},
            timeout=30,
        )
        self._update_rate_limit(response)

        if response.status_code != 200:
            return []

        return self._parse_listing(response.json_data, subreddit)

    def scan_all_subreddits(
        self,
        subreddits: list[str] | None = None,
        limit_per_sub: int = 25,
    ) -> list[RedditPost]:
        """Scan multiple subreddits and return posts with GitHub links."""
        subs = subreddits or SCOUT_SUBREDDITS
        all_posts: list[RedditPost] = []

        for sub in subs:
            posts = self.fetch_subreddit_posts(sub, limit=limit_per_sub)
            for post in posts:
                if post.github_repos:
                    all_posts.append(post)

        return all_posts

    def calculate_upvote_velocity(self, post: RedditPost) -> float:
        """Calculate upvotes per hour since post creation."""
        if post.created_utc <= 0 or post.upvotes <= 0:
            return 0.0

        created = datetime.fromtimestamp(post.created_utc, tz=UTC)
        age_hours = max((datetime.now(UTC) - created).total_seconds() / 3600, 1)
        return post.upvotes / age_hours

    def _parse_listing(
        self, data: Any, subreddit: str
    ) -> list[RedditPost]:
        """Parse Reddit listing response into RedditPost objects."""
        if not data or not isinstance(data, dict):
            return []

        children = data.get("data", {}).get("children", [])
        posts: list[RedditPost] = []

        for child in children:
            post_data = child.get("data", {})
            if not post_data:
                continue

            title = (post_data.get("title") or "")[:300]
            selftext = (post_data.get("selftext") or "")[:2000]
            url = post_data.get("url") or ""

            github_repos = self._extract_github_links(
                f"{title} {selftext} {url}"
            )

            posts.append(RedditPost(
                post_id=post_data.get("id", ""),
                title=title,
                subreddit=subreddit,
                author=post_data.get("author") or "",
                url=url,
                selftext=selftext,
                upvotes=post_data.get("ups", 0),
                comment_count=post_data.get("num_comments", 0),
                created_utc=post_data.get("created_utc", 0.0),
                github_repos=github_repos,
            ))

        return posts

    def _extract_github_links(self, text: str) -> list[str]:
        """Extract GitHub repository URLs from text."""
        matches = GITHUB_URL_PATTERN.findall(text)
        seen: set[str] = set()
        repos: list[str] = []
        for match in matches:
            normalized = match.rstrip("/").lower()
            if normalized not in seen:
                seen.add(normalized)
                repos.append(f"https://github.com/{match}")
        return repos
