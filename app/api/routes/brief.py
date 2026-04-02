"""Foxhound Brief API — the per-application intelligence artifact."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.foxhound_brief import FoxhoundBrief
from app.db.models.job_listing import JobListing
from app.db.session import get_db
from app.services.application_guidance import (
    build_application_context,
    build_recommended_next_action,
    parse_serialized_recommended_next_action,
)
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/brief", tags=["brief"])


@router.get("/{application_id}")
async def get_brief(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the Foxhound Brief for an application."""
    user_id = user["user_id"]

    # Get the brief
    result = await db.execute(
        select(FoxhoundBrief).where(
            FoxhoundBrief.application_id == application_id,
            FoxhoundBrief.user_id == user_id,
        )
    )
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(404, "Brief not found for this application")

    # Get application + job for context
    app_result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    row = app_result.first()
    if not row:
        raise HTTPException(404, "Application not found")

    app, job = row
    context = build_application_context(
        app,
        job,
        brief_ready=True,
        brief_status=brief.status,
    )
    fallback_action = build_recommended_next_action(context, module="brief")
    recommended_action = parse_serialized_recommended_next_action(
        brief.recommended_next_action,
        fallback=fallback_action,
    )

    return {
        "brief_id": brief.id,
        "application_id": application_id,
        "status": brief.status,
        "company": job.company,
        "title": job.title,
        "match_score": None,  # Could join JobMatch here
        "applied_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "generated_at": brief.updated_at.isoformat() if brief.updated_at else None,
        "application_context": context,

        # Submission proof
        "submission": {
            "status": app.status,
            "method": getattr(app, "submission_method", "browser"),
            "ats_type": job.ats_type,
            "screenshot": app.screenshot_storage_path,
            "pre_submit_screenshot": app.pre_submit_screenshot_path,
            "fields_filled": json.loads(app.fields_filled_json or "[]"),
        },

        # Posting status
        "posting_status": {
            "watchdog_status": brief.watchdog_status or "active",
            "ghost_score": job.ghost_score,
            "ghost_risk": job.ghost_risk,
        },

        # Company context
        "company_brief": json.loads(brief.company_brief_json) if brief.company_brief_json else None,

        # Best contact + outreach
        "pathfinder": json.loads(brief.pathfinder_json) if brief.pathfinder_json else None,

        # Network connections
        "network_map": json.loads(brief.network_map_json) if brief.network_map_json else None,

        # Full dossier
        "dossier": json.loads(brief.dossier_json) if brief.dossier_json else None,

        # Recommendation
        "recommended_next_action": recommended_action,
    }
