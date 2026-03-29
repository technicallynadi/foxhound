"""Applications API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.session import get_db
from app.services.apply.orchestrator import ApplicationOrchestrator
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])

orchestrator = ApplicationOrchestrator()


class ApplyBody(BaseModel):
    job_id: str
    trigger: str = "manual"


@router.post("")
async def create_application(
    body: ApplyBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a new job application via TinyFish."""
    user_id = user["user_id"]
    try:
        app = await orchestrator.apply(
            db=db,
            user_id=user_id,
            job_id=body.job_id,
            trigger=body.trigger,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "application_id": app.id,
        "status": app.status,
        "tinyfish_status": app.tinyfish_status,
    }


@router.get("")
async def list_applications(
    user: dict = Depends(get_current_user),
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List user's applications."""
    user_id = user["user_id"]
    offset = (page - 1) * per_page

    query = (
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
    )
    if status:
        query = query.where(Application.status == status)

    query = query.order_by(Application.created_at.desc()).offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.all()

    count_query = (
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == user_id)
    )
    if status:
        count_query = count_query.where(Application.status == status)
    total = (await db.execute(count_query)).scalar() or 0

    items = []
    for app, job in rows:
        items.append({
            "id": app.id,
            "status": app.status,
            "trigger": app.trigger,
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "ats_type": job.ats_type,
            },
            "tinyfish_status": app.tinyfish_status,
            "screenshot_url": app.screenshot_storage_path,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/stats")
async def application_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application statistics."""
    user_id = user["user_id"]
    from app.db.models.user_profile import UserProfile

    # Get profile for tier/limits
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    # Count by status
    result = await db.execute(
        select(Application.status, func.count())
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    )
    status_counts = dict(result.all())

    return {
        "total": sum(status_counts.values()),
        "submitted": status_counts.get("submitted", 0),
        "confirmed": status_counts.get("confirmed", 0),
        "failed": status_counts.get("failed", 0),
        "needs_manual": status_counts.get("needs_manual", 0),
        "in_progress": status_counts.get("in_progress", 0),
        "this_month": profile.applications_this_month if profile else 0,
        "monthly_limit": profile.monthly_apply_limit if profile else 0,
        "tier": profile.tier if profile else "free",
    }


@router.get("/{application_id}")
async def get_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full application detail."""
    user_id = user["user_id"]
    result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Application not found")

    app, job = row
    return {
        "id": app.id,
        "status": app.status,
        "trigger": app.trigger,
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "apply_url": job.apply_url,
            "ats_type": job.ats_type,
        },
        "fields_filled": json.loads(app.fields_filled_json or "[]"),
        "custom_answers": json.loads(app.custom_answers_json or "[]"),
        "tinyfish_status": app.tinyfish_status,
        "tinyfish_duration_ms": app.tinyfish_duration_ms,
        "screenshot_url": app.screenshot_storage_path,
        "error_type": app.error_type,
        "error_message": app.error_message,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }
