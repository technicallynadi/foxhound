"""Pathfinder API routes.

POST /api/v1/pathfinder/{job_id} — hiring manager discovery + outreach drafting.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.db.session import get_db
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pathfinder", tags=["pathfinder"])


@router.post("/{job_id}")
async def pathfinder_discover(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover the likely hiring manager for a job and draft outreach.

    Returns manager signals, LinkedIn/Google search URLs, overlap analysis,
    and draft connection request + email. All derived from existing job
    posting data in the DB — no external scraping.
    """
    user_id = user["user_id"]

    # Load job listing
    job_result = await db.execute(select(JobListing).where(JobListing.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job listing not found.")

    # Load user profile
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found. Complete onboarding first.")

    # Lazy imports to keep startup fast
    from app.services.pathfinder.extractor import extract_manager_signals
    from app.services.pathfinder.outreach import draft_outreach
    from app.services.pathfinder.overlap import find_overlap
    from app.services.pathfinder.search_url import build_search_urls

    # 1. Extract hiring manager signals from job description
    manager_signals = await extract_manager_signals(
        job_title=job.title,
        company=job.company,
        description=job.description,
        seniority=job.seniority,
    )

    # 2. Build search URLs
    likely_title = manager_signals.get("likely_title", "Hiring Manager")
    department = manager_signals.get("department", "Engineering")
    search_urls = build_search_urls(company=job.company, title=likely_title)

    # 2b. TinyFish background enrichment — search company team page for actual name
    import asyncio

    from app.services.pathfinder.team_lookup import lookup_team_page

    team_lookup_task = asyncio.create_task(
        lookup_team_page(
            company_name=job.company,
            company_url=getattr(job, "company_url", None),
            department=department,
            likely_title=likely_title,
        )
    )

    # 3. Compute profile-to-job overlap
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

    # 4. Draft outreach messages
    user_name = " ".join(p for p in [profile.first_name, profile.last_name] if p) or "there"

    outreach = await draft_outreach(
        job_title=job.title,
        company=job.company,
        description=job.description,
        manager_title=likely_title,
        user_name=user_name,
        user_summary=profile.summary,
        overlap_summary=overlap.summary_for_outreach(),
    )

    # 5. Collect TinyFish result (may still be running — wait up to 2s, then return without it)
    team_result = None
    try:
        team_result = await asyncio.wait_for(team_lookup_task, timeout=2.0)
    except TimeoutError:
        # TinyFish still running — return without it, it'll be available on next call via cache
        logger.info("Pathfinder: TinyFish still running for %s, returning without enrichment", job.company)
    except Exception:
        pass

    result = {
        "job_id": job_id,
        "company": job.company,
        "job_title": job.title,
        "manager_signals": manager_signals,
        "search_urls": search_urls,
        "overlap": overlap.to_dict(),
        "outreach": outreach,
    }

    if team_result:
        result["confirmed_manager"] = team_result

    return result
