"""Background loop that expires stale applications waiting for user input.

Started in the FastAPI lifespan. Runs every 60 seconds.
- Expires applications in waiting_user_input > 2 hours → mark failed
- Applications stuck in scanning/in_progress > 5 min → mark failed
- Notifies user on expiry
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.db.session import async_session

logger = logging.getLogger(__name__)


async def application_timeout_loop() -> None:
    """Background loop — call once from lifespan, runs forever."""
    cycle = 0
    while True:
        await asyncio.sleep(60)
        cycle += 1
        try:
            async with async_session() as db:
                await _check_expired_waiting(db)
                await _check_stuck_applications(db)
                # Check follow-ups every 30 minutes (not every 60 seconds)
                if cycle % 30 == 0:
                    await _check_followups(db)
                await db.commit()
        except Exception:
            logger.exception("Error in application timeout loop")


async def _check_expired_waiting(db: AsyncSession) -> None:
    """Expire applications waiting for user input > 2 hours."""
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)

    result = await db.execute(
        select(Application)
        .where(Application.status == "waiting_user_input")
        .where(Application.updated_at < two_hours_ago)
    )

    for app in result.scalars():
        app.status = "failed"
        app.error_type = "input_expired"
        app.error_message = "No response within 2 hours"
        logger.info("Expired waiting application %s", app.id)

        try:
            await _send_expiry_notice(db, app)
        except Exception:
            logger.exception("Failed to send expiry notice for app %s", app.id)


async def _check_stuck_applications(db: AsyncSession) -> None:
    """Fail applications stuck in transient states > 5 minutes."""
    now = datetime.now(timezone.utc)
    five_min_ago = now - timedelta(minutes=5)

    result = await db.execute(
        select(Application)
        .where(Application.status.in_(["scanning", "in_progress"]))
        .where(Application.updated_at < five_min_ago)
    )

    for app in result.scalars():
        app.status = "failed"
        app.error_type = "stuck_timeout"
        app.error_message = f"Application stuck in {app.status} for >5 minutes"
        logger.warning("Timed out stuck application %s (was %s)", app.id, app.status)


async def _send_expiry_notice(db: AsyncSession, app: Application) -> None:
    """Notify user their application expired."""
    from app.services.apply.notifications import _get_user_channels
    from app.services.notification_service import _post_webhook

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == app.user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        return

    job = await db.get(JobListing, app.job_id)
    company = job.company if job else "Unknown"
    title = job.title if job else "Unknown"

    channels = _get_user_channels(profile)
    message = (
        f"Foxhound: Your application to {company} -- {title} "
        f"has expired (no response within 2 hours). "
        f"You can re-apply from your dashboard."
    )

    for channel, webhook_url in channels.items():
        await _post_webhook(webhook_url, {"text": message})


async def _check_followups(db: AsyncSession) -> None:
    """Send follow-up messages at day 3, 7, 14 post-submission."""
    from app.services.apply.notifications import (
        send_followup_day3,
        send_followup_day7,
        send_followup_day14,
    )

    now = datetime.now(timezone.utc)

    # Day 3
    day3_cutoff = now - timedelta(days=3)
    day3_result = await db.execute(
        select(Application, JobListing, UserProfile)
        .join(JobListing, Application.job_id == JobListing.id)
        .join(UserProfile, Application.user_id == UserProfile.user_id)
        .where(
            Application.status == "submitted",
            Application.followup_day3_sent == False,
            Application.submitted_at <= day3_cutoff,
        )
        .limit(50)
    )
    for app, job, profile in day3_result.all():
        try:
            await send_followup_day3(profile, job)
            app.followup_day3_sent = True
            logger.info("Sent day-3 followup for app %s (%s)", app.id, job.company)
        except Exception:
            logger.exception("Day-3 followup failed for app %s", app.id)

    # Day 7
    day7_cutoff = now - timedelta(days=7)
    day7_result = await db.execute(
        select(Application, JobListing, UserProfile)
        .join(JobListing, Application.job_id == JobListing.id)
        .join(UserProfile, Application.user_id == UserProfile.user_id)
        .where(
            Application.status == "submitted",
            Application.followup_day7_sent == False,
            Application.submitted_at <= day7_cutoff,
        )
        .limit(50)
    )
    for app, job, profile in day7_result.all():
        try:
            await send_followup_day7(profile, job)
            app.followup_day7_sent = True
            logger.info("Sent day-7 followup for app %s (%s)", app.id, job.company)
        except Exception:
            logger.exception("Day-7 followup failed for app %s", app.id)

    # Day 14
    day14_cutoff = now - timedelta(days=14)
    day14_result = await db.execute(
        select(Application, JobListing, UserProfile)
        .join(JobListing, Application.job_id == JobListing.id)
        .join(UserProfile, Application.user_id == UserProfile.user_id)
        .where(
            Application.status == "submitted",
            Application.followup_day14_sent == False,
            Application.submitted_at <= day14_cutoff,
        )
        .limit(50)
    )
    for app, job, profile in day14_result.all():
        try:
            await send_followup_day14(profile, job)
            app.followup_day14_sent = True
            logger.info("Sent day-14 followup for app %s (%s)", app.id, job.company)
        except Exception:
            logger.exception("Day-14 followup failed for app %s", app.id)
