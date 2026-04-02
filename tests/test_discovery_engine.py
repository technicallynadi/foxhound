"""Tests for job discovery engine and adapters."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.discovery.adapters.greenhouse import GreenhouseAdapter, _infer_remote as gh_infer_remote
from app.services.discovery.adapters.lever import LeverAdapter, _infer_remote as lever_infer_remote
from app.services.discovery.adapters.ashby import AshbyAdapter, _infer_remote as ashby_infer_remote
from app.services.discovery.adapters.hn_hiring import HNHiringAdapter, _parse_hn_comment
from app.services.discovery.deduplicator import compute_dedup_hash
from app.services.discovery.ats_detector import detect_ats, is_auto_apply_supported
from app.services.discovery.engine import JobDiscoveryEngine


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------

def test_dedup_hash_stable():
    h1 = compute_dedup_hash("Stripe", "Backend Engineer", "San Francisco")
    h2 = compute_dedup_hash("Stripe", "Backend Engineer", "San Francisco")
    assert h1 == h2

def test_dedup_hash_case_insensitive():
    h1 = compute_dedup_hash("STRIPE", "Backend Engineer", "SF")
    h2 = compute_dedup_hash("stripe", "backend engineer", "sf")
    assert h1 == h2

def test_dedup_hash_different_jobs():
    h1 = compute_dedup_hash("Stripe", "Backend", "SF")
    h2 = compute_dedup_hash("Stripe", "Frontend", "SF")
    assert h1 != h2

def test_dedup_hash_none_location():
    h = compute_dedup_hash("Stripe", "Engineer", None)
    assert isinstance(h, str) and len(h) == 16


# ---------------------------------------------------------------------------
# ATS Detector
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/anthropic/jobs/123", "greenhouse"),
    ("https://jobs.lever.co/stripe/abc", "lever"),
    ("https://jobs.ashbyhq.com/openai/xyz", "ashby"),
    ("https://company.myworkdayjobs.com/en-US/jobs", "workday"),
    ("https://random.com/careers", None),
])
def test_detect_ats(url, expected):
    assert detect_ats(url) == expected

@pytest.mark.parametrize("ats,expected", [
    ("greenhouse", True), ("ashby", True), ("lever", True),
    ("workday", False), ("icims", False), (None, False),
])
def test_auto_apply_supported(ats, expected):
    assert is_auto_apply_supported(ats) == expected


# ---------------------------------------------------------------------------
# Remote inference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location,expected", [
    ("Remote", "remote"), ("San Francisco (Hybrid)", "hybrid"),
    ("New York, NY", None), ("", None),
])
def test_greenhouse_infer_remote(location, expected):
    assert gh_infer_remote(location) == expected

@pytest.mark.parametrize("location,expected", [
    ("Remote - US", "remote"), ("London (Hybrid)", "hybrid"),
    ("Austin, TX", None),
])
def test_lever_infer_remote(location, expected):
    assert lever_infer_remote(location) == expected

def test_ashby_infer_remote_from_field():
    assert ashby_infer_remote("New York", {"isRemote": True}) == "remote"
    assert ashby_infer_remote("Remote", {}) == "remote"
    assert ashby_infer_remote("Hybrid Office", {}) == "hybrid"
    assert ashby_infer_remote("SF", {}) is None


# ---------------------------------------------------------------------------
# HN Comment Parser
# ---------------------------------------------------------------------------

def test_parse_hn_comment_standard():
    text = "Acme Corp | Senior Engineer | Remote | https://acme.com/jobs"
    result = _parse_hn_comment(text)
    assert result is not None
    assert result["company"] == "Acme Corp"
    assert result["title"] == "Senior Engineer"
    assert result["remote_type"] == "remote"
    assert result["apply_url"] == "https://acme.com/jobs"

def test_parse_hn_comment_two_parts():
    text = "Startup | Hiring all roles"
    result = _parse_hn_comment(text)
    assert result is not None
    assert result["company"] == "Startup"

def test_parse_hn_comment_too_short():
    result = _parse_hn_comment("A")
    assert result is None

def test_parse_hn_comment_no_pipe():
    result = _parse_hn_comment("Just a regular comment with no structured data")
    assert result is None


# ---------------------------------------------------------------------------
# Greenhouse Adapter (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_greenhouse_fetch_single_board():
    adapter = GreenhouseAdapter(boards=[("testco", "TestCo")])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": 123,
                "title": "Backend Engineer",
                "absolute_url": "https://boards.greenhouse.io/testco/jobs/123",
                "location": {"name": "Remote"},
                "content": "Build backend systems.",
                "updated_at": "2026-03-01T00:00:00Z",
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.services.discovery.adapters.greenhouse.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert len(listings) == 1
    assert listings[0]["company"] == "TestCo"
    assert listings[0]["title"] == "Backend Engineer"
    assert listings[0]["source"] == "greenhouse"
    assert listings[0]["remote_type"] == "remote"


@pytest.mark.asyncio
async def test_greenhouse_handles_404():
    adapter = GreenhouseAdapter(boards=[("gone", "Gone Co")])

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch("app.services.discovery.adapters.greenhouse.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert listings == []


# ---------------------------------------------------------------------------
# Lever Adapter (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lever_fetch_single_company():
    adapter = LeverAdapter(companies=[("acme", "Acme")])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "id": "abc-123",
            "text": "Frontend Engineer",
            "applyUrl": "https://jobs.lever.co/acme/abc-123/apply",
            "hostedUrl": "https://jobs.lever.co/acme/abc-123",
            "categories": {"location": "New York, NY", "team": "Engineering"},
            "descriptionPlain": "Build frontend.",
            "description": "<p>Build frontend.</p>",
            "lists": [],
        }
    ]
    mock_resp.raise_for_status = MagicMock()

    with patch("app.services.discovery.adapters.lever.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert len(listings) == 1
    assert listings[0]["company"] == "Acme"
    assert listings[0]["source"] == "lever"
    assert listings[0]["location"] == "New York, NY"


# ---------------------------------------------------------------------------
# Ashby Adapter (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ashby_fetch_with_compensation():
    adapter = AshbyAdapter(companies=[("ai", "AI Corp")])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": "xyz",
                "title": "ML Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/ai/xyz",
                "location": "Remote",
                "descriptionPlain": "Train models.",
                "description": "<p>Train models.</p>",
                "compensation": {"min": 200000, "max": 350000, "currency": "USD"},
                "publishedAt": "2026-03-01",
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.services.discovery.adapters.ashby.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert len(listings) == 1
    assert listings[0]["salary_min"] == 200000
    assert listings[0]["salary_max"] == 350000
    assert listings[0]["remote_type"] == "remote"


# ---------------------------------------------------------------------------
# HN Hiring Adapter (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hn_hiring_fetch():
    adapter = HNHiringAdapter()

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "hits": [{"objectID": "999"}]
    }
    search_resp.raise_for_status = MagicMock()

    item_resp = MagicMock()
    item_resp.status_code = 200
    item_resp.json.return_value = {
        "children": [
            {
                "id": 1001,
                "text": "TechStartup | Senior Backend | Remote | https://techstartup.com/jobs this is a longer description that meets the minimum length requirement for parsing",
                "created_at": "2026-03-01T00:00:00Z",
            },
            {
                "id": 1002,
                "text": "short",  # Too short, should be skipped
            },
        ]
    }
    item_resp.raise_for_status = MagicMock()

    with patch("app.services.discovery.adapters.hn_hiring.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[search_resp, item_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert len(listings) == 1
    assert listings[0]["company"] == "TechStartup"
    assert listings[0]["source"] == "hn_hiring"


@pytest.mark.asyncio
async def test_hn_hiring_no_thread():
    adapter = HNHiringAdapter()

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {"hits": []}
    search_resp.raise_for_status = MagicMock()

    with patch("app.services.discovery.adapters.hn_hiring.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        listings = await adapter.fetch_listings()

    assert listings == []


# ---------------------------------------------------------------------------
# Discovery Engine — store_listings dedup (DB integration)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_stores_new_listings(db):
    engine = JobDiscoveryEngine()
    listings = [
        {
            "external_id": "test-001",
            "title": "Test Engineer",
            "company": "TestCo",
            "description": "A test job",
            "apply_url": "https://test.com/jobs/1",
            "source": "test",
            "source_url": "https://test.com",
            "dedup_hash": compute_dedup_hash("TestCo", "Test Engineer", "Remote"),
        },
    ]
    result = await engine._store_listings(db, listings)
    assert result["new"] == 1
    assert result["deduplicated"] == 0


@pytest.mark.asyncio
async def test_engine_deduplicates(db):
    engine = JobDiscoveryEngine()
    dedup_hash = compute_dedup_hash("DedupCo", "Role A", "NY")
    listings = [
        {
            "external_id": "dedup-001",
            "title": "Role A", "company": "DedupCo",
            "description": "A role", "apply_url": "https://x.com/1",
            "source": "test", "source_url": "https://x.com",
            "dedup_hash": dedup_hash,
        },
    ]
    # First insert
    r1 = await engine._store_listings(db, listings)
    assert r1["new"] == 1

    # Second insert with same hash → dedup
    r2 = await engine._store_listings(db, listings)
    assert r2["new"] == 0
    assert r2["deduplicated"] == 1


@pytest.mark.asyncio
async def test_engine_empty_listings(db):
    engine = JobDiscoveryEngine()
    result = await engine._store_listings(db, [])
    assert result == {"new": 0, "updated": 0, "deduplicated": 0}
