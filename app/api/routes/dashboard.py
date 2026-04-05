"""Dashboard API routes.

GET /api/v1/dashboard          — aggregated stats in one call
GET /api/v1/dashboard/activity — paginated activity feed
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated dashboard data in one call."""
    user_id = user["user_id"]
    # Profile summary
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()
    if not profile:
        return {"error": "no_profile", "message": "Upload your resume to get started."}

    profile_summary = {
        "name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "tier": profile.tier,
        "applications_this_month": profile.applications_this_month,
        "monthly_limit": profile.monthly_apply_limit,
        "autopilot_enabled": bool(profile.autopilot_enabled),
        "profile_complete": bool(profile.profile_complete),
        "resume_filename": profile.resume_filename,
    }

    # Application stats
    app_stats_result = await db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    )
    app_stats = {row[0]: row[1] for row in app_stats_result.all()}
    total_apps = sum(app_stats.values())

    # Recent applications (last 5)
    recent_result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .limit(5)
    )
    recent_apps = [
        {
            "application_id": app.id,
            "company": job.company,
            "title": job.title,
            "status": app.status,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        }
        for app, job in recent_result.all()
    ]

    # Match count (only jobs scoring above 30%)
    match_count_result = await db.execute(
        select(func.count(JobMatch.id)).where(
            JobMatch.user_id == user_id,
            JobMatch.disqualified.is_(False),
            JobMatch.match_score >= 65,
            JobMatch.user_action != "dismissed",
        )
    )
    match_count = match_count_result.scalar() or 0

    # Top match score
    top_match_result = await db.execute(
        select(func.max(JobMatch.match_score)).where(
            JobMatch.user_id == user_id,
            JobMatch.disqualified.is_(False),
        )
    )
    top_match = top_match_result.scalar()

    # Pending questions count
    from app.db.models.application_question import ApplicationQuestion

    pending_q_result = await db.execute(
        select(func.count(ApplicationQuestion.id))
        .join(Application, ApplicationQuestion.application_id == Application.id)
        .where(
            Application.user_id == user_id,
            ApplicationQuestion.status == "pending",
        )
    )
    pending_questions = pending_q_result.scalar() or 0

    return {
        "profile": profile_summary,
        "applications": {
            "total": total_apps,
            "by_status": app_stats,
            "recent": recent_apps,
        },
        "matches": {
            "total": match_count,
            "top_score": top_match,
        },
        "pending_questions": pending_questions,
    }


@router.get("/activity")
async def get_activity(
    user: dict = Depends(get_current_user),
    page: int = 1,
    per_page: int = 20,
    type_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated activity feed."""
    user_id = user["user_id"]
    offset = (page - 1) * per_page
    limit = min(per_page, 50)

    stmt = (
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
    )

    if type_filter:
        stmt = stmt.where(Application.status == type_filter)

    stmt = stmt.order_by(Application.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)

    items = [
        {
            "type": "application",
            "application_id": app.id,
            "company": job.company,
            "title": job.title,
            "status": app.status,
            "trigger": app.trigger,
            "error": app.error_type,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "has_screenshot": bool(app.screenshot_storage_path),
        }
        for app, job in result.all()
    ]

    # Total count for pagination
    count_stmt = select(func.count(Application.id)).where(Application.user_id == user_id)
    if type_filter:
        count_stmt = count_stmt.where(Application.status == type_filter)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    return {
        "items": items,
        "page": page,
        "per_page": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit if limit else 0,
    }
