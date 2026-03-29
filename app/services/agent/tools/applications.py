"""Application listing tool."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.services.agent.registry import tool


@tool(
    name="get_applications",
    description=(
        "List the user's job applications and their status. Use this when the "
        "user asks about their application status, history, or progress."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status (pending, submitted, failed, waiting_user_input, needs_manual)"},
            "company": {"type": "string", "description": "Filter by company name"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
        },
    },
    permissions=["read"],
    side_effects=False,
)
async def get_applications(db: AsyncSession, user_id: str, params: dict) -> dict:
    limit = min(params.get("limit", 10), 20)
    status_filter = params.get("status")
    company_filter = (params.get("company") or "").lower()

    stmt = (
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
    )

    if status_filter:
        stmt = stmt.where(Application.status == status_filter)

    stmt = stmt.order_by(Application.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    if company_filter:
        rows = [(a, j) for a, j in rows if company_filter in (j.company or "").lower()]

    if not rows:
        return {"applications": [], "message": "No applications found."}

    apps = []
    for app, job in rows:
        entry = {
            "application_id": app.id,
            "company": job.company,
            "title": job.title,
            "status": app.status,
            "trigger": app.trigger,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        }
        if app.submitted_at:
            entry["submitted_at"] = app.submitted_at.isoformat()
        if app.error_type:
            entry["error"] = app.error_type
        if app.screenshot_storage_path:
            entry["has_screenshot"] = True
        apps.append(entry)

    statuses = {}
    for app, _ in rows:
        statuses[app.status] = statuses.get(app.status, 0) + 1

    return {
        "applications": apps,
        "total": len(apps),
        "by_status": statuses,
        "message": f"{len(apps)} applications. " + ", ".join(f"{v} {k}" for k, v in statuses.items()) + ".",
    }
