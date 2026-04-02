"""Per-user TinyFish job discovery.

Runs small, focused TinyFish goals based on each user's target roles
and preferences. Found jobs are deduped and added to the main job board.

Flow:
1. Build 1-2 small search goals from the user's profile
2. TinyFish searches Google/Greenhouse/Lever (one goal at a time)
3. Parse results into structured job data
4. Dedup against existing listings (by URL and by company+title+location hash)
5. Store new listings in job_listings table
6. Score them against the user's profile
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.db.session import async_session
from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)


async def discover_for_user(user_id: str) -> int:
    """Run TinyFish discovery for a single user. Returns count of new jobs found."""
    async with async_session() as db:
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return 0

        titles = json.loads(profile.target_titles_json or "[]")
        locations = json.loads(profile.target_locations_json or "[]")
        remote_pref = profile.remote_preference or "any"

        if not titles:
            logger.info("TinyFish discovery: user %s has no target titles, skipping", user_id)
            return 0

        # Build small, focused search goals — one per title (max 2)
        goals = _build_search_goals(titles[:2], locations[:1], remote_pref)

        total_new = 0
        for goal in goals:
            try:
                jobs = await _run_tinyfish_search(goal)
                if jobs:
                    new_count = await _ingest_jobs(db, jobs)
                    total_new += new_count
                    logger.info(
                        "TinyFish discovery for %s: goal='%s' found=%d new=%d",
                        user_id, goal["query"][:50], len(jobs), new_count,
                    )
            except Exception:
                logger.exception("TinyFish discovery failed for goal: %s", goal["query"][:50])

        # Score new jobs against this user
        if total_new > 0:
            try:
                from app.services.matching.scorer import MatchScorer
                scorer = MatchScorer()
                await scorer.score_jobs_for_user(db, user_id)
            except Exception:
                logger.exception("Scoring failed after TinyFish discovery for %s", user_id)

        await db.commit()

    # Log activity
    if total_new > 0:
        from app.services.activity.logger import log_activity
        await log_activity(
            user_id=user_id,
            event_type="matches_discovered",
            title=f"Found {total_new} new jobs from the web",
            description="Foxhound searched beyond saved job boards for roles matching your profile.",
            metadata={"count": total_new, "source": "tinyfish_discovery"},
        )

    return total_new


def _build_search_goals(
    titles: list[str],
    locations: list[str],
    remote_pref: str,
) -> list[dict]:
    """Build small, focused TinyFish search goals from user preferences.

    Only searches sources that our API board crawl doesn't cover:
    Google, Reddit, company career pages, niche job boards.
    NOT Greenhouse/Lever/Ashby — those are already crawled via API.
    """
    goals = []

    location_hint = locations[0] if locations else ""
    if remote_pref == "remote":
        location_hint = "remote"

    # Use the first target title for focused searches
    title = titles[0] if titles else "software engineer"
    query = f"{title} {location_hint}".strip()

    # Goal 1: Google — find job postings on company career pages
    goals.append({
        "query": query,
        "url": f"https://www.google.com/search?q={query.replace(' ', '+')}+hiring+apply+2026",
        "goal": (
            f"Find 3-5 open positions for '{title}'"
            f"{f' in {location_hint}' if location_hint else ''}. "
            "Skip any results from boards.greenhouse.io, jobs.lever.co, or jobs.ashbyhq.com. "
            "Click into the top 3 most relevant results. "
            "For each real job posting, extract: job title, company name, location, and the direct apply URL. "
            'Return as JSON array: [{"title": "...", "company": "...", "location": "...", "apply_url": "..."}]'
        ),
    })

    # Goal 2: Reddit — find who's hiring threads and job posts
    goals.append({
        "query": query,
        "url": f"https://www.google.com/search?q=site:reddit.com+{title.replace(' ', '+')}+hiring+2026",
        "goal": (
            f"Find Reddit posts about companies hiring for '{title}' roles"
            f"{f' in {location_hint}' if location_hint else ''}. "
            "Look for 'Who is hiring' threads, job postings, and hiring announcements. "
            "Click into 2-3 relevant threads. Extract any job opportunities mentioned: "
            "job title, company name, location, and apply URL if available. "
            'Return as JSON array: [{"title": "...", "company": "...", "location": "...", "apply_url": "..."}]'
        ),
    })

    return goals


async def _run_tinyfish_search(goal: dict) -> list[dict]:
    """Run a single TinyFish search goal. Returns parsed job dicts."""
    from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE

    async with TINYFISH_SEMAPHORE:
        try:
            from tinyfish import BrowserProfile, RunStatus
            from app.services.ingest.tinyfish_adapter import _get_client

            client = _get_client()
            result = await client.agent.run(
                goal=goal["goal"],
                url=goal["url"],
                browser_profile=BrowserProfile.LITE,
            )

            if result.status == RunStatus.COMPLETED and result.result:
                raw = result.result if isinstance(result.result, str) else json.dumps(result.result)
                return _parse_results(raw)
            return []
        except Exception as e:
            logger.warning("TinyFish search failed: %s", str(e)[:200])
            return []


def _parse_results(raw: str) -> list[dict]:
    """Parse TinyFish output into structured job dicts."""
    import re

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [j for j in data if isinstance(j, dict) and j.get("title") and j.get("apply_url")]
        if isinstance(data, dict) and data.get("result"):
            inner = data["result"]
            if isinstance(inner, str):
                return _parse_results(inner)
            if isinstance(inner, list):
                return [j for j in inner if isinstance(j, dict) and j.get("title") and j.get("apply_url")]
    except json.JSONDecodeError:
        pass

    # Try extracting JSON array from text
    match = re.search(r'\[[\s\S]*\]', raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [j for j in data if isinstance(j, dict) and j.get("title") and j.get("apply_url")]
        except json.JSONDecodeError:
            pass

    return []


async def _ingest_jobs(db: AsyncSession, jobs: list[dict]) -> int:
    """Dedup and store discovered jobs. Returns count of new jobs added."""
    from app.services.discovery.ats_detector import detect_ats

    new_count = 0

    for job_data in jobs:
        apply_url = (job_data.get("apply_url") or "").strip()
        title = (job_data.get("title") or "").strip()
        company = (job_data.get("company") or "").strip()
        location = (job_data.get("location") or "").strip()

        if not apply_url or not title:
            continue

        # Dedup 1: exact URL match
        url_check = await db.execute(
            select(JobListing.id).where(JobListing.apply_url == apply_url).limit(1)
        )
        if url_check.scalar_one_or_none():
            continue

        # Dedup 2: company + title + location hash match
        dedup_hash = compute_dedup_hash(company, title, location)
        hash_check = await db.execute(
            select(JobListing.id).where(JobListing.dedup_hash == dedup_hash).limit(1)
        )
        if hash_check.scalar_one_or_none():
            continue

        # Detect ATS type from URL
        ats_type = detect_ats(apply_url)

        listing = JobListing(
            id=str(uuid4()),
            title=title,
            company=company,
            location=location,
            apply_url=apply_url,
            description=(job_data.get("description") or "")[:5000],
            salary_text=job_data.get("salary"),
            source="tinyfish_discovery",
            ats_type=ats_type,
            status="active",
            dedup_hash=dedup_hash,
            discovered_at=datetime.now(timezone.utc),
        )
        db.add(listing)
        new_count += 1

    if new_count:
        await db.flush()

    return new_count
