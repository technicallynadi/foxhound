"""Job matches API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/matches", tags=["matches"])


@router.get("")
async def list_matches(
    user: dict = Depends(get_current_user),
    min_score: int = Query(65, ge=0, le=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List job matches for the authenticated user, ranked by score."""
    user_id = user["user_id"]
    offset = (page - 1) * per_page

    stmt = (
        select(JobMatch, JobListing)
        .join(JobListing, JobMatch.job_id == JobListing.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.disqualified.is_(False),
            JobMatch.match_score >= min_score,
        )
        .order_by(JobMatch.match_score.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    rows = result.all()

    items = [
        {
            "match_id": match.id,
            "match_score": match.match_score,
            "title_score": match.title_score,
            "skills_score": match.skills_score,
            "experience_score": match.experience_score,
            "location_score": match.location_score,
            "salary_score": match.salary_score,
            "recency_score": match.recency_score,
            "user_action": match.user_action,
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "remote_type": job.remote_type,
                "ats_type": job.ats_type,
                "apply_url": job.apply_url,
            },
        }
        for match, job in rows
    ]

    return {"items": items, "page": page, "per_page": per_page}
