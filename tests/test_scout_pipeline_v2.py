"""Tests for Scout Pipeline V2: fetch, score, select."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from foxhound.adapters.github_connector import HttpResponse
from foxhound.core.models import OpportunityState, WorkItemKind, WorkItemState
from foxhound.scout.fetcher import (
    ScoutConfig,
    ScoutFetcher,
    SourceConfig,
    _make_dedupe_hash,
)
from foxhound.scout.scoring import (
    ScoringPipeline,
    ScoringPreferences,
    _raw_to_scout_source,
)
from foxhound.scout.selection import (
    GeneratedTask,
    SelectionPipeline,
    analyze_opportunity,
)
from foxhound.storage.database import Database, RawOpportunityStore

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db() -> Database:
    """Create in-memory database for testing."""
    return Database(":memory:")


@pytest.fixture
def raw_store(db: Database) -> RawOpportunityStore:
    return RawOpportunityStore(db)


@pytest.fixture
def mock_http_client() -> MagicMock:
    client = MagicMock()
    client.get.return_value = HttpResponse(
        status_code=200, json_data={"items": []}, headers={}
    )
    return client


def _make_github_response(repos: list[dict]) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        json_data={"items": repos},
        headers={"x-ratelimit-remaining": "4999"},
    )


def _make_reddit_response(posts: list[dict]) -> HttpResponse:
    children = [{"data": p} for p in posts]
    return HttpResponse(
        status_code=200,
        json_data={"data": {"children": children}},
        headers={},
    )


def _sample_github_repo(
    name: str = "owner/test-repo",
    stars: int = 100,
    language: str = "Python",
    license_spdx: str = "MIT",
) -> dict:
    return {
        "full_name": name,
        "description": "A test repository",
        "stargazers_count": stars,
        "forks_count": 10,
        "language": language,
        "license": {"spdx_id": license_spdx},
        "open_issues_count": 5,
        "created_at": (datetime.now() - timedelta(days=3)).isoformat() + "Z",
        "html_url": f"https://github.com/{name}",
        "topics": ["testing"],
    }


def _sample_reddit_post(
    post_id: str = "abc123",
    title: str = "Check out my project",
    github_url: str = "https://github.com/owner/cool-project",
) -> dict:
    return {
        "id": post_id,
        "title": title,
        "author": "testuser",
        "url": github_url,
        "selftext": f"Built this thing: {github_url}",
        "ups": 50,
        "num_comments": 10,
        "created_utc": datetime.now().timestamp() - 3600,
    }


# ============================================================================
# #86: Raw Opportunity Storage and Deduplication
# ============================================================================


class TestRawOpportunityStore:
    def test_upsert_new_item(self, raw_store: RawOpportunityStore) -> None:
        is_new = raw_store.upsert(
            raw_id="raw_001",
            source="github_trending",
            source_url="https://github.com/test/repo",
            source_id="test/repo",
            title="Test Repo",
            raw_payload='{"stars": 100}',
            fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "test/repo"),
        )
        assert is_new is True

    def test_upsert_duplicate_updates(self, raw_store: RawOpportunityStore) -> None:
        dedupe = _make_dedupe_hash("github_trending", "test/repo")
        raw_store.upsert(
            raw_id="raw_001", source="github_trending",
            source_url="https://github.com/test/repo", source_id="test/repo",
            title="Test Repo", raw_payload='{"stars": 100}',
            fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=dedupe,
        )

        is_new = raw_store.upsert(
            raw_id="raw_002", source="github_trending",
            source_url="https://github.com/test/repo", source_id="test/repo",
            title="Test Repo Updated", raw_payload='{"stars": 200}',
            fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=dedupe,
        )
        assert is_new is False

        item = raw_store.get("raw_001")
        assert item is not None
        assert json.loads(item["raw_payload"])["stars"] == 200
        assert item["title"] == "Test Repo Updated"

    def test_list_unscored(self, raw_store: RawOpportunityStore) -> None:
        for i in range(3):
            raw_store.upsert(
                raw_id=f"raw_{i:03d}", source="github_trending",
                source_url=f"https://github.com/test/repo{i}",
                source_id=f"test/repo{i}",
                title=f"Repo {i}", raw_payload=f'{{"stars": {i * 100}}}',
                fetched_at=datetime.now().isoformat(),
                expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
                dedupe_hash=_make_dedupe_hash("github_trending", f"test/repo{i}"),
            )

        unscored = raw_store.list_unscored()
        assert len(unscored) == 3

        raw_store.mark_scored("raw_000")
        unscored = raw_store.list_unscored()
        assert len(unscored) == 2

    def test_list_unscored_by_source(self, raw_store: RawOpportunityStore) -> None:
        raw_store.upsert(
            raw_id="raw_gh", source="github_trending",
            source_url="url1", source_id="gh1", title="GH",
            raw_payload="{}", fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "gh1"),
        )
        raw_store.upsert(
            raw_id="raw_rd", source="reddit",
            source_url="url2", source_id="rd1", title="Reddit",
            raw_payload="{}", fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("reddit", "rd1"),
        )

        gh_only = raw_store.list_unscored(source="github_trending")
        assert len(gh_only) == 1
        assert gh_only[0]["source"] == "github_trending"

    def test_mark_scored(self, raw_store: RawOpportunityStore) -> None:
        raw_store.upsert(
            raw_id="raw_001", source="github_trending",
            source_url="url", source_id="id1", title="Test",
            raw_payload="{}", fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "id1"),
        )

        assert raw_store.mark_scored("raw_001") is True
        item = raw_store.get("raw_001")
        assert item is not None
        assert item["scored"] == 1

    def test_prune_expired(self, raw_store: RawOpportunityStore) -> None:
        raw_store.upsert(
            raw_id="raw_old", source="github_trending",
            source_url="url", source_id="old1", title="Old",
            raw_payload="{}", fetched_at=(datetime.now() - timedelta(days=10)).isoformat(),
            expires_at=(datetime.now() - timedelta(days=1)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "old1"),
        )
        raw_store.upsert(
            raw_id="raw_new", source="github_trending",
            source_url="url", source_id="new1", title="New",
            raw_payload="{}", fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "new1"),
        )

        pruned = raw_store.prune_expired()
        assert pruned == 1
        assert raw_store.get("raw_old") is None
        assert raw_store.get("raw_new") is not None

    def test_count_by_source(self, raw_store: RawOpportunityStore) -> None:
        for i, src in enumerate(["github_trending", "github_trending", "reddit"]):
            raw_store.upsert(
                raw_id=f"raw_{i}", source=src,
                source_url="url", source_id=f"id_{i}", title=f"Item {i}",
                raw_payload="{}", fetched_at=datetime.now().isoformat(),
                expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
                dedupe_hash=_make_dedupe_hash(src, f"id_{i}"),
            )

        counts = raw_store.count_by_source()
        assert counts["github_trending"] == 2
        assert counts["reddit"] == 1

    def test_fetch_metadata(self, raw_store: RawOpportunityStore) -> None:
        assert raw_store.get_fetch_metadata("github_trending") is None

        raw_store.update_fetch_metadata("github_trending", items_fetched=10)
        meta = raw_store.get_fetch_metadata("github_trending")
        assert meta is not None
        assert meta["items_fetched"] == 10

    def test_get_nonexistent(self, raw_store: RawOpportunityStore) -> None:
        assert raw_store.get("nonexistent") is None

    def test_mark_scored_nonexistent(self, raw_store: RawOpportunityStore) -> None:
        assert raw_store.mark_scored("nonexistent") is False


# ============================================================================
# #85: Scout Data Fetching Layer
# ============================================================================


class TestScoutConfig:
    def test_default_config(self) -> None:
        config = ScoutConfig()
        assert config.fetch_interval_hours == 6
        assert config.is_source_enabled("github_trending")
        assert config.is_source_enabled("reddit")
        assert not config.is_source_enabled("hackernews")

    def test_source_interval_override(self) -> None:
        config = ScoutConfig(
            sources={
                "github_trending": SourceConfig(fetch_interval_hours=3),
                "reddit": SourceConfig(fetch_interval_hours=12),
            }
        )
        assert config.get_source_interval("github_trending") == 3
        assert config.get_source_interval("reddit") == 12

    def test_disabled_source(self) -> None:
        config = ScoutConfig(
            sources={
                "github_trending": SourceConfig(enabled=False),
                "reddit": SourceConfig(),
            }
        )
        assert not config.is_source_enabled("github_trending")
        assert config.is_source_enabled("reddit")


class TestScoutFetcher:
    def test_fetch_github_stores_raw(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo("owner/repo1"),
            _sample_github_repo("owner/repo2"),
        ])

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all(force_refresh=True)

        assert len(summary.results) >= 1
        gh_result = next(r for r in summary.results if r.source == "github_trending")
        assert gh_result.items_fetched == 2
        assert gh_result.new_items == 2

    def test_fetch_skips_fresh_data(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        store = RawOpportunityStore(db)
        store.update_fetch_metadata("github_trending", items_fetched=5)
        store.update_fetch_metadata("reddit", items_fetched=3)

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all()

        for result in summary.results:
            assert result.skipped_fresh is True

    def test_fetch_refresh_bypasses_freshness(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        store = RawOpportunityStore(db)
        store.update_fetch_metadata("github_trending", items_fetched=5)

        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo("owner/new-repo"),
        ])

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all(force_refresh=True)

        gh_result = next(
            (r for r in summary.results if r.source == "github_trending"),
            None,
        )
        assert gh_result is not None
        assert gh_result.skipped_fresh is False

    def test_fetch_updates_existing(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo("owner/repo1", stars=100),
        ])

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        fetcher.fetch_all(force_refresh=True)

        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo("owner/repo1", stars=200),
        ])
        summary = fetcher.fetch_all(force_refresh=True)
        gh_result = next(r for r in summary.results if r.source == "github_trending")
        assert gh_result.updated_items == 1
        assert gh_result.new_items == 0

    def test_fetch_prunes_expired(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        store = RawOpportunityStore(db)
        store.upsert(
            raw_id="raw_expired", source="github_trending",
            source_url="url", source_id="expired",
            title="Expired", raw_payload="{}",
            fetched_at=(datetime.now() - timedelta(days=10)).isoformat(),
            expires_at=(datetime.now() - timedelta(days=1)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "expired"),
        )

        mock_http_client.get.return_value = _make_github_response([])
        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all(force_refresh=True)
        assert summary.pruned == 1

    def test_fetch_disabled_source_skipped(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        config = ScoutConfig(sources={
            "github_trending": SourceConfig(enabled=False),
            "reddit": SourceConfig(enabled=False),
        })

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client, config=config)
        summary = fetcher.fetch_all(force_refresh=True)
        assert len(summary.results) == 0

    def test_fetch_error_does_not_block_others(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network down")
            return _make_reddit_response([_sample_reddit_post()])

        mock_http_client.get.side_effect = side_effect

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all(force_refresh=True)

        errors = [r for r in summary.results if r.error]
        successes = [r for r in summary.results if not r.error and not r.skipped_fresh]
        assert len(errors) == 1
        assert len(successes) >= 1

    def test_fetch_reddit_stores_raw(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        mock_http_client.get.side_effect = [
            HttpResponse(status_code=200, json_data={"items": []}, headers={}),
            _make_reddit_response([_sample_reddit_post("post1")]),
            _make_reddit_response([_sample_reddit_post("post2")]),
            _make_reddit_response([_sample_reddit_post("post3")]),
        ]

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        summary = fetcher.fetch_all(force_refresh=True)

        rd_result = next(
            (r for r in summary.results if r.source == "reddit"),
            None,
        )
        assert rd_result is not None
        assert rd_result.items_fetched >= 1

    def test_timestamp_updated_after_fetch(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo(),
        ])

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client)
        fetcher.fetch_all(force_refresh=True)

        store = RawOpportunityStore(db)
        meta = store.get_fetch_metadata("github_trending")
        assert meta is not None
        assert meta["items_fetched"] == 1

    def test_fetch_interval_override_per_source(
        self, db: Database, mock_http_client: MagicMock
    ) -> None:
        config = ScoutConfig(
            fetch_interval_hours=6,
            sources={
                "github_trending": SourceConfig(fetch_interval_hours=0.001),
                "reddit": SourceConfig(fetch_interval_hours=999),
            },
        )

        # Set github metadata to 1 hour ago (stale for 0.001h interval)
        with db.connection() as conn:
            old_time = (datetime.now() - timedelta(hours=1)).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO scout_fetch_metadata
                   (source, last_fetched_at, items_fetched, rate_limit_hits)
                   VALUES (?, ?, ?, ?)""",
                ("github_trending", old_time, 1, 0),
            )
            conn.execute(
                """INSERT OR REPLACE INTO scout_fetch_metadata
                   (source, last_fetched_at, items_fetched, rate_limit_hits)
                   VALUES (?, ?, ?, ?)""",
                ("reddit", datetime.now().isoformat(), 1, 0),
            )
            conn.commit()

        mock_http_client.get.return_value = _make_github_response([
            _sample_github_repo(),
        ])

        fetcher = ScoutFetcher(db=db, http_client=mock_http_client, config=config)
        summary = fetcher.fetch_all()

        gh = next((r for r in summary.results if r.source == "github_trending"), None)
        rd = next((r for r in summary.results if r.source == "reddit"), None)

        assert gh is not None and gh.skipped_fresh is False
        assert rd is not None and rd.skipped_fresh is True


