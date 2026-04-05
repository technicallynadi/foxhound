"""Follow-up scheduling: create day 3/7/14 follow-up jobs after application submission."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.foxhound_job import FoxhoundJob
from app.db.session import async_session

logger = logging.getLogger(__name__)

FOLLOWUP_DAYS = [3, 7, 14]


async def schedule_followups(
    user_id: str,
    application_id: str,
    job_id: str,
    db: AsyncSession | None = None,
) -> list[FoxhoundJob]:
    """Schedule follow-up check jobs at day 3, 7, and 14 after application submission.

    Can be called with an existing db session or without (creates its own).
    """
    now = datetime.now(UTC)
    jobs = []

    async def _create(session: AsyncSession) -> None:
        for day in FOLLOWUP_DAYS:
            followup_job = FoxhoundJob(
                id=str(uuid4()),
                run_id=str(uuid4()),
                job_type="followup_check",
                origin="post_apply",
                priority=20,
                payload_json=json.dumps(
                    {
                        "user_id": user_id,
                        "application_id": application_id,
                        "job_id": job_id,
                        "day": day,
                    }
                ),
                status="queued",
                next_scheduled_at=now + timedelta(days=day),
            )
            session.add(followup_job)
            jobs.append(followup_job)

    if db:
        await _create(db)
        await db.flush()
    else:
        async with async_session() as session:
            await _create(session)
            await session.commit()

    logger.info(
        "Scheduled %d follow-up jobs for application %s (days %s)",
        len(jobs),
        application_id,
        FOLLOWUP_DAYS,
    )
    from app.services.activity.logger import log_activity

    await log_activity(
        user_id=user_id,
        event_type="followup_scheduled",
        title="Follow-ups scheduled",
        description="Foxhound queued follow-up checkpoints for day 3, 7, and 14.",
        metadata={
            "application_id": application_id,
            "job_id": job_id,
            "days": FOLLOWUP_DAYS,
        },
    )
    return jobs
