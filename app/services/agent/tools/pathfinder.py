"""Pathfinder tool: find the hiring manager via agent chat."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="find_hiring_manager",
    description=(
        "Discover the likely hiring manager for a job. Analyzes the job posting "
        "to identify the probable manager title, department, and reporting structure, "
        "then generates LinkedIn search URLs and drafts a personalized outreach "
        "message. Use when the user asks 'who's the hiring manager?', 'find the "
        "manager for this job', 'help me reach out', or 'pathfinder'. "
        "Specify by job_id or company_name."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "Job ID to analyze (preferred — gets exact posting).",
            },
            "company_name": {
                "type": "string",
                "description": "Company name to search for (fuzzy match, uses most recent posting).",
            },
        },
    },
    permissions=["read"],
    side_effects=False,
    cost_estimate="medium",
)
async def find_hiring_manager(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Run Pathfinder and return hiring manager intel + outreach drafts."""
    job_id = params.get("job_id")
    company_name = (params.get("company_name") or "").strip().lower()
    company_context = params.get("_company_context")
    contacts_found = params.get("_contacts_found")

    # Resolve job_id if only company_name given
    if not job_id and company_name:
        result = await db.execute(
            select(JobListing)
            .where(JobListing.status == "active")
            .order_by(JobListing.discovered_at.desc())
        )
        for job in result.scalars():
            if company_name in (job.company or "").lower():
                job_id = job.id
                break

    if not job_id:
        return {
            "error": "no_job_found",
            "message": "Could not find a job listing for that company. Try searching first.",
            "suggestion": "Use search_jobs to find the company, then run find_hiring_manager with the job_id.",
        }

    # Load job
    job_result = await db.execute(
        select(JobListing).where(JobListing.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        return {"error": "job_not_found", "message": f"Job {job_id} not found."}

    # Load user profile
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    # Lazy imports
    from app.services.pathfinder.extractor import extract_manager_signals
    from app.services.pathfinder.overlap import OverlapResult, find_overlap
    from app.services.pathfinder.outreach import draft_outreach
    from app.services.pathfinder.search_url import build_search_urls

    # 1. Extract manager signals
    manager_signals = await extract_manager_signals(
        job_title=job.title,
        company=job.company,
        description=job.description,
        seniority=job.seniority,
    )

    likely_title = manager_signals.get("likely_title", "Hiring Manager")

    # 2. Build search URLs
    search_urls = build_search_urls(company=job.company, title=likely_title)

    # 3. Compute overlap (if profile exists)
    overlap: OverlapResult | None = None
    user_name = "there"
    user_summary: str | None = None

    if profile:
        overlap = find_overlap(
            user_skills_json=profile.skills_json,
            user_industries_json=profile.industries_json,
            user_location=profile.location,
            user_seniority=profile.seniority_level,
            user_experience_json=profile.experience_json,
            job_required_skills_json=job.required_skills_json,
            job_preferred_skills_json=job.preferred_skills_json,
            job_location=job.location,
            job_seniority=job.seniority,
            job_description=job.description,
        )
        user_name = " ".join(
            p for p in [profile.first_name, profile.last_name] if p
        ) or "there"
        user_summary = profile.summary

    overlap_summary = overlap.summary_for_outreach() if overlap else "general interest in the role"

    # 4. Draft outreach
    outreach = await draft_outreach(
        job_title=job.title,
        company=job.company,
        description=job.description,
        manager_title=likely_title,
        user_name=user_name,
        user_summary=user_summary,
        overlap_summary=overlap_summary,
        company_context=company_context,
        contacts_found=contacts_found,
    )

    # Format response for agent
    dept = manager_signals.get("department", "unknown")
    confidence = manager_signals.get("confidence", "low")
    linkedin_note = outreach.get("linkedin_note", "")

    response: dict = {
        "company": job.company,
        "job_title": job.title,
        "job_id": job_id,
        "manager_signals": manager_signals,
        "search_urls": search_urls,
        "outreach": outreach,
        "message": (
            f"Pathfinder results for {job.title} at {job.company}:\n\n"
            f"Likely hiring manager: {likely_title} ({dept})\n"
            f"Confidence: {confidence}\n\n"
            f"Find them:\n"
            f"  LinkedIn: {search_urls['linkedin']}\n"
            f"  Google: {search_urls['google']}\n\n"
            f"Draft LinkedIn note:\n\"{linkedin_note}\"\n\n"
            f"Draft email subject: {outreach.get('email_subject', '')}\n"
            f"Draft email:\n{outreach.get('email_body', '')}"
        ),
    }

    if overlap:
        response["overlap"] = overlap.to_dict()

    return response
