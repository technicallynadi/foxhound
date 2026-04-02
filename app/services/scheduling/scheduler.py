"""Job scheduler: registers and manages recurring Foxhound jobs.

Ensures recurring jobs exist in the database on startup.
The existing worker_loop in run_service.py picks them up and executes them.

Recurring jobs:
- job_discovery: crawl all sources (every 12 hours)
- autopilot_apply: apply for autopilot users (daily at 10:00 UTC)
- daily_digest: send end-of-day summaries (daily at 20:00 UTC)
- stale_cleanup: expire old job listings (daily at 02:00 UTC)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.foxhound_job import FoxhoundJob
from app.db.session import async_session

logger = logging.getLogger(__name__)

RECURRING_JOBS = [
    {
        "job_type": "job_discovery",
        "origin": "scheduled",
        "priority": 30,
        "recurrence_interval_seconds": 43200,  # 12 hours
        "payload": {"sources": ["greenhouse", "lever", "ashby", "remotive", "hn_hiring"]},
    },
    {
        "job_type": "autopilot_apply",
        "origin": "scheduled",
        "priority": 40,
        "recurrence_interval_seconds": 86400,  # 24 hours
        "payload": {},
    },
    {
        "job_type": "daily_digest",
        "origin": "scheduled",
        "priority": 20,
        "recurrence_interval_seconds": 86400,
        "payload": {},
    },
    {
        "job_type": "stale_cleanup",
        "origin": "scheduled",
        "priority": 10,
        "recurrence_interval_seconds": 86400,
        "payload": {},
    },
    {
        "job_type": "watchdog_sweep",
        "origin": "scheduled",
        "priority": 15,
        "recurrence_interval_seconds": 86400,
        "payload": {"batch_size": 50, "max_concurrent": 3, "domain_delay_seconds": 5},
    },
]


async def ensure_recurring_jobs() -> None:
    """Ensure all recurring jobs exist in the database.

    Called once on startup. If a recurring job already exists and is
    queued or running, it's left alone. If it's completed or doesn't
    exist, a new one is created.
    """
    async with async_session() as db:
        for spec in RECURRING_JOBS:
            job_type = spec["job_type"]

            # Check if there's already an active job of this type
            result = await db.execute(
                select(FoxhoundJob)
                .where(
                    FoxhoundJob.job_type == job_type,
                    FoxhoundJob.recurring.is_(True),
                    FoxhoundJob.status.in_(["queued", "running"]),
                )
                .limit(1)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.info("Recurring job %s already active (id=%s)", job_type, existing.id)
                continue

            # Create new recurring job
            now = datetime.now(timezone.utc)
            job = FoxhoundJob(
                id=str(uuid4()),
                run_id=str(uuid4()),
                job_type=job_type,
                origin=spec["origin"],
                priority=spec["priority"],
                recurring=True,
                recurrence_interval_seconds=spec["recurrence_interval_seconds"],
                payload_json=json.dumps(spec["payload"]),
                status="queued",
                next_scheduled_at=now,
            )
            db.add(job)
            logger.info("Created recurring job: %s (id=%s)", job_type, job.id)

        await db.commit()


async def reschedule_completed_job(job: FoxhoundJob) -> FoxhoundJob | None:
    """After a recurring job completes, schedule the next occurrence.

    Called by the executor after successful completion.
    Returns the new job if created, None if not recurring.
    """
    if not job.recurring or not job.recurrence_interval_seconds:
        return None

    now = datetime.now(timezone.utc)
    next_at = now + timedelta(seconds=job.recurrence_interval_seconds)

    async with async_session() as db:
        new_job = FoxhoundJob(
            id=str(uuid4()),
            run_id=str(uuid4()),
            job_type=job.job_type,
            origin=job.origin,
            priority=job.priority,
            recurring=True,
            recurrence_interval_seconds=job.recurrence_interval_seconds,
            payload_json=job.payload_json,
            status="queued",
            next_scheduled_at=next_at,
        )
        db.add(new_job)
        await db.commit()
        logger.info("Rescheduled %s: next at %s (id=%s)", job.job_type, next_at, new_job.id)
        return new_job
