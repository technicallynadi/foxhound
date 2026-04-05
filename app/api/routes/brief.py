"""Foxhound Brief API — the per-application intelligence artifact."""

from __future__ import annotations

import json
from datetime import UTC

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
        # Brief doesn't exist — create it and start research
        from uuid import uuid4

        from app.db.models.foxhound_brief import FoxhoundBrief as BriefModel

        # Verify the application exists and belongs to this user
        app_check = await db.execute(
            select(Application).where(Application.id == application_id, Application.user_id == user_id)
        )
        app_obj = app_check.scalar_one_or_none()
        if not app_obj:
            raise HTTPException(404, "Application not found")

        brief = BriefModel(
            id=str(uuid4()),
            user_id=user_id,
            application_id=application_id,
            status="assembling",
            watchdog_status="active",
        )
        db.add(brief)
        await db.commit()

        # Start research cascade in background
        try:
            from app.services.research.cascade import start_research_cascade
            await start_research_cascade(user_id, application_id, app_obj.job_id, None)
        except Exception:
            pass  # Best effort — cascade logs its own errors

    elif brief.status not in ("ready", "failed"):
        # Brief exists but incomplete — only re-run if cascade isn't already running
        # and enough time has passed since last update (avoid re-triggering on every poll)
        from datetime import datetime, timedelta
        now = datetime.now(UTC)
        stale_threshold = now - timedelta(minutes=2)
        failure_ceiling = now - timedelta(minutes=15)

        # Hard ceiling: after 15 min still assembling → mark failed, stop re-triggering
        if brief.created_at and brief.created_at < failure_ceiling and brief.status == "assembling":
            brief.status = "failed"
            await db.commit()
        elif brief.updated_at and brief.updated_at < stale_threshold:
            app_check = await db.execute(
                select(Application).where(Application.id == application_id, Application.user_id == user_id)
            )
            app_obj = app_check.scalar_one_or_none()
            if app_obj:
                try:
                    from app.services.research.cascade import start_research_cascade
                    await start_research_cascade(user_id, application_id, app_obj.job_id, None)
                except Exception:
                    pass

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