class TestDedupeHash:
    def test_same_inputs_same_hash(self) -> None:
        h1 = _make_dedupe_hash("github_trending", "owner/repo")
        h2 = _make_dedupe_hash("github_trending", "owner/repo")
        assert h1 == h2

    def test_different_inputs_different_hash(self) -> None:
        h1 = _make_dedupe_hash("github_trending", "owner/repo1")
        h2 = _make_dedupe_hash("github_trending", "owner/repo2")
        assert h1 != h2

    def test_different_sources_different_hash(self) -> None:
        h1 = _make_dedupe_hash("github_trending", "owner/repo")
        h2 = _make_dedupe_hash("reddit", "owner/repo")
        assert h1 != h2


# ============================================================================
# #87: Scoring Pipeline
# ============================================================================


class TestRawToScoutSource:
    def test_github_raw_conversion(self) -> None:
        raw = {
            "raw_id": "raw_001",
            "source": "github_trending",
            "source_url": "https://github.com/owner/repo",
            "title": "owner/repo",
            "raw_payload": json.dumps({
                "name": "owner/repo",
                "description": "A cool project",
                "stars": 500,
                "star_velocity": 10.0,
                "language": "Python",
                "license_type": "MIT",
                "html_url": "https://github.com/owner/repo",
                "topics": ["cli", "tool"],
            }),
        }
        source = _raw_to_scout_source(raw)
        assert source.title == "owner/repo"
        assert source.stars == 500
        assert source.star_velocity == 10.0
        assert source.language == "Python"
        assert source.license_type == "MIT"
        assert source.source_type == "github_trending"

    def test_reddit_raw_conversion(self) -> None:
        raw = {
            "raw_id": "raw_002",
            "source": "reddit",
            "source_url": "https://reddit.com/r/test",
            "title": "Check out my project",
            "raw_payload": json.dumps({
                "title": "Check out my project",
                "selftext": "Built something cool",
                "upvotes": 100,
                "upvote_velocity": 5.0,
                "subreddit": "SideProject",
                "github_repos": ["https://github.com/owner/cool"],
            }),
        }
        source = _raw_to_scout_source(raw)
        assert source.title == "Check out my project"
        assert source.source_type == "reddit"
        assert source.source_url == "https://github.com/owner/cool"

    def test_unknown_source_conversion(self) -> None:
        raw = {
            "raw_id": "raw_003",
            "source": "hackernews",
            "source_url": "https://news.ycombinator.com/item?id=123",
            "title": "Show HN: My project",
            "raw_payload": json.dumps({"title": "Show HN"}),
        }
        source = _raw_to_scout_source(raw)
        assert source.source_type == "hackernews"
        assert source.title == "Show HN: My project"


