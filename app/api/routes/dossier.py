"""Dossier API routes.

POST /api/v1/dossier/{application_id}             — start building
GET  /api/v1/dossier/{dossier_id}                  — get current state
GET  /api/v1/dossier/by-application/{application_id} — find dossier for an application
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dossier import Dossier
from app.db.session import get_db
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dossier", tags=["dossier"])

# Rate limit: 1 dossier per application, 10 per user per day
_DAILY_DOSSIER_LIMIT = 10


def _serialize_dossier(dossier: Dossier) -> dict:
    """Serialize a dossier row into an API response dict."""

    def _safe_json(text: str | None) -> dict | list | str | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            # TinyFish returns {"result": "...long text..."} — unwrap it
            # so the UI gets the text directly or structured data
            if isinstance(parsed, dict) and list(parsed.keys()) == ["result"]:
                return parsed["result"]
            return parsed
        except (json.JSONDecodeError, TypeError):
            return text

    return {
        "id": dossier.id,
        "application_id": dossier.application_id,
        "user_id": dossier.user_id,
        "company_normalized": dossier.company_normalized,
        "status": dossier.status,
        "instant_analysis": _safe_json(dossier.instant_analysis),
        "company_data": _safe_json(dossier.company_data),
        "careers_data": _safe_json(dossier.careers_data),
        "news_data": _safe_json(dossier.news_data),
        "team_contacts": _safe_json(dossier.team_contacts),
        "glassdoor_data": _safe_json(dossier.glassdoor_data),
        "reddit_interviews_data": _safe_json(dossier.reddit_interviews_data),
        "reddit_culture_data": _safe_json(dossier.reddit_culture_data),
        "engineering_blog_data": _safe_json(dossier.engineering_blog_data),
        "levels_fyi_data": _safe_json(dossier.levels_fyi_data),
        "executive_summary": _safe_json(dossier.executive_summary),
        "outreach_draft": _safe_json(dossier.outreach_draft),
        "interview_prep": _safe_json(dossier.interview_prep),
        "interview_process": _safe_json(dossier.interview_process),
        "culture_report": _safe_json(dossier.culture_report),
        "salary_estimate": _safe_json(dossier.salary_estimate),
        "overall_assessment": dossier.overall_assessment,
        "overlap_data": _safe_json(dossier.overlap_data),
        "sources_completed": _safe_json(dossier.sources_completed) or [],
        "sources_failed": _safe_json(dossier.sources_failed) or [],
        "tinyfish_credits": dossier.tinyfish_credits,
        "created_at": dossier.created_at.isoformat() if dossier.created_at else None,
        "completed_at": dossier.completed_at.isoformat() if dossier.completed_at else None,
        "notified_at": dossier.notified_at.isoformat() if dossier.notified_at else None,
    }


@router.post("/{application_id}")
async def start_dossier(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start building a dossier for an application.

    Returns immediately with {status: "building", dossier_id: "..."}.
    The background task runs TinyFish sources and updates the DB.
    """
    user_id = user["user_id"]

    # Rate limit check
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    count_result = await db.execute(
        select(func.count())
        .select_from(Dossier)
        .where(
            Dossier.user_id == user_id,
            Dossier.created_at > day_ago,
        )
    )
    recent_count = count_result.scalar() or 0

    if recent_count >= _DAILY_DOSSIER_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Dossier rate limit reached ({_DAILY_DOSSIER_LIMIT}/day). Try again tomorrow.",
        )

    from app.services.dossier.builder import DossierBuilder

    builder = DossierBuilder()
    result = await builder.start(application_id, user_id)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to start dossier"))

    return result


@router.get("/{dossier_id}")
async def get_dossier(
    dossier_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current state of a dossier (partial or complete).

    Sections that are not ready yet will be null. Check the status
    field: "building" | "partial" | "ready" | "failed".
    """
    user_id = user["user_id"]

    from app.db.models.application import Application
    from app.db.models.job_listing import JobListing

    result = await db.execute(
        select(Dossier).where(
            Dossier.id == dossier_id,
            Dossier.user_id == user_id,
        )
    )
    dossier = result.scalar_one_or_none()

    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier not found")

    data = _serialize_dossier(dossier)

    # Enrich with company name and role title from the application
    try:
        app_result = await db.execute(
            select(Application, JobListing)
            .join(JobListing, Application.job_id == JobListing.id)
            .where(Application.id == dossier.application_id)
        )
        row = app_result.first()
        if row:
            _, job = row
            data["company_name"] = job.company or dossier.company_normalized
            data["role_title"] = job.title or ""
    except Exception:
        pass

    return data


@router.post("/{dossier_id}/resynthesize")
async def resynthesize_dossier(
    dossier_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run Claude synthesis against saved TinyFish data.

    Use this when the original synthesis failed but source data exists.
    """
    user_id = user["user_id"]

    result = await db.execute(
        select(Dossier).where(
            Dossier.id == dossier_id,
            Dossier.user_id == user_id,
        )
    )
    dossier = result.scalar_one_or_none()

    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier not found")

    from app.services.dossier.builder import DossierBuilder

    builder = DossierBuilder()
    import asyncio
    asyncio.create_task(
        builder._resynthesize(dossier_id),
        name=f"resynth-{dossier_id[:8]}",
    )

    return {"status": "resynthesizing", "dossier_id": dossier_id}


@router.get("/notifications/pending")
async def get_pending_notifications(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get reports that completed but haven't been viewed yet.

    Returns dossiers where status='ready' and notified_at is null,
    indicating the user hasn't seen the completion yet.
    """
    user_id = user["user_id"]

    from app.db.models.application import Application
    from app.db.models.job_listing import JobListing

    result = await db.execute(
        select(Dossier, JobListing.company, JobListing.title)
        .join(
            Application,
            Dossier.application_id == Application.id,
        )
        .join(
            JobListing,
            Application.job_id == JobListing.id,
        )
        .where(
            Dossier.user_id == user_id,
            Dossier.status == "ready",
            Dossier.notified_at.is_(None),
        )
        .order_by(Dossier.completed_at.desc())
        .limit(10)
    )

    notifications = []
    for dossier, company, role in result.all():
        notifications.append({
            "dossier_id": dossier.id,
            "company": company or dossier.company_normalized,
            "role": role or "",
            "status": dossier.status,
            "completed_at": dossier.completed_at.isoformat() if dossier.completed_at else None,
        })

    return {"notifications": notifications}


@router.post("/{dossier_id}/dismiss")
async def dismiss_notification(
    dossier_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a dossier notification as seen/dismissed."""
    user_id = user["user_id"]

    result = await db.execute(
        select(Dossier).where(
            Dossier.id == dossier_id,
            Dossier.user_id == user_id,
        )
    )
    dossier = result.scalar_one_or_none()

    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier not found")

    dossier.notified_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True}


@router.get("/by-application/{application_id}")
async def get_dossier_by_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find a dossier for a given application.

    Returns the most recent dossier for this application, or 404.
    """
    user_id = user["user_id"]

    result = await db.execute(
        select(Dossier)
        .where(
            Dossier.application_id == application_id,
            Dossier.user_id == user_id,
        )
        .order_by(Dossier.created_at.desc())
        .limit(1)
    )
    dossier = result.scalar_one_or_none()

    if not dossier:
        raise HTTPException(status_code=404, detail="No dossier found for this application")

    return _serialize_dossier(dossier)
