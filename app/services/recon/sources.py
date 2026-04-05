"""TinyFish source fetchers for company recon.

Each source returns a dict on success or None on failure.
Uses BrowserProfile.LITE for both — company websites don't need stealth.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ingest.tinyfish_adapter import _get_client

logger = logging.getLogger(__name__)


async def fetch_careers_page(company_name: str, company_url: str | None) -> dict[str, Any] | None:
    """Scrape a company's careers page for hiring signals.

    Returns dict with open_roles, technologies, top_departments, hiring_velocity
    or None on failure.
    """
    from tinyfish import BrowserProfile, RunStatus

    if not company_url:
        start_url = f"https://www.google.com/search?q={company_name}+careers"
    else:
        start_url = company_url.rstrip("/")

    goal = (
        f"Navigate to {start_url}/careers or search for '{company_name} careers'. "
        "Count the total number of open job postings. List the departments "
        "that are hiring the most. Return as JSON: "
        '{"open_roles": number, '
        '"top_departments": [string], '
        '"hiring_velocity": "growing"|"stable"|"slowing"}'
    )

    try:
        client = _get_client()
        result = await client.agent.run(
            goal=goal,
            url=start_url,
            browser_profile=BrowserProfile.LITE,
        )

        if result.status == RunStatus.COMPLETED and result.result:
            data = result.result if isinstance(result.result, dict) else {}
            if not data and isinstance(result.result, str):
                try:
                    data = json.loads(result.result)
                except (json.JSONDecodeError, TypeError):
                    data = {"raw": result.result[:1000]}
            logger.info("Careers page fetch OK for %s: %d keys", company_name, len(data))
            return data

        error = getattr(result, "error", None) or "unknown"
        logger.warning("Careers page fetch failed for %s: %s", company_name, error)
        return None

    except Exception as e:
        _log_tinyfish_error("careers", company_name, e)
        return None


async def fetch_about_page(company_name: str, company_url: str | None) -> dict[str, Any] | None:
    """Scrape a company's about page for company details.

    Returns dict with mission, founded, size, locations, funding, notable_facts
    or None on failure.
    """
    from tinyfish import BrowserProfile, RunStatus

    if not company_url:
        start_url = f"https://www.google.com/search?q={company_name}+about"
    else:
        start_url = company_url.rstrip("/")

    goal = (
        f"Navigate to {start_url}/about or the company's main page. "
        "Extract: company mission/description, founding year, number of employees "
        "(if stated), office locations, any mention of funding or investors, "
        "and the products, software, or services they provide. "
        "Return as JSON: "
        '{"mission": string, "founded": string, "size": string, '
        '"locations": [string], "funding": string, "products": [string], "notable_facts": [string]}'
    )

    try:
        client = _get_client()
        result = await client.agent.run(
            goal=goal,
            url=start_url,
            browser_profile=BrowserProfile.LITE,
        )

        if result.status == RunStatus.COMPLETED and result.result:
            data = result.result if isinstance(result.result, dict) else {}
            if not data and isinstance(result.result, str):
                try:
                    data = json.loads(result.result)
                except (json.JSONDecodeError, TypeError):
                    data = {"raw": result.result[:1000]}
            logger.info("About page fetch OK for %s: %d keys", company_name, len(data))
            return data

        error = getattr(result, "error", None) or "unknown"
        logger.warning("About page fetch failed for %s: %s", company_name, error)
        return None

    except Exception as e:
        _log_tinyfish_error("about", company_name, e)
        return None


async def load_posting_data(db: AsyncSession, job_id: str) -> dict[str, Any] | None:
    """Load job posting data from the DB. Free — no TinyFish call needed.

    Returns dict with title, company, description, tech_stack, requirements,
    seniority, remote_type, location, or None if not found.
    """
    from app.db.models.job_listing import JobListing

    result = await db.execute(select(JobListing).where(JobListing.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        logger.warning("Job %s not found for recon posting data", job_id)
        return None

    try:
        required_skills = json.loads(job.required_skills_json or "[]")
    except (json.JSONDecodeError, TypeError):
        required_skills = []

    try:
        preferred_skills = json.loads(job.preferred_skills_json or "[]")
    except (json.JSONDecodeError, TypeError):
        preferred_skills = []

    data: dict[str, Any] = {
        "title": job.title,
        "company": job.company,
        "company_url": getattr(job, "company_url", None),
        "description": (job.description or "")[:3000],
        "seniority": job.seniority,
        "remote_type": job.remote_type,
        "location": job.location,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
    }
    # Only include tech_stack if we actually have extracted skills
    all_skills = required_skills + preferred_skills
    if all_skills:
        data["tech_stack"] = all_skills
    return data


def _log_tinyfish_error(source: str, company: str, error: Exception) -> None:
    """Classify and log TinyFish errors."""
    error_str = str(error)
    if "RATE_LIMIT_EXCEEDED" in error_str:
        logger.warning("TinyFish rate limited on %s for %s", source, company)
    elif "INSUFFICIENT_CREDITS" in error_str:
        logger.error("TinyFish credits exhausted on %s for %s", source, company)
    else:
        logger.warning("TinyFish error on %s for %s: %s", source, company, error_str[:200])
