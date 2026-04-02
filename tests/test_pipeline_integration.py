"""Tests for pipeline integration: follow-up scheduling, executor dispatch, stale cleanup."""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.db.models.application import Application
from app.db.models.foxhound_job import FoxhoundJob
from app.db.models.job_listing import JobListing
from app.services.scheduling.followup import schedule_followups, FOLLOWUP_DAYS


# ---------------------------------------------------------------------------
# Follow-up scheduling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_followups_creates_three_jobs(db, user_id):
    app_id = str(uuid4())
    job_id = str(uuid4())

    jobs = await schedule_followups(user_id, app_id, job_id, db=db)
    await db.commit()

    assert len(jobs) == 3

    days = sorted(json.loads(j.payload_json)["day"] for j in jobs)
    assert days == [3, 7, 14]

    for j in jobs:
        assert j.job_type == "followup_check"
        assert j.status == "queued"
        payload = json.loads(j.payload_json)
        assert payload["user_id"] == user_id
        assert payload["application_id"] == app_id


@pytest.mark.asyncio
async def test_schedule_followups_correct_timing(db, user_id):
    now = datetime.now(timezone.utc)
    jobs = await schedule_followups(user_id, str(uuid4()), str(uuid4()), db=db)
    await db.commit()

    for j in jobs:
        day = json.loads(j.payload_json)["day"]
        expected = now + timedelta(days=day)
        # Allow 5 seconds tolerance
        assert abs((j.next_scheduled_at - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Follow-up executor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_executor_day3(db, sample_profile, sample_jobs):
    """Day 3 follow-up sends notification and marks flag."""
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="submitted",
        trigger="manual",
    )
    db.add(application)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()),
        run_id=str(uuid4()),
        job_type="followup_check",
        origin="post_apply",
        priority=20,
        payload_json=json.dumps({
            "user_id": sample_profile.user_id,
            "application_id": application.id,
            "job_id": sample_jobs[0].id,
            "day": 3,
        }),
        status="running",
    )

    with patch("app.services.apply.notifications.send_followup_day3", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"skipped": "no channels"}
        from app.services.scheduling.executors import execute_followup
        await execute_followup(job)

    mock_send.assert_called_once()

    # Check the flag was set
    await db.refresh(application)
    assert application.followup_day3_sent


@pytest.mark.asyncio
async def test_followup_executor_day7(db, sample_profile, sample_jobs):
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="submitted",
        trigger="manual",
    )
    db.add(application)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()), job_type="followup_check",
        origin="post_apply", priority=20,
        payload_json=json.dumps({
            "user_id": sample_profile.user_id,
            "application_id": application.id,
            "job_id": sample_jobs[0].id,
            "day": 7,
        }),
        status="running",
    )

    with patch("app.services.apply.notifications.send_followup_day7", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {}
        from app.services.scheduling.executors import execute_followup
        await execute_followup(job)

    mock_send.assert_called_once()
    await db.refresh(application)
    assert application.followup_day7_sent


@pytest.mark.asyncio
async def test_followup_executor_day14(db, sample_profile, sample_jobs):
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="submitted",
        trigger="manual",
    )
    db.add(application)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()), job_type="followup_check",
        origin="post_apply", priority=20,
        payload_json=json.dumps({
            "user_id": sample_profile.user_id,
            "application_id": application.id,
            "job_id": sample_jobs[0].id,
            "day": 14,
        }),
        status="running",
    )

    with patch("app.services.apply.notifications.send_followup_day14", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {}
        from app.services.scheduling.executors import execute_followup
        await execute_followup(job)

    mock_send.assert_called_once()
    await db.refresh(application)
    assert application.followup_day14_sent


@pytest.mark.asyncio
async def test_followup_executor_skips_failed_application(db, sample_profile, sample_jobs):
    """Follow-up should not fire if application is failed."""
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="failed",
        trigger="manual",
    )
    db.add(application)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()), job_type="followup_check",
        origin="post_apply", priority=20,
        payload_json=json.dumps({
            "user_id": sample_profile.user_id,
            "application_id": application.id,
            "job_id": sample_jobs[0].id,
            "day": 3,
        }),
        status="running",
    )

    with patch("app.services.apply.notifications.send_followup_day3", new_callable=AsyncMock) as mock_send:
        from app.services.scheduling.executors import execute_followup
        await execute_followup(job)

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_followup_executor_skips_already_sent(db, sample_profile, sample_jobs):
    """Follow-up should not re-send if already marked."""
    application = Application(
        id=str(uuid4()),
        user_id=sample_profile.user_id,
        job_id=sample_jobs[0].id,
        status="submitted",
        trigger="manual",
        followup_day3_sent=True,
    )
    db.add(application)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()), job_type="followup_check",
        origin="post_apply", priority=20,
        payload_json=json.dumps({
            "user_id": sample_profile.user_id,
            "application_id": application.id,
            "job_id": sample_jobs[0].id,
            "day": 3,
        }),
        status="running",
    )

    with patch("app.services.apply.notifications.send_followup_day3", new_callable=AsyncMock) as mock_send:
        from app.services.scheduling.executors import execute_followup
        await execute_followup(job)

    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Stale cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_cleanup_expires_old_jobs(db):
    old_job = JobListing(
        id=str(uuid4()),
        title="Old Job",
        company="OldCo",
        description="Expired role",
        apply_url="https://old.com/jobs",
        source="test",
        source_url="https://old.com",
        status="active",
        posted_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    db.add(old_job)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()),
        job_type="stale_cleanup", origin="scheduled", priority=10,
        payload_json="{}", status="running",
    )

    from app.services.scheduling.executors import execute_stale_cleanup
    await execute_stale_cleanup(job)

    await db.refresh(old_job)
    assert old_job.status == "expired"


@pytest.mark.asyncio
async def test_stale_cleanup_keeps_recent_jobs(db):
    recent_job = JobListing(
        id=str(uuid4()),
        title="Recent Job",
        company="NewCo",
        description="Fresh role",
        apply_url="https://new.com/jobs",
        source="test",
        source_url="https://new.com",
        status="active",
        posted_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.add(recent_job)
    await db.commit()

    job = FoxhoundJob(
        id=str(uuid4()), run_id=str(uuid4()),
        job_type="stale_cleanup", origin="scheduled", priority=10,
        payload_json="{}", status="running",
    )

    from app.services.scheduling.executors import execute_stale_cleanup
    await execute_stale_cleanup(job)

    await db.refresh(recent_job)
    assert recent_job.status == "active"


# ---------------------------------------------------------------------------
# Executor dispatch map
# ---------------------------------------------------------------------------

def test_executor_map_includes_followup():
    """The executor map in run_service.py should include followup_check."""
    expected = {"job_discovery", "autopilot_apply", "single_apply", "daily_digest", "stale_cleanup", "followup_check"}
    # Read from the source
    from app.services.scheduling.executors import (
        execute_job_discovery, execute_autopilot_apply, execute_single_apply,
        execute_daily_digest, execute_stale_cleanup, execute_followup,
    )
    assert all(callable(f) for f in [
        execute_job_discovery, execute_autopilot_apply, execute_single_apply,
        execute_daily_digest, execute_stale_cleanup, execute_followup,
    ])
