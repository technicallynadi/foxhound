"""GitHub API connector for scout and discovery operations.

Fetches trending repos, repo metadata, star velocity, issue counts,
and license detection. Handles rate limiting and token auth.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field


class HttpClient(Protocol):
    """Protocol for HTTP client abstraction."""

    def get(
        self, url: str, headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None, timeout: int = 30,
    ) -> "HttpResponse":
        """Make a GET request."""
        ...


class HttpResponse(BaseModel):
    """HTTP response wrapper."""

    status_code: int = Field(..., description="HTTP status code")
    json_data: Any = Field(default=None, description="Parsed JSON body")
    headers: dict[str, str] = Field(default_factory=dict, description="Response headers")

    model_config = {"extra": "forbid"}


class RepoMetadata(BaseModel):
    """GitHub repository metadata."""

    name: str = Field(..., description="Repo full name (owner/repo)")
    description: str = Field(default="", description="Repo description")
    stars: int = Field(default=0, description="Star count")
    forks: int = Field(default=0, description="Fork count")
    language: str = Field(default="", description="Primary language")
    license_type: str = Field(default="", description="License SPDX identifier")
    open_issues: int = Field(default=0, description="Open issue count")
    created_at: str = Field(default="", description="Creation date ISO string")
    html_url: str = Field(default="", description="Repository URL")
    topics: list[str] = Field(default_factory=list, description="Repository topics")

    model_config = {"extra": "forbid"}


class GitHubConnector:
    """Connector for GitHub API operations.

    Supports trending repo discovery, metadata lookup, and star velocity
    calculation. Loads auth token from secret provider.
    """

    API_BASE = "https://api.github.com"

    def __init__(
        self,
        http_client: HttpClient,
        token: str | None = None,
    ) -> None:
        self._client = http_client
        self._token = token
        self._rate_remaining: int | None = None
        self._rate_reset: datetime | None = None

    def _headers(self) -> dict[str, str]:
        """Build request headers with optional auth."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "foxhound-scout",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _update_rate_limit(self, response: HttpResponse) -> None:
        """Update rate limit tracking from response headers."""
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            self._rate_remaining = int(remaining)
        reset = response.headers.get("x-ratelimit-reset")
        if reset is not None:
            self._rate_reset = datetime.fromtimestamp(int(reset), tz=UTC)

    @property
    def rate_remaining(self) -> int | None:
        """Remaining API calls before rate limit."""
        return self._rate_remaining

    def is_rate_limited(self) -> bool:
        """Check if we're currently rate limited."""
        if self._rate_remaining is not None and self._rate_remaining <= 1:
            if self._rate_reset and datetime.now(UTC) < self._rate_reset:
                return True
        return False

    def search_trending(
        self,
        language: str | None = None,
        days: int = 7,
        min_stars: int = 10,
        limit: int = 30,
        query: str | None = None,
    ) -> list[RepoMetadata]:
        """Search for recently created/trending repos.

        Uses GitHub search API to find repos created in the last N days
        sorted by stars. When query is provided, adds it as a keyword filter.
        """
        if self.is_rate_limited():
            return []

        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        search_q = f"created:>{since} stars:>={min_stars}"
        if query:
            search_q = f"{query} {search_q}"
        if language:
            search_q += f" language:{language}"
        query = search_q

        response = self._client.get(
            f"{self.API_BASE}/search/repositories",
            headers=self._headers(),
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": str(min(limit, 100)),
            },
            timeout=30,
        )
        self._update_rate_limit(response)

        if response.status_code != 200:
            return []

        items = response.json_data.get("items", []) if response.json_data else []
        return [self._parse_repo(item) for item in items]

    def get_repo(self, owner: str, repo: str) -> RepoMetadata | None:
        """Get metadata for a specific repository."""
        if self.is_rate_limited():
            return None

        response = self._client.get(
            f"{self.API_BASE}/repos/{owner}/{repo}",
            headers=self._headers(),
            timeout=30,
        )
        self._update_rate_limit(response)

        if response.status_code != 200:
            return None

        return self._parse_repo(response.json_data)

    def calculate_star_velocity(
        self, repo: RepoMetadata, days: int = 7
    ) -> float:
        """Estimate star velocity (stars per day) based on creation date."""
        if not repo.created_at or repo.stars == 0:
            return 0.0

        try:
            created = datetime.fromisoformat(
                repo.created_at.replace("Z", "+00:00")
            )
            age_days = max((datetime.now(UTC) - created).days, 1)
            return repo.stars / age_days
        except (ValueError, TypeError):
            return 0.0

    def _parse_repo(self, data: dict[str, Any]) -> RepoMetadata:
        """Parse GitHub API repo response into RepoMetadata."""
        license_info = data.get("license") or {}
        return RepoMetadata(
            name=data.get("full_name", ""),
            description=(data.get("description") or "")[:500],
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            language=data.get("language") or "",
            license_type=license_info.get("spdx_id") or "",
            open_issues=data.get("open_issues_count", 0),
            created_at=data.get("created_at") or "",
            html_url=data.get("html_url") or "",
            topics=data.get("topics") or [],
        )
