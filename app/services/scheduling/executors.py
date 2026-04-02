"""Job executors: the functions that run for each scheduled job type.

Each executor receives a FoxhoundJob and performs the work.
Called by _execute_job() in run_service.py.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.foxhound_job import FoxhoundJob
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.db.session import async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job Discovery
# ---------------------------------------------------------------------------


async def execute_job_discovery(job: FoxhoundJob) -> None:
    """Crawl all sources and score new jobs for all active users."""
    payload = json.loads(job.payload_json or "{}")
    sources = payload.get("sources", ["greenhouse", "lever", "ashby", "remotive", "hn_hiring"])

    from app.services.discovery.engine import JobDiscoveryEngine

    engine = JobDiscoveryEngine()

    async with async_session() as db:
        runs = await engine.run_discovery(db, source=None)  # All sources
        total_new = sum(getattr(r, "new_count", 0) for r in runs)
        logger.info("Discovery complete: %d runs, %d new jobs", len(runs), total_new)

        # Score new jobs for all active users
        if total_new > 0:
            from app.services.matching.scorer import MatchScorer

            scorer = MatchScorer()
            result = await db.execute(
                select(UserProfile.user_id).where(
                    UserProfile.tier != "free",
                    UserProfile.profile_complete == True,
                )
            )
            user_ids = [row[0] for row in result.all()]

            for uid in user_ids:
                try:
                    matches = await scorer.score_jobs_for_user(db, uid)
                    logger.info("Scored %d jobs for user %s", len(matches), uid)
                except Exception:
                    logger.exception("Scoring failed for user %s", uid)

            # Send new match alerts
            await _send_new_match_alerts(db, user_ids)

        await db.commit()


async def _send_new_match_alerts(db: AsyncSession, user_ids: list[str]) -> None:
    """Notify users about new matches above their threshold."""
    from app.services.apply.notifications import send_new_match_alert

    for uid in user_ids:
        try:
            profile_result = await db.execute(
                select(UserProfile).where(UserProfile.user_id == uid)
            )
            profile = profile_result.scalar_one_or_none()
            if not profile:
                continue

            threshold = profile.autopilot_threshold or 70

            # Get new unviewed matches above threshold (created today)
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            match_result = await db.execute(
                select(JobMatch, JobListing)
                .join(JobListing, JobMatch.job_id == JobListing.id)
                .where(
                    JobMatch.user_id == uid,
                    JobMatch.match_score >= threshold,
                    JobMatch.disqualified == False,
                    JobMatch.created_at >= today_start,
                )
                .order_by(JobMatch.match_score.desc())
                .limit(10)
            )
            new_matches = match_result.all()

            if new_matches:
                await send_new_match_alert(profile, new_matches)
                logger.info("Sent new match alert to user %s (%d matches)", uid, len(new_matches))
        except Exception:
            logger.exception("Match alert failed for user %s", uid)


# ---------------------------------------------------------------------------
# Autopilot Apply
# ---------------------------------------------------------------------------


async def execute_autopilot_apply(job: FoxhoundJob) -> None:
    """Apply to top matches for all autopilot users."""
    async with async_session() as db:
        # Get all autopilot users
        result = await db.execute(
            select(UserProfile).where(
                UserProfile.autopilot_enabled == True,
                UserProfile.applications_this_month < UserProfile.monthly_apply_limit,
            )
        )
        users = list(result.scalars().all())
        logger.info("Autopilot: %d eligible users", len(users))

        for profile in users:
            try:
                await _autopilot_for_user(db, profile)
            except Exception:
                logger.exception("Autopilot failed for user %s", profile.user_id)

        await db.commit()


async def _autopilot_for_user(db: AsyncSession, profile: UserProfile) -> None:
    """Apply to top matches for a single autopilot user."""
    # Check daily limit
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.user_id == profile.user_id,
            Application.created_at >= today_start,
        )
    )
    today_count = today_count_result.scalar() or 0
    remaining_today = max(0, profile.daily_apply_limit - today_count)

    if remaining_today == 0:
        logger.info("User %s: daily limit reached (%d)", profile.user_id, profile.daily_apply_limit)
        return

    # Get top unmatched jobs above threshold
    threshold = profile.autopilot_threshold or 70
    result = await db.execute(
        select(JobMatch)
        .where(
            JobMatch.user_id == profile.user_id,
            JobMatch.match_score >= threshold,
            JobMatch.disqualified == False,
            JobMatch.user_action == "none",
        )
        .order_by(JobMatch.match_score.desc())
        .limit(remaining_today)
    )
    matches = list(result.scalars().all())

    if not matches:
        logger.info("User %s: no matches above %d%%", profile.user_id, threshold)
        return

    # Check which jobs already have applications
    job_ids = [m.job_id for m in matches]
    existing_result = await db.execute(
        select(Application.job_id).where(
            Application.user_id == profile.user_id,
            Application.job_id.in_(job_ids),
            Application.status.notin_(["failed", "canceled"]),
        )
    )
    already_applied = {row[0] for row in existing_result.all()}

    # Filter to unapplied jobs
    to_apply = [m for m in matches if m.job_id not in already_applied]

    if not to_apply:
        logger.info("User %s: all matches already applied", profile.user_id)
        return

    # Smart pacing: check companies applied to today
    today_companies_result = await db.execute(
        select(JobListing.company)
        .join(Application, Application.job_id == JobListing.id)
        .where(Application.user_id == profile.user_id, Application.created_at >= today_start)
    )
    today_companies = {row[0].lower() for row in today_companies_result.all()}

    # Schedule applications with randomized delays
    scheduled = 0
    for match in to_apply:
        job = await db.get(JobListing, match.job_id)
        if not job:
            continue

        # Skip if already applied to this company today (smart pacing)
        if (job.company or "").lower() in today_companies:
            continue

        # Create a delayed single_apply job
        delay = random.randint(60, 28800)  # 1 min to 8 hours spread
        scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

        apply_job = FoxhoundJob(
            id=str(uuid4()),
            run_id=str(uuid4()),
            job_type="single_apply",
            origin="autopilot",
            priority=50,
            payload_json=json.dumps({
                "user_id": profile.user_id,
                "job_id": match.job_id,
                "trigger": "autopilot",
            }),
            status="queued",
            next_scheduled_at=scheduled_at,
        )
        db.add(apply_job)
        today_companies.add((job.company or "").lower())
        scheduled += 1

    logger.info("User %s: scheduled %d autopilot applications", profile.user_id, scheduled)


# ---------------------------------------------------------------------------
# Single Apply (created by autopilot, executed by worker)
# ---------------------------------------------------------------------------


async def execute_single_apply(job: FoxhoundJob) -> None:
    """Execute a single application (used by autopilot)."""
    payload = json.loads(job.payload_json or "{}")
    user_id = payload["user_id"]
    job_id = payload["job_id"]
    trigger = payload.get("trigger", "autopilot")

    from app.services.apply.orchestrator import ApplicationOrchestrator

    orchestrator = ApplicationOrchestrator()

    async with async_session() as db:
        try:
            application = await orchestrator.apply(
                db=db, user_id=user_id, job_id=job_id, trigger=trigger,
            )
            logger.info(
                "Autopilot apply: user=%s job=%s status=%s",
                user_id, job_id, application.status,
            )
        except ValueError as e:
            logger.warning("Autopilot apply failed: %s", e)


# ---------------------------------------------------------------------------
# Daily Digest
# ---------------------------------------------------------------------------


async def execute_daily_digest(job: FoxhoundJob) -> None:
    """Send daily digest to all subscribed users."""
    from app.services.apply.notifications import send_daily_digest

    async with async_session() as db:
        result = await db.execute(
            select(UserProfile.user_id).where(
                UserProfile.notify_daily_digest == True,
            )
        )
        user_ids = [row[0] for row in result.all()]
        logger.info("Sending daily digest to %d users", len(user_ids))

        for uid in user_ids:
            try:
                await send_daily_digest(db, uid)
            except Exception:
                logger.exception("Digest failed for user %s", uid)


# ---------------------------------------------------------------------------
# Stale Job Cleanup
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Follow-up Check (day 3, 7, 14 after application)
# ---------------------------------------------------------------------------


async def execute_followup(job: FoxhoundJob) -> None:
    """Send a follow-up notification for an application at day 3, 7, or 14."""
    payload = json.loads(job.payload_json or "{}")
    user_id = payload["user_id"]
    application_id = payload["application_id"]
    job_id = payload["job_id"]
    day = payload["day"]

    from app.services.apply.notifications import (
        send_followup_day3,
        send_followup_day7,
        send_followup_day14,
    )

    async with async_session() as db:
        # Get profile and job
        profile_result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            logger.warning("Follow-up: no profile for user %s", user_id)
            return

        job_listing = await db.get(JobListing, job_id)
        if not job_listing:
            logger.warning("Follow-up: job %s not found", job_id)
            return

        application = await db.get(Application, application_id)
        if not application or application.status not in ("submitted", "confirmed"):
            logger.info("Follow-up: skipping (status=%s)", application.status if application else "missing")
            return

        # Send the appropriate follow-up
        if day == 3 and not application.followup_day3_sent:
            await send_followup_day3(profile, job_listing)
            application.followup_day3_sent = True
        elif day == 7 and not application.followup_day7_sent:
            await send_followup_day7(profile, job_listing)
            application.followup_day7_sent = True
        elif day == 14 and not application.followup_day14_sent:
            await send_followup_day14(profile, job_listing)
            application.followup_day14_sent = True

        await db.commit()
        from app.services.activity.logger import log_activity

        await log_activity(
            user_id=user_id,
            event_type="followup_reminder",
            title=f"Follow-up reminder: {job_listing.company}",
            description=f"Foxhound queued the day {day} follow-up for {job_listing.title}.",
            metadata={
                "application_id": application_id,
                "job_id": job_id,
                "company": job_listing.company,
                "title": job_listing.title,
                "day": day,
            },
        )
        logger.info("Follow-up day %d sent for application %s", day, application_id)


# ---------------------------------------------------------------------------
# Stale Job Cleanup
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Watchdog Sweep
# ---------------------------------------------------------------------------


async def execute_watchdog_sweep(job: FoxhoundJob) -> None:
    """Check all active application postings for changes."""
    payload = json.loads(job.payload_json or "{}")
    max_concurrent = payload.get("max_concurrent", 3)
    domain_delay = payload.get("domain_delay_seconds", 5)

    from app.services.watchdog.sweep import run_watchdog_sweep

    await run_watchdog_sweep(
        max_concurrent=max_concurrent,
        domain_delay_seconds=domain_delay,
    )


# ---------------------------------------------------------------------------
# Stale Job Cleanup
# ---------------------------------------------------------------------------


async def execute_stale_cleanup(job: FoxhoundJob) -> None:
    """Expire job listings older than 30 days and clean up matches."""
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        # Find stale jobs
        result = await db.execute(
            select(JobListing).where(
                JobListing.status == "active",
                JobListing.posted_at < cutoff,
                JobListing.expires_at.is_(None),
            )
        )
        stale_jobs = list(result.scalars().all())

        expired_count = 0
        for jl in stale_jobs:
            jl.status = "expired"
            expired_count += 1

        # Remove matches for expired jobs
        if stale_jobs:
            stale_ids = [j.id for j in stale_jobs]
            from sqlalchemy import update
            await db.execute(
                update(JobMatch)
                .where(JobMatch.job_id.in_(stale_ids))
                .values(disqualified=True, disqualify_reason="job_expired")
            )

        await db.commit()
        logger.info("Stale cleanup: expired %d jobs", expired_count)
