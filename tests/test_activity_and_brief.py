"""Tests for activity logging, brief model, and the activity/brief APIs."""

import json
from datetime import UTC
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.foxhound_brief import FoxhoundBrief
from app.main import app

# ---------------------------------------------------------------------------
# Activity logger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_activity(db):
    from app.services.activity.logger import log_activity

    activity = await log_activity(
        user_id="test-user",
        event_type="application_submitted",
        title="Applied to Stripe",
        description="Submitted via API",
        metadata={"company": "Stripe", "match_score": 91},
    )
    assert activity is not None
    assert activity.event_type == "application_submitted"
    assert activity.title == "Applied to Stripe"
    assert json.loads(activity.metadata_json)["company"] == "Stripe"


@pytest.mark.asyncio
async def test_log_activity_minimal(db):
    from app.services.activity.logger import log_activity

    activity = await log_activity(
        user_id="test-user",
        event_type="scan_completed",
        title="Scan done",
    )
    assert activity is not None
    assert activity.description is None
    assert activity.metadata_json is None


# ---------------------------------------------------------------------------
# FoxhoundBrief model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foxhound_brief_creation(db):
    brief = FoxhoundBrief(
        id=str(uuid4()),
        user_id="test-user",
        application_id=str(uuid4()),
        status="assembling",
    )
    db.add(brief)
    await db.commit()

    from sqlalchemy import select

    result = await db.execute(select(FoxhoundBrief).where(FoxhoundBrief.user_id == "test-user"))
    loaded = result.scalar_one()
    assert loaded.status == "assembling"
    assert loaded.company_brief_json is None
    assert loaded.pathfinder_json is None


@pytest.mark.asyncio
async def test_brief_assembler(db):
    from app.services.research.brief_assembler import assemble_brief

    app_id = str(uuid4())
    brief = await assemble_brief(
        user_id="test-user",
        application_id=app_id,
        data={
            "company_brief": {"summary": "Great company", "tech_stack": ["Python"]},
            "pathfinder": {"search_urls": {"linkedin": "https://linkedin.com/search"}},
        },
    )
    assert brief is not None
    assert brief.status == "ready"  # Both required sections present
    assert json.loads(brief.company_brief_json)["summary"] == "Great company"


@pytest.mark.asyncio
async def test_brief_assembler_partial(db):
    from app.services.research.brief_assembler import assemble_brief

    brief = await assemble_brief(
        user_id="test-user",
        application_id=str(uuid4()),
        data={
            "company_brief": {"summary": "Some data"},
            # No pathfinder — partial
        },
    )
    assert brief is not None
    assert brief.status == "partial"


# ---------------------------------------------------------------------------
# Activity API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_feed_empty(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert data["total"] >= 0


@pytest.mark.asyncio
async def test_activity_briefing(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/activity/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "applications" in data
    assert "alerts" in data
    assert "new_matches" in data


@pytest.mark.asyncio
async def test_activity_stats(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/activity/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_matches" in data
    assert "autopilot_enabled" in data


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


def test_rate_limit_creates_dependency():
    from app.api.rate_limit import rate_limit

    dep = rate_limit("test_scope", 5, 60)
    assert callable(dep)


# ---------------------------------------------------------------------------
# Claim next job respects scheduling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_next_job_respects_scheduled_time(db):
    """Jobs with future next_scheduled_at should NOT be claimed."""
    from datetime import datetime, timedelta
    from uuid import uuid4

    from app.db.models.foxhound_job import FoxhoundJob

    # Create a job scheduled 1 hour in the future
    future_job = FoxhoundJob(
        id=str(uuid4()),
        run_id=str(uuid4()),
        job_type="single_apply",
        origin="autopilot",
        priority=50,
        payload_json=json.dumps({"user_id": "test", "job_id": "test"}),
        status="queued",
        next_scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(future_job)
    await db.commit()

    from app.services.run_service import claim_next_job

    result = await claim_next_job("test-worker")

    # Should NOT claim the future-scheduled job
    if result is not None:
        claimed_id = result[0]
        assert claimed_id != future_job.id, "Should not claim a job scheduled in the future"
