"""Ghost Job Detector: scores job postings for likelihood of being fake/stale.

Uses multiple signals:
1. Posting age (90+ days = red flag)
2. Repost history (removed and reposted = ghost pattern)
3. Company hiring velocity (many listings, few hires = ghost farm)
4. Description staleness (unchanged for months)
5. Application response signals (from Foxhound's own data)

Returns a ghost risk score (0-100) and human-readable risk factors.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing

logger = logging.getLogger(__name__)


def calculate_ghost_score(
    job: JobListing,
    repost_count: int = 0,
    company_listing_count: int = 0,
    company_hire_count: int = 0,
    response_rate: float | None = None,
) -> dict[str, Any]:
    """Calculate ghost job risk score for a listing.

    Returns:
        {
            "score": 0-100 (higher = more likely ghost),
            "risk": "low" | "medium" | "high",
            "badge": "verified" | "caution" | "ghost_risk",
            "factors": ["list of reasons"],
        }
    """
    score = 0
    factors: list[str] = []
    now = datetime.now(timezone.utc)

    # --- Factor 1: Posting age ---
    posted = job.posted_at or job.discovered_at
    if posted:
        age_days = (now - posted).days

        if age_days > 120:
            score += 35
            factors.append(f"Posted {age_days} days ago — significantly stale")
        elif age_days > 90:
            score += 25
            factors.append(f"Posted {age_days} days ago — aging listing")
        elif age_days > 60:
            score += 15
            factors.append(f"Posted {age_days} days ago — older listing")
        elif age_days > 30:
            score += 5
            factors.append(f"Posted {age_days} days ago")
        elif age_days <= 7:
            score -= 10  # Fresh posting is a positive signal
            factors.append(f"Recently posted ({age_days} days ago)")

    # --- Factor 2: Repost pattern ---
    if repost_count >= 3:
        score += 30
        factors.append(f"Reposted {repost_count} times — classic ghost job pattern")
    elif repost_count == 2:
        score += 15
        factors.append("Reposted twice — possible churning")
    elif repost_count == 1:
        score += 5
        factors.append("Reposted once")

    # --- Factor 3: Company hiring velocity ---
    if company_listing_count > 0 and company_hire_count == 0:
        if company_listing_count >= 10:
            score += 25
            factors.append(f"{company_listing_count} open listings but no recent hires detected")
        elif company_listing_count >= 5:
            score += 15
            factors.append(f"{company_listing_count} open listings, hiring activity unclear")
    elif company_listing_count > 0 and company_hire_count > 0:
        ratio = company_hire_count / company_listing_count
        if ratio > 0.3:
            score -= 10
            factors.append(f"Active hiring: {company_hire_count} recent hires across {company_listing_count} listings")

    # --- Factor 4: Application response rate (Foxhound data) ---
    if response_rate is not None:
        if response_rate < 0.05:
            score += 20
            factors.append("Very low response rate from this company")
        elif response_rate < 0.15:
            score += 10
            factors.append("Below-average response rate")
        elif response_rate > 0.4:
            score -= 10
            factors.append("Good response rate from this company")

    # --- Factor 5: Missing posting date ---
    if not job.posted_at:
        score += 5
        factors.append("No original posting date available")

    # --- Factor 6: Job status from watchdog ---
    if job.status == "removed":
        score += 40
        factors.append("Listing has been removed")
    elif job.status == "expired":
        score += 30
        factors.append("Listing has expired")

    # Clamp score
    score = max(0, min(100, score))

    # Determine risk level and badge
    if score >= 60:
        risk = "high"
        badge = "ghost_risk"
    elif score >= 30:
        risk = "medium"
        badge = "caution"
    else:
        risk = "low"
        badge = "verified"

    return {
        "score": score,
        "risk": risk,
        "badge": badge,
        "factors": factors,
    }


async def score_job(db: AsyncSession, job_id: str) -> dict[str, Any]:
    """Calculate ghost score for a single job with full DB context."""
    job = await db.get(JobListing, job_id)
    if not job:
        return {"error": "Job not found"}

    # Get repost count from watchdog history
    repost_count = 0
    try:
        from app.db.models.watchdog_check import WatchdogCheck
        result = await db.execute(
            select(func.count()).select_from(WatchdogCheck).where(
                WatchdogCheck.job_id == job_id,
                WatchdogCheck.status_change == "reposted",
            )
        )
        repost_count = result.scalar() or 0
    except Exception:
        pass  # Table may not exist yet

    # Get company hiring signals
    company_listing_count = 0
    company_hire_count = 0
    if job.company:
        # Count active listings from this company
        result = await db.execute(
            select(func.count()).select_from(JobListing).where(
                JobListing.company == job.company,
                JobListing.status == "active",
            )
        )
        company_listing_count = result.scalar() or 0

        # Count submitted applications (proxy for hiring activity)
        result = await db.execute(
            select(func.count()).select_from(Application).join(
                JobListing, Application.job_id == JobListing.id
            ).where(
                JobListing.company == job.company,
                Application.status == "submitted",
            )
        )
        company_hire_count = result.scalar() or 0

    # Calculate response rate from Foxhound data
    response_rate = None
    if job.company:
        result = await db.execute(
            select(func.count()).select_from(Application).join(
                JobListing, Application.job_id == JobListing.id
            ).where(
                JobListing.company == job.company,
            )
        )
        total_apps = result.scalar() or 0

        if total_apps >= 3:  # Only calculate with enough data
            result = await db.execute(
                select(func.count()).select_from(Application).join(
                    JobListing, Application.job_id == JobListing.id
                ).where(
                    JobListing.company == job.company,
                    Application.status.in_(["submitted", "interviewing"]),
                )
            )
            responded = result.scalar() or 0
            response_rate = responded / total_apps

    return calculate_ghost_score(
        job=job,
        repost_count=repost_count,
        company_listing_count=company_listing_count,
        company_hire_count=company_hire_count,
        response_rate=response_rate,
    )


async def score_url(url: str) -> dict[str, Any]:
    """Score a job URL without requiring it to be in the DB.

    Uses ATS API to check posting status — no TinyFish needed.
    Works for Greenhouse, Lever, and Ashby URLs.
    """
    from app.services.apply.ats_url_parser import parse_ats_url

    url_info = parse_ats_url(url)
    if not url_info:
        # No ATS API available — use TinyFish to check if page is live
        return await _check_url_via_browser(url)

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if url_info.ats_type == "greenhouse":
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{url_info.board_token}/jobs/{url_info.job_id}"
                resp = await client.get(api_url)

                if resp.status_code == 404:
                    return {
                        "score": 90,
                        "risk": "high",
                        "badge": "ghost_risk",
                        "factors": ["Job posting not found — may have been removed"],
                    }

                if resp.status_code == 200:
                    data = resp.json()
                    # Check posting date
                    updated_at = data.get("updated_at", "")
                    title = data.get("title", "")

                    factors = [f"Verified active on Greenhouse: {title}"]
                    score = 10  # Base low score for verified posting

                    if updated_at:
                        try:
                            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                            age = (datetime.now(timezone.utc) - updated).days
                            if age > 90:
                                score += 25
                                factors.append(f"Last updated {age} days ago")
                            elif age > 60:
                                score += 15
                                factors.append(f"Last updated {age} days ago")
                            elif age <= 14:
                                score -= 5
                                factors.append(f"Recently updated ({age} days ago)")
                        except Exception:
                            pass

                    # Check number of questions (real jobs tend to have custom questions)
                    questions = data.get("questions") or []
                    if len(questions) >= 3:
                        score -= 5
                        factors.append(f"{len(questions)} custom questions — suggests active hiring")

                    # Hiring velocity — count total open roles at this company
                    try:
                        board_url = f"https://boards-api.greenhouse.io/v1/boards/{url_info.board_token}/jobs"
                        board_resp = await client.get(board_url)
                        if board_resp.status_code == 200:
                            board_data = board_resp.json()
                            total_roles = len(board_data.get("jobs") or [])
                            if total_roles > 20:
                                score -= 5
                                factors.append(f"{total_roles} open roles — actively hiring")
                            elif total_roles > 5:
                                factors.append(f"{total_roles} open roles at this company")
                            elif total_roles <= 2:
                                score += 10
                                factors.append(f"Only {total_roles} open role(s) — limited hiring")
                    except Exception:
                        pass

                    score = max(0, min(100, score))
                    risk = "high" if score >= 60 else "medium" if score >= 30 else "low"
                    badge = "ghost_risk" if score >= 60 else "caution" if score >= 30 else "verified"

                    return {"score": score, "risk": risk, "badge": badge, "factors": factors}

            elif url_info.ats_type == "lever":
                api_url = f"https://api.lever.co/v0/postings/{url_info.board_token}/{url_info.job_id}"
                resp = await client.get(api_url)

                if resp.status_code == 404:
                    return {
                        "score": 90,
                        "risk": "high",
                        "badge": "ghost_risk",
                        "factors": ["Job posting not found on Lever — may have been removed"],
                    }

                if resp.status_code == 200:
                    data = resp.json()
                    created_at = data.get("createdAt", 0)
                    factors = [f"Verified active on Lever: {data.get('text', '')}"]
                    score = 10

                    if created_at:
                        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)).days
                        if age > 90:
                            score += 25
                            factors.append(f"Posted {age} days ago")
                        elif age <= 14:
                            score -= 5
                            factors.append(f"Recently posted ({age} days ago)")

                    # Hiring velocity — count total open roles
                    try:
                        company_url = f"https://api.lever.co/v0/postings/{url_info.board_token}"
                        company_resp = await client.get(company_url)
                        if company_resp.status_code == 200:
                            all_postings = company_resp.json()
                            total_roles = len(all_postings) if isinstance(all_postings, list) else 0
                            if total_roles > 20:
                                score -= 5
                                factors.append(f"{total_roles} open roles — actively hiring")
                            elif total_roles > 5:
                                factors.append(f"{total_roles} open roles at this company")
                            elif total_roles <= 2:
                                score += 10
                                factors.append(f"Only {total_roles} open role(s) — limited hiring")
                    except Exception:
                        pass

                    score = max(0, min(100, score))
                    risk = "high" if score >= 60 else "medium" if score >= 30 else "low"
                    badge = "ghost_risk" if score >= 60 else "caution" if score >= 30 else "verified"

                    return {"score": score, "risk": risk, "badge": badge, "factors": factors}

            elif url_info.ats_type == "ashby":
                api_url = "https://api.ashbyhq.com/posting-api/posting-info"
                resp = await client.post(api_url, json={"postingId": url_info.job_id})

                if resp.status_code != 200:
                    return {
                        "score": 80,
                        "risk": "high",
                        "badge": "ghost_risk",
                        "factors": ["Job posting not found on Ashby"],
                    }

                data = resp.json()
                info = data.get("info") or data
                factors = [f"Verified active on Ashby: {info.get('title', '')}"]
                return {"score": 10, "risk": "low", "badge": "verified", "factors": factors}

    except Exception as e:
        logger.warning("Ghost check URL failed: %s", str(e)[:200])
        return {
            "score": 50,
            "risk": "medium",
            "badge": "caution",
            "factors": [f"Could not verify: {str(e)[:100]}"],
        }

    return {"score": 50, "risk": "medium", "badge": "caution", "factors": ["Verification inconclusive"]}


async def _check_url_via_browser(url: str) -> dict[str, Any]:
    """Check any job URL using 3 parallel TinyFish agents.

    Agent 1: Is the posting page still live?
    Agent 2: How many open roles does this company have?
    Agent 3: Has this job been posted before (repost detection)?

    Works for ALL job boards — Workday, iCIMS, custom career pages, etc.
    """
    import asyncio
    import json as _json
    from urllib.parse import urlparse

    from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE

    domain = urlparse(url).netloc or "unknown"

    # Extract a rough company/title hint from the URL for search agents
    path_parts = [p for p in urlparse(url).path.split("/") if p and len(p) > 2]
    url_hint = " ".join(path_parts[:3]).replace("-", " ").replace("_", " ")

    sources = [
        {
            "name": "posting_check",
            "url": url,
            "goal": (
                "Is this job posting still active? "
                "Copy the job title and company name. "
                'Return JSON: {"active": true, "title": "...", "company": "..."} '
                'or {"active": false} if filled, expired, or not found.'
            ),
        },
        {
            "name": "hiring_velocity",
            "url": f"https://www.google.com/search?q=site:{domain}+careers+open+roles",
            "goal": (
                f"How many open job listings does this company have on {domain}? "
                'Return JSON: {"open_roles": 0, "company": "..."}'
            ),
        },
        {
            "name": "repost_check",
            "url": f"https://www.google.com/search?q={url_hint}+job+site:{domain}",
            "goal": (
                f"Has this job been posted before? Search for: {url_hint}. "
                "Check if there are multiple listings for the same role. "
                'Return JSON: {"reposted": true/false, "count": 1}'
            ),
        },
    ]

    results: dict[str, dict] = {}

    async def _run(source: dict) -> tuple[str, dict]:
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
                    raw = result.result if isinstance(result.result, str) else _json.dumps(result.result)
                    try:
                        data = _json.loads(raw)
                        if isinstance(data, dict) and "result" in data and isinstance(data["result"], str):
                            data = _json.loads(data["result"])
                        return (source["name"], data if isinstance(data, dict) else {})
                    except (ValueError, TypeError):
                        return (source["name"], {})
                return (source["name"], {})
            except Exception as e:
                logger.warning("Ghost agent '%s' failed: %s", source["name"], str(e)[:200])
                return (source["name"], {})

    gathered = await asyncio.gather(*[_run(s) for s in sources])
    for name, data in gathered:
        results[name] = data

    # Combine signals into a ghost score
    score = 0
    factors: list[str] = []

    # Signal 1: Is the posting active?
    posting = results.get("posting_check", {})
    title = posting.get("title", "")
    company = posting.get("company", "")

    if posting.get("active") is False:
        score += 40
        factors.append("Posting appears to be removed or filled")
    elif title:
        factors.append(f"Verified active: {title}")
        if company:
            factors.append(f"Company: {company}")

    # Signal 2: Hiring velocity
    velocity = results.get("hiring_velocity", {})
    open_roles = velocity.get("open_roles", -1)
    if isinstance(open_roles, int) and open_roles >= 0:
        if open_roles == 0:
            score += 20
            factors.append("No other open roles found — low hiring activity")
        elif open_roles > 50:
            score -= 5
            factors.append(f"{open_roles} open roles — active hiring")
        else:
            factors.append(f"{open_roles} open roles at this company")

    # Signal 3: Repost detection
    repost = results.get("repost_check", {})
    if repost.get("reposted"):
        repost_count = repost.get("count", 2)
        if repost_count >= 3:
            score += 25
            factors.append(f"Job reposted {repost_count} times — classic ghost pattern")
        else:
            score += 10
            factors.append("Similar listing found — possible repost")

    score = max(0, min(100, score))
    risk = "high" if score >= 60 else "medium" if score >= 30 else "low"
    badge = "ghost_risk" if score >= 60 else "caution" if score >= 30 else "verified"

    if not factors:
        factors.append("Limited data available — check manually")

    return {"score": score, "risk": risk, "badge": badge, "factors": factors}
