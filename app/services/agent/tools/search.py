"""Job search and matching tools."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool


@tool(
    name="search_jobs",
    description=(
        "Search for jobs matching a query. Use this when the user wants to "
        "find jobs, explore what's available, or search for specific roles. "
        "Returns matching job listings with relevance scores."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms (e.g. 'ML engineer', 'backend Python')"},
            "location": {"type": "string", "description": "Location filter (e.g. 'San Francisco', 'remote')"},
            "remote_only": {"type": "boolean", "description": "Only show remote jobs"},
            "min_salary": {"type": "integer", "description": "Minimum salary filter"},
            "limit": {"type": "integer", "description": "Max results to return (default 5)"},
        },
        "required": ["query"],
    },
    permissions=["read"],
    side_effects=False,
)
async def search_jobs(db: AsyncSession, user_id: str, params: dict) -> dict:
    query = params.get("query", "").lower()
    location = params.get("location", "").lower()
    remote_only = params.get("remote_only", False)
    min_salary = params.get("min_salary")
    limit = min(params.get("limit", 5), 20)

    result = await db.execute(
        select(JobListing).where(JobListing.status == "active")
        .order_by(JobListing.discovered_at.desc())
    )
    all_jobs = list(result.scalars().all())

    scored = []
    for job in all_jobs:
        score = 0
        title_lower = (job.title or "").lower()
        desc_lower = (job.description or "").lower()
        company_lower = (job.company or "").lower()

        for term in query.split():
            if term in title_lower:
                score += 3
            if term in company_lower:
                score += 2
            if term in desc_lower:
                score += 1

        if location:
            job_loc = (job.location or "").lower()
            if location in job_loc or (location == "remote" and job.remote_type == "remote"):
                score += 2
            elif location and location not in job_loc and job.remote_type != "remote":
                continue

        if remote_only and job.remote_type != "remote":
            continue
        if min_salary and job.salary_max and job.salary_max < min_salary:
            continue
        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    if not top:
        return {"jobs": [], "message": f"No jobs found matching '{query}'."}

    # Check match scores
    job_ids = [j.id for _, j in top]
    match_result = await db.execute(
        select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id.in_(job_ids))
    )
    match_map = {m.job_id: m.match_score for m in match_result.scalars()}

    jobs_data = []
    for _, job in top:
        entry = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location or "Not specified",
            "remote": job.remote_type or "unknown",
            "salary_range": _format_salary(job.salary_min, job.salary_max),
            "ats": job.ats_type,
        }
        if job.id in match_map:
            entry["match_score"] = match_map[job.id]
        jobs_data.append(entry)

    return {"jobs": jobs_data, "total_found": len(scored), "showing": len(top),
            "message": f"Found {len(scored)} jobs matching '{query}'. Showing top {len(top)}."}


@tool(
    name="get_matches",
    description=(
        "Get the user's top job matches based on their profile. "
        "Use this when the user asks what jobs match them, wants recommendations, "
        "or says 'show me my matches'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "min_score": {"type": "integer", "description": "Minimum match score 0-100 (default 50)"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
        },
    },
    permissions=["read"],
    side_effects=False,
)
async def get_matches(db: AsyncSession, user_id: str, params: dict) -> dict:
    min_score = params.get("min_score", 50)
    limit = min(params.get("limit", 10), 20)

    result = await db.execute(
        select(JobMatch, JobListing)
        .join(JobListing, JobMatch.job_id == JobListing.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.match_score >= min_score,
            JobMatch.disqualified == False,
            JobMatch.user_action != "dismissed",
        )
        .order_by(JobMatch.match_score.desc())
        .limit(limit)
    )
    rows = result.all()

    if not rows:
        count_result = await db.execute(
            select(func.count()).select_from(JobMatch).where(JobMatch.user_id == user_id)
        )
        total = count_result.scalar() or 0
        if total == 0:
            return {"matches": [], "message": "No matches yet. Want me to search for jobs?"}
        return {"matches": [], "message": f"No matches above {min_score}%. You have {total} at lower scores."}

    matches = []
    for match, job in rows:
        matches.append({
            "job_id": job.id, "title": job.title, "company": job.company,
            "location": job.location or "Not specified",
            "remote": job.remote_type or "unknown",
            "match_score": match.match_score,
            "salary_range": _format_salary(job.salary_min, job.salary_max),
        })

    return {"matches": matches, "total_above_threshold": len(rows),
            "message": f"Top {len(matches)} matches above {min_score}%."}


def _format_salary(min_sal: int | None, max_sal: int | None) -> str:
    if min_sal and max_sal:
        return f"${min_sal:,}-${max_sal:,}"
    if min_sal:
        return f"${min_sal:,}+"
    if max_sal:
        return f"Up to ${max_sal:,}"
    return "Not listed"
