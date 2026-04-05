"""Tests for jobs marketplace API routes: feed, detail, actions."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

# ---------------------------------------------------------------------------
# Public feed (no auth required — these don't need user_id fixture)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_public_feed_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/public")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_public_feed_with_jobs(db, sample_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/public")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_public_feed_search(db, sample_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/public", params={"search": "Anthropic"})
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert any(j["company"] == "Anthropic" for j in jobs)


@pytest.mark.asyncio
async def test_public_feed_pagination():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/public", params={"page": 1, "per_page": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 2


# ---------------------------------------------------------------------------
# Public stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_public_stats(db, sample_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs/public/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_jobs"] >= 3
    assert data["total_companies"] >= 1
    assert "by_ats" in data


# ---------------------------------------------------------------------------
# Authenticated feed (auth handled by conftest dependency override)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_jobs_no_matches(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_jobs_with_matches(db, sample_profile, sample_jobs, sample_matches):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    scores = [item["match_score"] for item in data["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_list_jobs_min_score_filter(db, sample_profile, sample_jobs, sample_matches):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/jobs", params={"min_score": 90})
    data = resp.json()
    assert all(item["match_score"] >= 90 for item in data["items"])


# ---------------------------------------------------------------------------
# Job detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_not_found(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/jobs/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_job_detail(db, sample_profile, sample_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/jobs/{sample_jobs[0].id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"]["company"] == "Anthropic"


# ---------------------------------------------------------------------------
# User actions (dismiss, save, feedback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dismiss_job(db, sample_profile, sample_jobs, sample_matches):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/jobs/{sample_jobs[0].id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"


@pytest.mark.asyncio
async def test_save_job(db, sample_profile, sample_jobs, sample_matches):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/jobs/{sample_jobs[1].id}/save")
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_feedback_thumbs_up(db, sample_profile, sample_jobs, sample_matches):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/jobs/{sample_jobs[2].id}/feedback",
            json={"feedback": "thumbs_up"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "feedback_recorded"


@pytest.mark.asyncio
async def test_feedback_invalid(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/jobs/{uuid4()}/feedback",
            json={"feedback": "invalid_value"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dismiss_no_match(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/jobs/{uuid4()}/dismiss")
    assert resp.status_code == 404