class TestScoringPipeline:
    def _insert_raw(self, store: RawOpportunityStore, i: int = 0, **kwargs: str) -> None:
        defaults = {
            "raw_id": f"raw_{i:03d}",
            "source": "github_trending",
            "source_url": f"https://github.com/owner/repo{i}",
            "source_id": f"owner/repo{i}",
            "title": f"owner/repo{i}",
            "raw_payload": json.dumps({
                "name": f"owner/repo{i}",
                "description": f"Project {i}",
                "stars": 500,
                "star_velocity": 10.0,
                "language": "Python",
                "license_type": "MIT",
                "html_url": f"https://github.com/owner/repo{i}",
                "topics": ["testing"],
            }),
            "fetched_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
            "dedupe_hash": _make_dedupe_hash("github_trending", f"owner/repo{i}"),
        }
        defaults.update(kwargs)
        store.upsert(**defaults)

    def test_scores_unscored_items(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)
        self._insert_raw(store, 1)

        pipeline = ScoringPipeline(db=db)
        result = pipeline.score_all()

        assert result.processed == 2
        assert result.passed == 2
        assert len(result.opportunity_ids) == 2

    def test_already_scored_not_reprocessed(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)
        store.mark_scored("raw_000")

        pipeline = ScoringPipeline(db=db)
        result = pipeline.score_all()

        assert result.processed == 0

    def test_creates_suggested_opportunities(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(db=db)
        pipeline.score_all()

        suggested = pipeline.get_suggested_opportunities()
        assert len(suggested) >= 1
        assert suggested[0].state == OpportunityState.SUGGESTED

    def test_marks_raw_as_scored(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(db=db)
        pipeline.score_all()

        unscored = store.list_unscored()
        assert len(unscored) == 0

    def test_filters_low_score(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        store.upsert(
            raw_id="raw_low", source="github_trending",
            source_url="https://github.com/test/low",
            source_id="test/low", title="test/low",
            raw_payload=json.dumps({
                "name": "test/low",
                "description": "Low quality",
                "stars": 0, "star_velocity": 0.0,
                "language": "", "license_type": "gpl-3.0",
                "html_url": "https://github.com/test/low",
                "topics": [],
            }),
            fetched_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            dedupe_hash=_make_dedupe_hash("github_trending", "test/low"),
        )

        pipeline = ScoringPipeline(
            db=db, preferences=ScoringPreferences(min_score=0.5)
        )
        result = pipeline.score_all()
        assert result.filtered >= 1

    def test_language_filter(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(
            db=db, preferences=ScoringPreferences(languages=["Rust"])
        )
        result = pipeline.score_all()
        assert result.filtered == 1
        assert result.passed == 0

    def test_exclude_repos_filter(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(
            db=db, preferences=ScoringPreferences(exclude_repos=["repo0"])
        )
        result = pipeline.score_all()
        assert result.filtered == 1

    def test_empty_batch(self, db: Database) -> None:
        pipeline = ScoringPipeline(db=db)
        result = pipeline.score_all()
        assert result.processed == 0
        assert result.passed == 0

    def test_uses_fast_tier_scoring(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(db=db)
        result = pipeline.score_all()
        assert result.total_cost == 0.0

    def test_dedup_against_existing_opportunities(self, db: Database) -> None:
        store = RawOpportunityStore(db)
        self._insert_raw(store, 0)

        pipeline = ScoringPipeline(db=db)
        result1 = pipeline.score_all()
        assert result1.passed == 1

        self._insert_raw(store, 10, raw_payload=json.dumps({
            "name": "owner/repo0",
            "description": "Project 0",
            "stars": 500, "star_velocity": 10.0,
            "language": "Python", "license_type": "MIT",
            "html_url": "https://github.com/owner/repo0",
            "topics": ["testing"],
        }), dedupe_hash=_make_dedupe_hash("github_trending", "owner/repo_dup"))
        result2 = pipeline.score_all()
        assert result2.filtered >= 1


# ============================================================================
# #88: Opportunity Selection and Task Generation
# ============================================================================


class TestAnalyzeOpportunity:
    def test_basic_analysis(self) -> None:
        analysis = analyze_opportunity(
            opportunity_id="opp_001",
            raw_payload={
                "name": "owner/cool-tool",
                "description": "A CLI tool for productivity",
                "language": "Python",
                "stars": 500,
                "topics": ["cli", "productivity"],
            },
            source_type="github_trending",
        )
        assert analysis.opportunity_id == "opp_001"
        assert "owner/cool-tool" in analysis.summary
        assert len(analysis.tasks) >= 2

    def test_missing_docs_detected(self) -> None:
        analysis = analyze_opportunity(
            opportunity_id="opp_002",
            raw_payload={"name": "test/repo", "description": ""},
            source_type="github_trending",
        )
        assert "Missing or minimal documentation" in analysis.gaps

    def test_low_traction_risk(self) -> None:
        analysis = analyze_opportunity(
            opportunity_id="opp_003",
            raw_payload={"name": "test/repo", "stars": 10},
            source_type="github_trending",
        )
        assert any("Low traction" in r for r in analysis.risks)

    def test_high_issue_count_gap(self) -> None:
        analysis = analyze_opportunity(
            opportunity_id="opp_004",
            raw_payload={
                "name": "test/repo",
                "description": "Lots of issues",
                "open_issues": 100,
            },
            source_type="github_trending",
        )
        assert any("open issue count" in g for g in analysis.gaps)

    def test_task_generation(self) -> None:
        analysis = analyze_opportunity(
            opportunity_id="opp_005",
            raw_payload={
                "name": "test/tool",
                "description": "",
                "language": "Rust",
                "topics": [],
            },
            source_type="github_trending",
        )
        titles = [t.title for t in analysis.tasks]
        assert any("scaffold" in t.lower() for t in titles)
        assert any("core" in t.lower() for t in titles)
        assert any("documentation" in t.lower() for t in titles)
        assert any("test" in t.lower() for t in titles)


class TestGeneratedTask:
    def test_valid_task(self) -> None:
        task = GeneratedTask(
            title="Build feature",
            description="Implement the thing",
            complexity="high",
        )
        assert task.title == "Build feature"
        assert task.complexity == "high"

    def test_default_complexity(self) -> None:
        task = GeneratedTask(title="Quick fix")
        assert task.complexity == "medium"


class TestSelectionPipeline:
    def _create_suggested_opportunity(self, db: Database) -> str:
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(db)
        item = mgr.create(
            title="test/cool-project",
            source_type="github_trending",
            source_url="https://github.com/test/cool-project",
            evidence={
                "name": "test/cool-project",
                "description": "A nice project to build on",
                "language": "Python",
                "stars": 500,
                "topics": ["cli"],
            },
        )
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(
            item.opportunity_id,
            credibility=0.7, novelty=0.6,
            actionability=0.8, business_value=0.7,
        )
        mgr.suggest(item.opportunity_id)
        return item.opportunity_id

    def test_deep_analyze(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)
        from foxhound.scout.opportunity import OpportunityManager
        OpportunityManager(db).approve(opp_id)

        pipeline = SelectionPipeline(db=db)
        analysis = pipeline.deep_analyze(opp_id)

        assert analysis.opportunity_id == opp_id
        assert len(analysis.tasks) >= 2
        assert analysis.summary != ""

    def test_create_tasks_from_analysis(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)
        from foxhound.scout.opportunity import OpportunityManager
        OpportunityManager(db).approve(opp_id)

        pipeline = SelectionPipeline(db=db)
        analysis = pipeline.deep_analyze(opp_id)
        tasks = pipeline.create_tasks_from_analysis(
            opp_id, analysis, repo_id="repo_001",
        )

        assert len(tasks) == len(analysis.tasks)
        for task in tasks:
            assert task.kind == WorkItemKind.EXECUTION
            assert task.state == WorkItemState.APPROVED
            assert task.repo_id == "repo_001"

    def test_selective_task_approval(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)
        from foxhound.scout.opportunity import OpportunityManager
        OpportunityManager(db).approve(opp_id)

        pipeline = SelectionPipeline(db=db)
        analysis = pipeline.deep_analyze(opp_id)
        tasks = pipeline.create_tasks_from_analysis(
            opp_id, analysis, repo_id="repo_001",
            approved_indices=[0],
        )

        assert len(tasks) == 1

    def test_rejected_tasks_not_created(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)
        from foxhound.scout.opportunity import OpportunityManager
        OpportunityManager(db).approve(opp_id)

        pipeline = SelectionPipeline(db=db)
        analysis = pipeline.deep_analyze(opp_id)
        tasks = pipeline.create_tasks_from_analysis(
            opp_id, analysis, repo_id="repo_001",
            approved_indices=[],
        )

        assert len(tasks) == 0

    def test_approve_and_generate_full_flow(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)

        pipeline = SelectionPipeline(db=db)
        analysis, tasks = pipeline.approve_and_generate(opp_id, repo_id="repo_001")

        assert len(tasks) >= 2
        assert analysis.opportunity_id == opp_id
        for task in tasks:
            assert task.state == WorkItemState.APPROVED

    def test_analyze_nonexistent_raises(self, db: Database) -> None:
        pipeline = SelectionPipeline(db=db)
        with pytest.raises(ValueError, match="not found"):
            pipeline.deep_analyze("opp_nonexistent")

    def test_approve_and_generate_nonexistent_raises(self, db: Database) -> None:
        pipeline = SelectionPipeline(db=db)
        with pytest.raises(ValueError, match="not found"):
            pipeline.approve_and_generate("opp_nonexistent", "repo_001")

    def test_task_evidence_includes_analysis(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)
        from foxhound.scout.opportunity import OpportunityManager
        OpportunityManager(db).approve(opp_id)

        pipeline = SelectionPipeline(db=db)
        analysis = pipeline.deep_analyze(opp_id)
        tasks = pipeline.create_tasks_from_analysis(
            opp_id, analysis, repo_id="repo_001",
        )

        for task in tasks:
            assert "opportunity_id" in task.evidence
            assert "complexity" in task.evidence
            assert "analysis_summary" in task.evidence

    def test_converts_opportunity_to_project(self, db: Database) -> None:
        opp_id = self._create_suggested_opportunity(db)

        pipeline = SelectionPipeline(db=db)
        pipeline.approve_and_generate(opp_id, repo_id="repo_001")

        from foxhound.scout.opportunity import OpportunityManager
        mgr = OpportunityManager(db)
        item = mgr.get(opp_id)
        assert item is not None
        assert item.state == OpportunityState.CONVERTED_TO_PROJECT
