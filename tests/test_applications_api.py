"""Tests for applications API routes: create, list, stats, detail."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.application import Application
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def sample_application(db, sample_profile, sample_jobs):
    """Create a sample submitted application."""
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="submitted",
        trigger="manual",
        tinyfish_status="submitted",
        tinyfish_duration_ms=3500,
        submitted_at=datetime.now(UTC),
    )
    db.add(application)
    await db.commit()
    return application


# ---------------------------------------------------------------------------
# List applications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_applications_empty(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/applications")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_applications_with_data(db, sample_application):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/applications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["status"] == "submitted"
    assert item["job"]["company"] == "Anthropic"


@pytest.mark.asyncio
async def test_list_applications_filter_by_status(db, sample_profile, sample_jobs):
    failed_app = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[1].id,
        status="failed",
        trigger="manual",
        error_type="timeout",
    )
    db.add(failed_app)
    await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/applications", params={"status": "failed"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["status"] == "failed" for item in items)


# ---------------------------------------------------------------------------
# Application detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_application_detail(db, sample_application):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/applications/{sample_application.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sample_application.id
    assert data["tinyfish_duration_ms"] == 3500


@pytest.mark.asyncio
async def test_get_application_not_found(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/applications/{uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Application stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_application_stats(db, sample_application):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/applications/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["submitted"] >= 1
    assert data["tier"] == "pro"
    assert data["monthly_limit"] == 50


@pytest.mark.asyncio
async def test_application_stats_no_profile(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/applications/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["tier"] == "free"
