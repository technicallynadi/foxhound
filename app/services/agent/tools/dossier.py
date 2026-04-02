"""Intelligence Report tool: build a company report via the agent chat."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.dossier import Dossier
from app.db.models.job_listing import JobListing
from app.services.agent.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="get_dossier",
    description=(
        "Build a comprehensive Intelligence Report on a company. Researches the "
        "company's about page, careers page, recent news, team contacts, and "
        "Glassdoor reviews in the background using TinyFish. Then synthesizes "
        "outreach drafts, interview prep, and an overall assessment with Claude. "
        "Use when the user says 'get me a report on this company', 'research "
        "this job', 'build a report', or 'prepare me for this interview'. "
        "Specify by application_id, job_id, or company_name. Returns immediately "
        "with a building status — the report takes 2-5 minutes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "application_id": {
                "type": "string",
                "description": "Application ID to build report for (preferred)",
            },
            "job_id": {
                "type": "string",
                "description": "Job ID to build report for (will find or create application)",
            },
            "company_name": {
                "type": "string",
                "description": "Company name to research (fuzzy match to find job)",
            },
        },
    },
    permissions=["read", "write"],
    side_effects=True,
    cost_estimate="high",
)
async def get_dossier(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Start a dossier build and return confirmation."""
    application_id = params.get("application_id")
    job_id = params.get("job_id")
    company_name = (params.get("company_name") or "").strip().lower()

    # Resolve to an application_id
    if not application_id and job_id:
        # Find application for this job
        result = await db.execute(
            select(Application).where(
                Application.job_id == job_id,
                Application.user_id == user_id,
            ).order_by(Application.created_at.desc())
            .limit(1)
        )
        app = result.scalar_one_or_none()
        if app:
            application_id = app.id
        else:
            return {
                "error": "no_application",
                "message": (
                    "No application found for this job. "
                    "Apply first, then request a report."
                ),
            }

    if not application_id and company_name:
        # Find most recent application matching company name
        result = await db.execute(
            select(Application, JobListing)
            .join(JobListing, Application.job_id == JobListing.id)
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
        )
        for app, job in result:
            if company_name in (job.company or "").lower():
                application_id = app.id
                break

        if not application_id:
            return {
                "error": "no_application",
                "message": (
                    f"No application found for '{company_name}'. "
                    "Apply first, then request a report."
                ),
                "suggestion": "Use search_jobs to find the company, apply, then request a report.",
            }

    if not application_id:
        return {
            "error": "missing_input",
            "message": "Please specify an application_id, job_id, or company_name.",
        }

    # Check if dossier already exists
    existing_result = await db.execute(
        select(Dossier).where(
            Dossier.application_id == application_id,
            Dossier.user_id == user_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing and existing.status == "ready":
        return {
            "status": "ready",
            "dossier_id": existing.id,
            "message": (
                f"Intelligence Report is already complete for this application. "
                f"View it at /dossier/{existing.id}"
            ),
        }
    if existing and existing.status == "building":
        return {
            "status": "building",
            "dossier_id": existing.id,
            "message": "Intelligence Report is already being built. You'll be notified when it's ready.",
        }

    # Start the build
    from app.services.dossier.builder import DossierBuilder

    builder = DossierBuilder()
    result = await builder.start(application_id, user_id)

    if result.get("status") == "error":
        return {
            "error": "build_failed",
            "message": result.get("message", "Failed to start Intelligence Report build"),
        }

    # Load company name for the confirmation message
    app_result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.id == application_id)
    )
    row = app_result.first()
    company = row[1].company if row else "this company"
    title = row[1].title if row else "this role"

    return {
        "status": "building",
        "dossier_id": result["dossier_id"],
        "message": (
            f"Building your Intelligence Report for {company} — {title}. "
            "This takes 2-5 minutes. You'll be notified when it's ready. "
            "The report will include company overview, hiring velocity, recent news, "
            "team contacts, outreach drafts, and interview prep."
        ),
    }
