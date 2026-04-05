"""Jobs marketplace feed API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.session import get_db
from app.services.auth_service import get_current_user, get_optional_user

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class FeedbackBody(BaseModel):
    feedback: str  # "thumbs_up" | "thumbs_down"


class SubmitUrlBody(BaseModel):
    url: str


@router.get("")
async def list_jobs(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: int = Query(0, ge=0, le=100),
    sort_by: str = Query("match_score"),
    db: AsyncSession = Depends(get_db),
):
    """Paginated marketplace feed of matched jobs for the user."""
    user_id = user["user_id"]
    offset = (page - 1) * per_page

    query = (
        select(JobMatch, JobListing)
        .join(JobListing, JobMatch.job_id == JobListing.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.disqualified is False,
            JobMatch.match_score >= min_score,
            JobListing.status == "active",
        )
        .order_by(JobMatch.match_score.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(query)
    rows = result.all()

    # Get total count
    count_query = (
        select(func.count())
        .select_from(JobMatch)
        .join(JobListing, JobMatch.job_id == JobListing.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.disqualified is False,
            JobMatch.match_score >= min_score,
            JobListing.status == "active",
        )
    )
    total = (await db.execute(count_query)).scalar() or 0

    items = []
    for match, job in rows:
        items.append({
            "job": _serialize_job(job),
            "match_score": match.match_score,
            "scoring_breakdown": {
                "title": match.title_score,
                "skills": match.skills_score,
                "experience": match.experience_score,
                "location": match.location_score,
                "salary": match.salary_score,
                "recency": match.recency_score,
            },
            "auto_apply_supported": bool(job.auto_apply_supported),
            "user_action": match.user_action,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


# ---------------------------------------------------------------------------
# Public endpoints (no auth required) — MUST be before /{job_id}
# ---------------------------------------------------------------------------


@router.get("/public")
async def public_job_feed(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    search: str = Query("", max_length=100),
    user: dict | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Job feed — public with optional auth enrichment.

    When authenticated: includes match_score and ghost data.
    When not authenticated: returns basic job info.
    """
    offset = (page - 1) * per_page
    user_id = user["user_id"] if user else None

    # Sanitize search input — escape LIKE wildcards to prevent DoS
    if search:
        search = search.replace("%", "").replace("_", "")
        search = search.strip()[:100]

    # If authenticated, try the matched feed first
    if user_id:
        try:
            query = (
                select(JobMatch, JobListing)
                .join(JobListing, JobMatch.job_id == JobListing.id)
                .where(
                    JobMatch.user_id == user_id,
                    JobMatch.disqualified is False,
                    JobListing.status == "active",
                )
            )
            if search:
                query = query.where(
                    JobListing.title.ilike(f"%{search}%")
                    | JobListing.company.ilike(f"%{search}%")
                )
            query = query.order_by(JobMatch.match_score.desc()).offset(offset).limit(per_page)

            result = await db.execute(query)
            rows = result.all()

            if rows:
                count_q = (
                    select(func.count())
                    .select_from(JobMatch)
                    .join(JobListing, JobMatch.job_id == JobListing.id)
                    .where(
                        JobMatch.user_id == user_id,
                        JobMatch.disqualified is False,
                        JobListing.status == "active",
                    )
                )
                total = (await db.execute(count_q)).scalar() or 0

                jobs = []
                for match, job in rows:
                    j = _serialize_job(job)
                    j["match_score"] = match.match_score
                    jobs.append(j)

                return {"jobs": jobs, "total": total, "page": page, "per_page": per_page}
        except Exception:
            pass  # Fall through to public feed

    # Public feed (no auth or no matches)
    stmt = select(JobListing).where(JobListing.status == "active")

    if search:
        stmt = stmt.where(
            JobListing.title.ilike(f"%{search}%")
            | JobListing.company.ilike(f"%{search}%")
        )

    count_stmt = select(func.count(JobListing.id)).where(JobListing.status == "active")
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(JobListing.posted_at.desc().nullslast(), JobListing.discovered_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(stmt)
    jobs = [_serialize_job(j) for j in result.scalars()]

    return {"jobs": jobs, "total": total, "page": page, "per_page": per_page}


@router.get("/public/stats")
async def public_stats(db: AsyncSession = Depends(get_db)):
    """Public stats for the landing page. No authentication required."""
    total_jobs = (await db.execute(
        select(func.count(JobListing.id)).where(JobListing.status == "active")
    )).scalar() or 0

    total_companies = (await db.execute(
        select(func.count(func.distinct(JobListing.company))).where(JobListing.status == "active")
    )).scalar() or 0

    ats_counts = {}
    ats_result = await db.execute(
        select(JobListing.ats_type, func.count(JobListing.id))
        .where(JobListing.status == "active", JobListing.ats_type.is_not(None))
        .group_by(JobListing.ats_type)
    )
    for ats, count in ats_result.all():
        ats_counts[ats] = count

    return {
        "total_jobs": total_jobs,
        "total_companies": total_companies,
        "by_ats": ats_counts,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full job detail with match breakdown."""
    user_id = user["user_id"]
    result = await db.execute(select(JobListing).where(JobListing.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    # Get match if exists
    match_result = await db.execute(
        select(JobMatch).where(
            JobMatch.job_id == job_id, JobMatch.user_id == user_id
        )
    )
    match = match_result.scalar_one_or_none()

    return {
        "job": _serialize_job(job),
        "match": {
            "score": match.match_score if match else None,
            "breakdown": {
                "title": match.title_score,
                "skills": match.skills_score,
                "experience": match.experience_score,
                "location": match.location_score,
                "salary": match.salary_score,
                "recency": match.recency_score,
            } if match else None,
            "disqualified": bool(match.disqualified) if match else None,
            "disqualify_reason": match.disqualify_reason if match else None,
        },
    }


@router.post("/{job_id}/dismiss")
async def dismiss_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a job from the feed."""
    user_id = user["user_id"]
    result = await db.execute(
        select(JobMatch).where(
            JobMatch.job_id == job_id, JobMatch.user_id == user_id
        )
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(404, "Match not found")

    match.user_action = "dismissed"
    await db.commit()
    return {"status": "dismissed"}


@router.post("/{job_id}/save")
async def save_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a job for later."""
    user_id = user["user_id"]
    result = await db.execute(
        select(JobMatch).where(
            JobMatch.job_id == job_id, JobMatch.user_id == user_id
        )
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(404, "Match not found")

    match.user_action = "saved"
    await db.commit()
    return {"status": "saved"}


@router.post("/{job_id}/feedback")
async def job_feedback(
    job_id: str,
    body: FeedbackBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback on a job match (thumbs up/down)."""
    user_id = user["user_id"]
    if body.feedback not in ("thumbs_up", "thumbs_down"):
        raise HTTPException(400, "feedback must be 'thumbs_up' or 'thumbs_down'")

    result = await db.execute(
        select(JobMatch).where(
            JobMatch.job_id == job_id, JobMatch.user_id == user_id
        )
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(404, "Match not found")

    match.user_feedback = body.feedback
    await db.commit()
    return {"status": "feedback_recorded"}


def _serialize_job(job: JobListing) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "company_url": job.company_url,
        "location": job.location,
        "remote_type": job.remote_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "seniority": job.seniority,
        "required_skills": json.loads(job.required_skills_json or "[]"),
        "preferred_skills": json.loads(job.preferred_skills_json or "[]"),
        "ats_type": job.ats_type,
        "auto_apply_supported": bool(job.auto_apply_supported),
        "apply_url": job.apply_url,
        "source": job.source,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "description": job.description[:500] if job.description else "",
        "ghost_score": getattr(job, "ghost_score", None),
        "ghost_risk": getattr(job, "ghost_risk", None),
        "ghost_factors_json": getattr(job, "ghost_factors_json", None),
    }
