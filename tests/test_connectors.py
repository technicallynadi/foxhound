"""Tests for GitHub and Reddit connectors."""

from datetime import UTC, datetime, timedelta

from foxhound.adapters.github_connector import (
    GitHubConnector,
    HttpResponse,
    RepoMetadata,
)
from foxhound.scout.connectors.reddit import (
    GITHUB_URL_PATTERN,
    SCOUT_SUBREDDITS,
    RedditConnector,
    RedditPost,
)


class MockHttpClient:
    """Mock HTTP client for testing connectors."""

    def __init__(self, responses: dict[str, HttpResponse] | None = None) -> None:
        self._responses = responses or {}
        self.requests: list[tuple[str, dict, dict]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        self.requests.append((url, headers or {}, params or {}))
        for pattern, response in self._responses.items():
            if pattern in url:
                return response
        return HttpResponse(status_code=404)


class TestGitHubConnector:
    def test_search_trending(self) -> None:
        mock = MockHttpClient({
            "search/repositories": HttpResponse(
                status_code=200,
                json_data={
                    "items": [
                        {
                            "full_name": "owner/repo",
                            "description": "A cool project",
                            "stargazers_count": 500,
                            "forks_count": 50,
                            "language": "Python",
                            "license": {"spdx_id": "MIT"},
                            "open_issues_count": 10,
                            "created_at": "2026-03-01T00:00:00Z",
                            "html_url": "https://github.com/owner/repo",
                            "topics": ["python"],
                        }
                    ]
                },
                headers={"x-ratelimit-remaining": "58"},
            ),
        })
        connector = GitHubConnector(mock)
        repos = connector.search_trending(language="python")
        assert len(repos) == 1
        assert repos[0].name == "owner/repo"
        assert repos[0].stars == 500
        assert repos[0].license_type == "MIT"
        assert connector.rate_remaining == 58

    def test_search_trending_empty(self) -> None:
        mock = MockHttpClient({
            "search/repositories": HttpResponse(
                status_code=200,
                json_data={"items": []},
            ),
        })
        connector = GitHubConnector(mock)
        repos = connector.search_trending()
        assert repos == []

    def test_search_trending_api_error(self) -> None:
        mock = MockHttpClient({
            "search/repositories": HttpResponse(status_code=500),
        })
        connector = GitHubConnector(mock)
        repos = connector.search_trending()
        assert repos == []

    def test_get_repo(self) -> None:
        mock = MockHttpClient({
            "repos/owner/repo": HttpResponse(
                status_code=200,
                json_data={
                    "full_name": "owner/repo",
                    "description": "Test",
                    "stargazers_count": 200,
                    "forks_count": 20,
                    "language": "Rust",
                    "license": None,
                    "open_issues_count": 5,
                    "created_at": "2026-01-01T00:00:00Z",
                    "html_url": "https://github.com/owner/repo",
                },
            ),
        })
        connector = GitHubConnector(mock)
        repo = connector.get_repo("owner", "repo")
        assert repo is not None
        assert repo.name == "owner/repo"
        assert repo.language == "Rust"
        assert repo.license_type == ""

    def test_get_repo_not_found(self) -> None:
        mock = MockHttpClient()
        connector = GitHubConnector(mock)
        repo = connector.get_repo("owner", "nonexistent")
        assert repo is None

    def test_star_velocity(self) -> None:
        connector = GitHubConnector(MockHttpClient())
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        repo = RepoMetadata(
            name="test/repo",
            stars=100,
            created_at=yesterday,
        )
        velocity = connector.calculate_star_velocity(repo)
        assert velocity >= 90.0

    def test_star_velocity_zero_stars(self) -> None:
        connector = GitHubConnector(MockHttpClient())
        repo = RepoMetadata(name="test/empty", stars=0)
        assert connector.calculate_star_velocity(repo) == 0.0

    def test_rate_limiting(self) -> None:
        mock = MockHttpClient({
            "search/repositories": HttpResponse(
                status_code=200,
                json_data={"items": []},
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": str(
                        int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
                    ),
                },
            ),
        })
        connector = GitHubConnector(mock)
        connector.search_trending()
        assert connector.is_rate_limited()
        repos = connector.search_trending()
        assert repos == []

    def test_auth_header(self) -> None:
        mock = MockHttpClient({
            "search/repositories": HttpResponse(
                status_code=200, json_data={"items": []},
            ),
        })
        connector = GitHubConnector(mock, token="ghp_test123")
        connector.search_trending()
        assert len(mock.requests) == 1
        headers = mock.requests[0][1]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer ghp_test123"


