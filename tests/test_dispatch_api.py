"""Tests for Dispatch API (FOX-66)."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.foxhound_job import FoxhoundJob
from app.main import app


@pytest.fixture
async def sample_job(db, user_id):
    """Create a sample active job for the user."""
    job = FoxhoundJob(
        id=str(uuid4()),
        run_id=f"{user_id}_run_123",
        job_type="recon",
        status="running",
        priority=10,
        payload_json=json.dumps({"user_id": user_id, "run_id": f"{user_id}_run_123"}),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@pytest.fixture
async def pending_job(db, user_id):
    """Create a job awaiting approval."""
    job = FoxhoundJob(
        id=str(uuid4()),
        run_id=f"{user_id}_run_456",
        job_type="apply",
        status="awaiting_approval",
        priority=20,
        payload_json=json.dumps({"user_id": user_id}),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    # Note: approval_status column doesn't exist yet, but the API uses getattr(..., None)
    # We can't actually set it on the model yet if it's not in the ORM.
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@pytest.mark.asyncio
async def test_list_dispatch_jobs(db, sample_job, pending_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/dispatch/jobs")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2

    # Check if our sample job is in the list
    job_ids = [j["id"] for j in data]
    assert sample_job.id in job_ids
    assert pending_job.id in job_ids


@pytest.mark.asyncio
async def test_get_dispatch_job_detail(db, sample_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/dispatch/jobs/{sample_job.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sample_job.id
    assert data["job_type"] == "recon"
    assert data["status"] == "running"
    assert "payload_json" in data
    assert data["children"] == []  # Stub returns empty


@pytest.mark.asyncio
async def test_cancel_dispatch_job(db, sample_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/dispatch/jobs/{sample_job.id}/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"

    await db.refresh(sample_job)
    assert sample_job.status == "canceled"
    assert sample_job.canceled_at is not None


@pytest.mark.asyncio
async def test_get_dispatch_dag(db, sample_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/dispatch/dag/{sample_job.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sample_job.id
    assert data["children"] == []  # Stub returns empty


@pytest.mark.asyncio
async def test_approve_dispatch_job(db, pending_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/dispatch/jobs/{pending_job.id}/approve")

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"

    await db.refresh(pending_job)
    assert pending_job.status == "queued"


@pytest.mark.asyncio
async def test_deny_dispatch_job(db, pending_job, user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/dispatch/jobs/{pending_job.id}/deny")

    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"

    await db.refresh(pending_job)
    assert pending_job.status == "canceled"
    assert pending_job.canceled_at is not None


@pytest.mark.asyncio
async def test_dispatch_job_not_found(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/dispatch/jobs/{uuid4()}")
    assert resp.status_code == 404
