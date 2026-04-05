"""Activity feed API — powers the dashboard command center."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_activity import AgentActivity
from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


@router.get("")
async def get_activity_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    event_type: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated activity feed for the dashboard."""
    user_id = user["user_id"]
    offset = (page - 1) * page_size

    stmt = (
        select(AgentActivity)
        .where(AgentActivity.user_id == user_id)
        .order_by(AgentActivity.created_at.desc())
    )
    # Hide internal cache events from the feed
    if not event_type:
        stmt = stmt.where(~AgentActivity.event_type.like("\\_%", escape="\\"))
    else:
        stmt = stmt.where(AgentActivity.event_type == event_type)

    result = await db.execute(stmt.offset(offset).limit(page_size))
    events = result.scalars().all()

    count_result = await db.execute(
        select(func.count(AgentActivity.id)).where(AgentActivity.user_id == user_id)
    )
    total = count_result.scalar() or 0

    return {
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "title": e.title,
                "description": e.description,
                "timestamp": e.created_at.isoformat() if e.created_at else None,
                "metadata": json.loads(e.metadata_json) if e.metadata_json else None,
            }
            for e in events
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": offset + page_size < total,
    }


@router.get("/briefing")
async def get_morning_briefing(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Morning briefing — aggregates overnight agent activity."""
    user_id = user["user_id"]

    # Get the start of today (UTC)
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Profile for threshold
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    threshold = profile.autopilot_threshold if profile else 70

    # Today's applications
    app_result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id, Application.created_at >= today_start)
        .order_by(Application.created_at.desc())
    )
    todays_apps = app_result.all()

    applications = []
    for app, job in todays_apps:
        # Get match score
        match_result = await db.execute(
            select(JobMatch.match_score).where(
                JobMatch.user_id == user_id, JobMatch.job_id == job.id
            )
        )
        score = match_result.scalar_one_or_none()

        # Check if brief exists
        from app.db.models.foxhound_brief import FoxhoundBrief
        brief_result = await db.execute(
            select(FoxhoundBrief.id, FoxhoundBrief.status).where(
                FoxhoundBrief.application_id == app.id
            )
        )
        brief_row = brief_result.first()

        applications.append({
            "application_id": app.id,
            "company": job.company,
            "title": job.title,
            "match_score": score,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "status": app.status,
            "brief_ready": brief_row[1] in ("ready", "partial") if brief_row else False,
            "brief_id": brief_row[0] if brief_row else None,
        })

    # Today's alerts (from activity log)
    alert_types = {"ghost_alert", "followup_reminder", "followup_sent", "watchdog_check"}
    alert_result = await db.execute(
        select(AgentActivity)
        .where(
            AgentActivity.user_id == user_id,
            AgentActivity.event_type.in_(alert_types),
            AgentActivity.created_at >= today_start,
        )
        .order_by(AgentActivity.created_at.desc())
        .limit(10)
    )
    alerts = [
        {
            "type": a.event_type,
            "title": a.title,
            "description": a.description,
            "metadata": json.loads(a.metadata_json) if a.metadata_json else None,
        }
        for a in alert_result.scalars()
    ]

    # New matches above threshold (today)
    match_result = await db.execute(
        select(JobMatch, JobListing)
        .join(JobListing, JobMatch.job_id == JobListing.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.match_score >= threshold,
            JobMatch.disqualified is False,
            JobMatch.user_action == "none",
            JobMatch.created_at >= today_start,
        )
        .order_by(JobMatch.match_score.desc())
        .limit(10)
    )
    new_matches = [
        {
            "match_id": m.id,
            "job_id": m.job_id,
            "company": j.company,
            "title": j.title,
            "match_score": m.match_score,
        }
        for m, j in match_result.all()
    ]

    # Count total discovered today
    discovered_result = await db.execute(
        select(func.count(JobListing.id)).where(
            JobListing.discovered_at >= today_start
        )
    )
    jobs_discovered = discovered_result.scalar() or 0

    # Count pending questions
    from app.db.models.application_question import ApplicationQuestion
    pending_q_result = await db.execute(
        select(func.count(ApplicationQuestion.id))
        .join(Application, ApplicationQuestion.application_id == Application.id)
        .where(Application.user_id == user_id, ApplicationQuestion.status == "pending")
    )
    questions_pending = pending_q_result.scalar() or 0

    return {
        "generated_at": now.isoformat(),
        "period_start": today_start.isoformat(),
        "summary": {
            "jobs_discovered": jobs_discovered,
            "matches_above_threshold": len(new_matches),
            "applications_submitted": len([a for a in applications if a["status"] == "submitted"]),
            "alerts_count": len(alerts),
            "questions_pending": questions_pending,
        },
        "applications": applications,
        "alerts": alerts,
        "new_matches": new_matches,
    }


@router.get("/stats")
async def get_dashboard_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compact stats for the summary bar."""
    user_id = user["user_id"]

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    match_count = await db.execute(
        select(func.count(JobMatch.id)).where(
            JobMatch.user_id == user_id, JobMatch.disqualified is False
        )
    )
    app_count = await db.execute(
        select(func.count(Application.id)).where(Application.user_id == user_id)
    )

    return {
        "total_matches": match_count.scalar() or 0,
        "total_applications": app_count.scalar() or 0,
        "autopilot_enabled": profile.autopilot_enabled if profile else False,
        "autopilot_threshold": profile.autopilot_threshold if profile else 70,
        "applications_this_month": profile.applications_this_month if profile else 0,
        "monthly_limit": profile.monthly_apply_limit if profile else 0,
    }
