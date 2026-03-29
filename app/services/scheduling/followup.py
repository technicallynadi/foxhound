"""Follow-up scheduling: create day 3/7/14 follow-up jobs after application submission."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.foxhound_job import FoxhoundJob

logger = logging.getLogger(__name__)

FOLLOWUP_DAYS = [3, 7, 14]


async def schedule_followups(
    db: AsyncSession, user_id: str, application_id: str, job_id: str
) -> list[FoxhoundJob]:
    """Schedule follow-up check jobs at day 3, 7, and 14 after application submission."""
    now = datetime.now(timezone.utc)
    jobs = []

    for day in FOLLOWUP_DAYS:
        scheduled_at = now + timedelta(days=day)
        followup_job = FoxhoundJob(
            id=str(uuid4()),
            run_id=str(uuid4()),
            job_type="followup_check",
            origin="post_apply",
            priority=20,
            payload_json=json.dumps({
                "user_id": user_id,
                "application_id": application_id,
                "job_id": job_id,
                "day": day,
            }),
            status="queued",
            next_scheduled_at=scheduled_at,
        )
        db.add(followup_job)
        jobs.append(followup_job)

    await db.flush()
    logger.info(
        "Scheduled %d follow-up jobs for application %s (days %s)",
        len(jobs), application_id, FOLLOWUP_DAYS,
    )
    return jobs
