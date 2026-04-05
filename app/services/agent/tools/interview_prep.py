"""Interview prep tool: TinyFish-powered interview question scraper.

Runs multiple small TinyFish agents in parallel — each focused on one
source (Glassdoor, Reddit, LeetCode, Blind) to avoid timeout issues.
Returns company-specific interview questions, experiences, and tips.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool
from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE

logger = logging.getLogger(__name__)


@tool(
    name="interview_prep",
    description=(
        "Research interview questions and experiences for a specific company using "
        "TinyFish. Scrapes Glassdoor, Reddit, LeetCode, and Blind in parallel for "
        "company-specific interview data. Use when the user says 'help me prepare "
        "for an interview at [company]', 'what questions does [company] ask', "
        "'interview prep for [company]', or 'what's the interview process at [company]'. "
        "Returns interview stages, common questions, difficulty, and tips from "
        "real candidate experiences."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "Company name to research",
            },
            "role": {
                "type": "string",
                "description": "Specific role (e.g. 'Senior Frontend Engineer')",
            },
            "job_id": {
                "type": "string",
                "description": "Job ID to pull role details from (optional)",
            },
        },
        "required": ["company_name"],
    },
    permissions=["read"],
    side_effects=True,
    cost_estimate="high",
)
async def interview_prep_search(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Run parallel TinyFish agents to gather interview intel."""
    company = params.get("company_name", "").strip()
    role = params.get("role", "")
    job_id = params.get("job_id")

    if not company:
        return {"error": "missing_company", "message": "Please specify a company name."}

    # Get role from job listing if provided
    if job_id and not role:
        job_result = await db.execute(
            select(JobListing).where(JobListing.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            role = job.title or ""

    # Load user profile to tailor interview search

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    # Determine interview type from profile
    interview_type = "general"
    search_focus = "interview questions experience"
    if profile:
        if not role:
            targets = json.loads(profile.target_titles_json or "[]")
            if targets:
                role = targets[0]

        role_lower = (role or "").lower()
        skills = json.loads(profile.skills_json or "[]")
        [s.lower() for s in skills]

        # Detect interview type from role + skills
        if any(kw in role_lower for kw in ["engineer", "developer", "swe", "backend", "frontend", "fullstack"]):
            interview_type = "technical"
            search_focus = "technical interview coding system design"
        elif any(kw in role_lower for kw in ["design", "ux", "ui"]):
            interview_type = "design"
            search_focus = "design interview portfolio review case study"
        elif any(kw in role_lower for kw in ["product", "pm", "program"]):
            interview_type = "product"
            search_focus = "product interview case study estimation metrics"
        elif any(kw in role_lower for kw in ["data", "analyst", "science", "ml", "ai"]):
            interview_type = "data"
            search_focus = "data science interview sql machine learning statistics"
        elif any(kw in role_lower for kw in ["marketing", "growth"]):
            interview_type = "marketing"
            search_focus = "marketing interview campaign strategy analytics"
        elif any(kw in role_lower for kw in ["sales", "account", "business development"]):
            interview_type = "sales"
            search_focus = "sales interview pitch objection handling"
        elif any(kw in role_lower for kw in ["manager", "director", "lead", "head"]):
            interview_type = "leadership"
            search_focus = "management interview leadership behavioral"

    role_hint = f" for {role}" if role else ""
    logger.info("Interview prep for %s: type=%s, role=%s", company, interview_type, role or "general")

    # Step 1: Try Reddit API first (free, instant, structured)
    from app.services.discovery.adapters.reddit import search_company_interviews

    reddit_data = None
    try:
        reddit_query = f"{company} {role}" if role else company
        reddit_data = await search_company_interviews(reddit_query)
        if reddit_data.get("posts_found", 0) > 0:
            logger.info("Reddit API: found %d interview posts for %s", reddit_data["posts_found"], company)
    except Exception as e:
        logger.warning("Reddit API failed for %s: %s", company, str(e)[:200])

    # Step 2: TinyFish for interview sources that don't have APIs
    # Each agent does ONE simple thing: Google search → click 1-2 results → copy text
    # Search terms are tailored to the user's interview type
    sources = [
        {
            "name": "interview_reviews",
            "url": f"https://www.google.com/search?q={company.replace(' ', '+')}+{search_focus.replace(' ', '+')}",
            "goal": (
                f"From the Google results, find interview reviews for {company}{role_hint}. "
                "Click the top 1-2 results. Copy the interview questions, "
                "difficulty rating, and process description. Return all text."
            ),
        },
        {
            "name": "role_questions",
            "url": f"https://www.google.com/search?q={company.replace(' ', '+')}+{(role or 'interview').replace(' ', '+')}+questions",
            "goal": (
                f"From the Google results, find {interview_type} interview questions for {company}{role_hint}. "
                "Click the top 1-2 results. Copy the specific questions asked "
                "and any preparation advice. Return all text."
            ),
        },
        {
            "name": "salary_offers",
            "url": f"https://www.google.com/search?q={company.replace(' ', '+')}+{(role or 'offer').replace(' ', '+')}+compensation+salary",
            "goal": (
                f"From the Google results, find posts about {company} compensation{role_hint}. "
                "Click the top 1-2 results. Copy salary numbers, levels, "
                "and negotiation tips. Return all text."
            ),
        },
    ]

    # Skip TinyFish Reddit if API already got data
    if reddit_data and reddit_data.get("posts_found", 0) > 0:
        sources = [s for s in sources if s["name"] != "reddit_interviews"]

    # Run TinyFish sources in parallel with semaphore
    results: dict[str, str | None] = {}

    async def _run_source(source: dict) -> tuple[str, str | None]:
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
                    text = result.result if isinstance(result.result, str) else json.dumps(result.result)
                    logger.info("Interview prep '%s' for %s: %d chars", source["name"], company, len(text))
                    return (source["name"], text)
                else:
                    logger.warning("Interview prep '%s' for %s: no result", source["name"], company)
                    return (source["name"], None)

            except Exception as e:
                logger.warning("Interview prep '%s' for %s failed: %s", source["name"], company, str(e)[:200])
                return (source["name"], None)

    gathered = await asyncio.gather(*[_run_source(s) for s in sources])
    for name, text in gathered:
        results[name] = text

    # Count successful sources
    successful = {k: v for k, v in results.items() if v}

    if not successful:
        return {
            "status": "no_data",
            "company": company,
            "message": f"Couldn't find interview data for {company}. The company may be too small or new for interview reviews.",
        }

    # Step 3: TinyFish micro-goals for course recommendations
    # Keep goals intentionally small: each task finds only 1-2 course candidates.
    course_sources = [
        {
            "name": "coursera_courses",
            "url": f"https://www.google.com/search?q=site:coursera.org+{company.replace(' ', '+')}+{(role or interview_type).replace(' ', '+')}+interview",
            "goal": (
                f"From these results, open up to 2 relevant courses for preparing a {role or interview_type} interview at {company}. "
                "Return ONLY a JSON array (max 2 items) with: "
                '[{"title":"...","provider":"Coursera","url":"...","reason":"one-line reason"}].'
            ),
        },
        {
            "name": "udemy_courses",
            "url": f"https://www.google.com/search?q=site:udemy.com+{(role or interview_type).replace(' ', '+')}+interview+prep",
            "goal": (
                f"From these results, open up to 2 relevant interview-prep courses for {role or interview_type}. "
                "Return ONLY a JSON array (max 2 items) with: "
                '[{"title":"...","provider":"Udemy","url":"...","reason":"one-line reason"}].'
            ),
        },
    ]

    course_raw = await asyncio.gather(*[_run_source(s) for s in course_sources])
    course_candidates: list[dict] = []
    for source_name, payload in course_raw:
        if not payload:
            continue
        parsed = _parse_course_results(payload)
        logger.info("Interview prep courses '%s' for %s: %d parsed", source_name, company, len(parsed))
        course_candidates.extend(parsed)

    # Deduplicate courses by URL/title
    seen_courses: set[tuple[str, str]] = set()
    courses: list[dict] = []
    for course in course_candidates:
        title = str(course.get("title", "")).strip()
        url = str(course.get("url", "")).strip()
        key = (title.lower(), url.lower())
        if not title or key in seen_courses:
            continue
        seen_courses.add(key)
        courses.append({
            "title": title,
            "provider": str(course.get("provider", "")).strip() or "Course platform",
            "url": url,
            "reason": str(course.get("reason", "")).strip(),
        })

    # Build structured response
    response: dict = {
        "status": "found",
        "company": company,
        "role": role or "General",
        "sources_found": list(successful.keys()),
        "sources_failed": [k for k, v in results.items() if v is None],
    }

    # Include Reddit API data (structured, with comments)
    if reddit_data and reddit_data.get("posts_found", 0) > 0:
        reddit_summary = []
        for post in reddit_data.get("posts", [])[:5]:
            entry = f"**{post['title']}** (score: {post['score']}, r/{post['subreddit']})\n{post['body'][:500]}"
            comments = post.get("top_comments", [])
            if comments:
                entry += "\nTop comments:\n" + "\n".join(
                    f"- {c['body'][:300]}" for c in comments[:3]
                )
            reddit_summary.append(entry)
        response["reddit"] = "\n\n---\n\n".join(reddit_summary)
        successful["reddit_api"] = True

    # Include TinyFish source data
    if successful.get("interview_reviews"):
        response["glassdoor"] = successful["interview_reviews"][:2000]
    if successful.get("role_questions"):
        response["coding_questions"] = successful["role_questions"][:2000]
    if successful.get("salary_offers"):
        response["salary_offers"] = successful["salary_offers"][:2000]

    if courses:
        response["courses"] = courses[:5]

    all_sources = list(successful.keys())
    if courses:
        all_sources.append("courses")
    response["message"] = (
        f"Found interview data for {company} from {len(all_sources)} sources "
        f"({', '.join(all_sources)}). "
        "I'll summarize the key findings for you."
    )

    return response


def _parse_course_results(raw: str) -> list[dict]:
    """Parse TinyFish output into course recommendations."""
    import re

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict) and c.get("title")]
        if isinstance(data, dict):
            inner = data.get("result")
            if isinstance(inner, list):
                return [c for c in inner if isinstance(c, dict) and c.get("title")]
            if isinstance(inner, str):
                return _parse_course_results(inner)
    except json.JSONDecodeError:
        pass

    # Fallback: pull JSON array from mixed text
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [c for c in data if isinstance(c, dict) and c.get("title")]
        except json.JSONDecodeError:
            pass

    return []
