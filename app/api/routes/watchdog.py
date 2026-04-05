"""Watchdog API endpoints.

POST /api/v1/watchdog/check/{application_id}  -- manually trigger a check
GET  /api/v1/watchdog/status                  -- summary of all watched applications
GET  /api/v1/watchdog/checks/{application_id} -- check history for one application
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.watchdog_check import WatchdogCheck
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/watchdog", tags=["watchdog"])


# ---------------------------------------------------------------------------
# POST /check/{application_id} -- manual trigger
# ---------------------------------------------------------------------------


@router.post("/check/{application_id}")
async def trigger_manual_check(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a watchdog check for one application.

    Rate-limited: max 1 manual check per application per hour.
    """
    user_id = user["user_id"]

    application = await db.get(Application, application_id)
    if not application or application.user_id != user_id:
        raise HTTPException(status_code=404, detail="Application not found")

    job = await db.get(JobListing, application.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job listing not found")

    # Rate limit: 1 manual check per hour
    if application.last_watchdog_check_at:
        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        if application.last_watchdog_check_at > one_hour_ago:
            raise HTTPException(
                status_code=429,
                detail="Check already ran recently. Try again in an hour.",
            )

    # Run the check (lazy import to avoid tinyfish at module level)
    from app.services.watchdog.checker import check_application

    outcome = await check_application(
        application, job, triggered_by="manual"
    )

    # Fetch the latest check record
    check_result = await db.execute(
        select(WatchdogCheck)
        .where(WatchdogCheck.application_id == application_id)
        .order_by(WatchdogCheck.created_at.desc())
        .limit(1)
    )
    check = check_result.scalar_one_or_none()

    return {
        "posting_status": outcome.get("status"),
        "changed": outcome.get("changed", False),
        "check": {
            "id": check.id,
            "status": check.check_status,
            "diff_summary": check.diff_summary,
            "duration_ms": check.check_duration_ms,
        }
        if check
        else None,
    }


# ---------------------------------------------------------------------------
# GET /status -- summary of all watched applications
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_watchdog_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all applications with their current watchdog monitoring data.

    Used by the Kanban board to render cards with posting status badges.
    """
    user_id = user["user_id"]

    result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
    )
    rows = result.all()

    return [
        {
            "id": app.id,
            "company": job.company,
            "title": job.title,
            "apply_url": job.apply_url,
            "status": app.status,
            "posting_status": app.posting_status,
            "posting_diff_summary": app.posting_diff_summary,
            "watchdog_enabled": app.watchdog_enabled,
            "days_since_applied": _days_since(app),
            "last_check_at": (
                app.last_watchdog_check_at.isoformat()
                if app.last_watchdog_check_at
                else None
            ),
            "submitted_at": (
                app.submitted_at.isoformat() if app.submitted_at else None
            ),
            "created_at": app.created_at.isoformat(),
        }
        for app, job in rows
    ]


# ---------------------------------------------------------------------------
# GET /checks/{application_id} -- check history
# ---------------------------------------------------------------------------


@router.get("/checks/{application_id}")
async def get_check_history(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Return watchdog check history for one application (timeline view)."""
    user_id = user["user_id"]

    application = await db.get(Application, application_id)
    if not application or application.user_id != user_id:
        raise HTTPException(status_code=404, detail="Application not found")

    result = await db.execute(
        select(WatchdogCheck)
        .where(WatchdogCheck.application_id == application_id)
        .order_by(WatchdogCheck.created_at.desc())
        .limit(limit)
    )
    checks = list(result.scalars().all())

    return [
        {
            "id": c.id,
            "check_status": c.check_status,
            "posting_changed": c.posting_changed,
            "status_changed": c.status_changed,
            "previous_status": c.previous_status,
            "new_status": c.new_status,
            "diff_summary": c.diff_summary,
            "removal_signal": c.removal_signal,
            "duration_ms": c.check_duration_ms,
            "triggered_by": c.triggered_by,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in checks
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _days_since(app: Application) -> int:
    ref = app.submitted_at or app.created_at
    if not ref:
        return 0
    return max(0, (datetime.now(UTC) - ref).days)
