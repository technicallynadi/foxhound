"""Discover jobs tool: TinyFish-powered web search for job opportunities.

Goes beyond the pre-configured board lists — searches the open web
for jobs matching the user's criteria, discovers new companies, and
returns structured listings that can be saved to the DB.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="discover_jobs",
    description=(
        "Search the web for new job opportunities using TinyFish. Goes beyond "
        "the existing job database — browses career pages, job boards, and "
        "Google to find roles matching the user's criteria. Use when the user "
        "says 'find me jobs at [type of company]', 'search for [role] in [location]', "
        "'find remote frontend jobs at health tech startups', or any request to "
        "discover jobs beyond what's already in the database. Returns structured "
        "job listings with title, company, location, and apply URL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'senior frontend engineer health tech London')",
            },
            "role": {
                "type": "string",
                "description": "Target role/title (e.g. 'Senior Frontend Engineer')",
            },
            "location": {
                "type": "string",
                "description": "Target location (e.g. 'London, UK' or 'remote')",
            },
            "industry": {
                "type": "string",
                "description": "Target industry or company type (e.g. 'health tech', 'fintech', 'AI startups')",
            },
            "count": {
                "type": "integer",
                "description": "Number of jobs to find (default 5, max 10)",
            },
        },
        "required": ["query"],
    },
    permissions=["read"],
    side_effects=True,
    cost_estimate="high",
)
async def discover_jobs(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Search the web for jobs matching user criteria via TinyFish."""
    query = params.get("query", "").strip()
    role = params.get("role", "")
    location = params.get("location", "")
    industry = params.get("industry", "")
    count = min(params.get("count", 5), 10)

    if not query:
        return {"error": "missing_query", "message": "Please describe what kind of jobs you're looking for."}

    # Load user profile for context
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    # Build search context from profile if available
    profile_context = ""
    if profile:
        skills = json.loads(profile.skills_json or "[]")
        if skills:
            profile_context = f"Candidate skills: {', '.join(skills[:10])}. "
        if profile.summary:
            profile_context += f"Background: {profile.summary[:200]}. "

    # Build multiple small focused search tasks
    search_query = query
    if role and role.lower() not in query.lower():
        search_query += f" {role}"
    if location and location.lower() not in query.lower():
        search_query += f" {location}"

    _RESULT_SCHEMA = (
        "Return as JSON array: "
        '[{"title": "...", "company": "...", "location": "...", '
        '"apply_url": "...", "description": "...", "salary": "..."}]'
    )

    sources = [
        {
            "name": "google_jobs",
            "url": f"https://www.google.com/search?q={search_query.replace(' ', '+')}+job+apply",
            "goal": (
                f"Find job openings from Google search results for: {search_query}. "
                f"{f'Focus on {industry} companies. ' if industry else ''}"
                "Click into 5-6 of the most relevant job posting links. "
                "For each, extract: title, company, location, apply URL, "
                "brief description, and salary if listed. " + _RESULT_SCHEMA
            ),
        },
    ]

    # Run searches in parallel with global semaphore
    from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE
    all_jobs: list[dict] = []

    async def _run_search(source: dict) -> list[dict]:
        async with TINYFISH_SEMAPHORE:
            try:
                from tinyfish import BrowserProfile, RunStatus
                from app.services.ingest.tinyfish_adapter import _get_client

                client = _get_client()
                result = await client.agent.run(
                    goal=source["goal"],
                    url=source["url"],
                    browser_profile=BrowserProfile.LITE,
                )

                if result.status == RunStatus.COMPLETED and result.result:
                    raw = result.result if isinstance(result.result, str) else json.dumps(result.result)
                    jobs = _parse_job_results(raw)
                    logger.info("Discovery '%s': found %d jobs", source["name"], len(jobs))
                    return jobs
                return []
            except Exception as e:
                logger.warning("Discovery '%s' failed: %s", source["name"], str(e)[:200])
                return []

    gathered = await asyncio.gather(*[_run_search(s) for s in sources])
    for jobs in gathered:
        all_jobs.extend(jobs)

    # Deduplicate by title + company
    seen = set()
    unique: list[dict] = []
    for job in all_jobs:
        key = (job.get("title", "").lower(), job.get("company", "").lower())
        if key not in seen and key[0]:
            seen.add(key)
            unique.append(job)

    if not unique:
        from app.services.activity.logger import log_activity

        await log_activity(
            user_id=user_id,
            event_type="scan_completed",
            title="Discovery run finished",
            description=f"No new jobs found for '{query}'.",
            metadata={"query": query, "count": 0},
        )
        return {
            "status": "no_results",
            "query": query,
            "message": f"No jobs found matching '{query}'. Try broadening your search.",
        }

    from app.services.activity.logger import log_activity
    await log_activity(
        user_id=user_id,
        event_type="matches_discovered",
        title=f"Discovered {len(unique[:count])} jobs for {query}",
        description="Foxhound searched beyond the saved job database.",
        metadata={
            "query": query,
            "count": len(unique[:count]),
            "jobs": unique[: min(len(unique), 3)],
        },
    )

    return {
        "status": "found",
        "jobs": unique[:count],
        "count": len(unique[:count]),
        "query": query,
        "message": (
            f"Found {len(unique[:count])} jobs matching '{query}'. "
            "Use apply_to_job with the apply_url to apply to any of these."
        ),
    }


def _parse_job_results(raw: str) -> list[dict]:
    """Parse TinyFish output into structured job listings."""
    import re

    # Try direct JSON parse
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [j for j in data if isinstance(j, dict) and j.get("title")]
        if isinstance(data, dict) and data.get("result"):
            inner = data["result"]
            if isinstance(inner, list):
                return [j for j in inner if isinstance(j, dict) and j.get("title")]
            if isinstance(inner, str):
                return _parse_job_results(inner)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON array from text
    match = re.search(r'\[[\s\S]*\]', raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [j for j in data if isinstance(j, dict) and j.get("title")]
        except json.JSONDecodeError:
            pass

    return []