class TestRedditConnector:
    def _reddit_listing(self, posts: list[dict]) -> dict:
        return {
            "data": {
                "children": [{"data": p} for p in posts],
            }
        }

    def test_fetch_subreddit_posts(self) -> None:
        mock = MockHttpClient({
            "r/SideProject": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([
                    {
                        "id": "abc123",
                        "title": "Check out my project",
                        "author": "dev1",
                        "url": "https://github.com/dev1/project",
                        "selftext": "",
                        "ups": 50,
                        "num_comments": 10,
                        "created_utc": 1710000000.0,
                    },
                ]),
            ),
        })
        connector = RedditConnector(mock)
        posts = connector.fetch_subreddit_posts("SideProject")
        assert len(posts) == 1
        assert posts[0].title == "Check out my project"
        assert len(posts[0].github_repos) == 1

    def test_extracts_github_links(self) -> None:
        mock = MockHttpClient({
            "r/test": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([
                    {
                        "id": "x1",
                        "title": "My tool: https://github.com/user/tool",
                        "selftext": "Also see https://github.com/user/docs",
                        "url": "",
                        "ups": 10,
                        "num_comments": 2,
                        "created_utc": 1710000000.0,
                    },
                ]),
            ),
        })
        connector = RedditConnector(mock)
        posts = connector.fetch_subreddit_posts("test")
        assert len(posts[0].github_repos) == 2

    def test_deduplicates_github_links(self) -> None:
        connector = RedditConnector(MockHttpClient())
        links = connector._extract_github_links(
            "https://github.com/user/repo "
            "https://github.com/user/repo "
            "https://github.com/User/Repo"
        )
        assert len(links) == 1

    def test_scan_all_subreddits_filters_no_github(self) -> None:
        mock = MockHttpClient({
            "r/SideProject": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([
                    {
                        "id": "no_gh",
                        "title": "No GitHub link here",
                        "selftext": "Just text",
                        "url": "https://example.com",
                        "ups": 5,
                        "num_comments": 1,
                        "created_utc": 1710000000.0,
                    },
                ]),
            ),
            "r/coolgithubprojects": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([]),
            ),
            "r/selfhosted": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([]),
            ),
        })
        connector = RedditConnector(mock)
        posts = connector.scan_all_subreddits()
        assert len(posts) == 0

    def test_api_error_returns_empty(self) -> None:
        mock = MockHttpClient({
            "r/SideProject": HttpResponse(status_code=500),
        })
        connector = RedditConnector(mock)
        posts = connector.fetch_subreddit_posts("SideProject")
        assert posts == []

    def test_upvote_velocity(self) -> None:
        connector = RedditConnector(MockHttpClient())
        one_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
        post = RedditPost(
            post_id="v1",
            title="Test",
            subreddit="test",
            upvotes=60,
            created_utc=one_hour_ago,
        )
        velocity = connector.calculate_upvote_velocity(post)
        assert velocity >= 55.0

    def test_rate_limiting(self) -> None:
        mock = MockHttpClient({
            "r/test": HttpResponse(
                status_code=200,
                json_data=self._reddit_listing([]),
                headers={"x-ratelimit-remaining": "0"},
            ),
        })
        connector = RedditConnector(mock)
        connector.fetch_subreddit_posts("test")
        assert connector.is_rate_limited()


class TestGitHubUrlExtraction:
    def test_standard_url(self) -> None:
        match = GITHUB_URL_PATTERN.search("https://github.com/user/repo")
        assert match is not None
        assert match.group(1) == "user/repo"

    def test_url_in_text(self) -> None:
        text = "Check out https://github.com/cool/project for more"
        match = GITHUB_URL_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "cool/project"

    def test_no_match(self) -> None:
        assert GITHUB_URL_PATTERN.search("https://gitlab.com/user/repo") is None


class TestScoutSubreddits:
    def test_default_subreddits(self) -> None:
        assert "SideProject" in SCOUT_SUBREDDITS
        assert "coolgithubprojects" in SCOUT_SUBREDDITS
        assert "selfhosted" in SCOUT_SUBREDDITS
