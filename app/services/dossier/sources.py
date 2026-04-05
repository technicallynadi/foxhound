"""TinyFish source fetchers for company dossiers.

5 parallel sources that run in the background after a user applies.
Each returns a dict on success or None on failure.
TinyFish imports are LAZY (inside functions).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# No timeout — let TinyFish finish. We'll add a reasonable one back
# once we know how long sources actually take.
SOURCE_TIMEOUT = None
RETRY_DELAY = 3


# ---------------------------------------------------------------------------
# Source 1: Company about page
# ---------------------------------------------------------------------------


async def fetch_company_page(
    company_name: str, company_url: str | None
) -> dict[str, Any] | None:
    """Scrape a company's about page for overview data.

    Returns dict with mission, founded, size, locations, funding, products
    or None on failure.
    """

    if company_url:
        start_url = company_url.rstrip("/")
    else:
        start_url = f"https://www.google.com/search?q={company_name}+about"

    goal = (
        f"Go to {start_url}/about or the company main page. "
        "Copy ALL visible text on the page — mission, founding year, employee count, "
        "office locations, funding, investors, products, leadership. Return the raw text."
    )

    return await _run_source("company", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 2: Careers page
# ---------------------------------------------------------------------------


async def fetch_careers_page(
    company_name: str, company_url: str | None
) -> dict[str, Any] | None:
    """Scrape a company's careers page for hiring signals.

    Returns dict with open_roles, top_departments, hiring_velocity
    or None on failure.
    """
    if company_url:
        start_url = company_url.rstrip("/")
    else:
        start_url = f"https://www.google.com/search?q={company_name}+careers"

    goal = (
        f"Go to {start_url}/careers or search '{company_name} careers'. "
        "Copy ALL visible text — job titles, departments, locations, number of open roles. "
        "Return the raw text from the careers page."
    )

    return await _run_source("careers", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 3: News search
# ---------------------------------------------------------------------------


async def fetch_news(company_name: str) -> dict[str, Any] | None:
    """Search for recent company news headlines.

    Returns dict with headlines list or None on failure.
    """
    start_url = f"https://www.google.com/search?q={company_name}+news&tbm=nws"

    goal = (
        f"Find the 5 most recent news articles about {company_name}. "
        "For each result, copy the headline, source name, date, and snippet. "
        "Return all the text you see on the search results page."
    )

    return await _run_source("news", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 4: Team/people page
# ---------------------------------------------------------------------------


async def fetch_team_page(
    company_name: str,
    company_url: str | None,
    department: str | None = None,
) -> dict[str, Any] | None:
    """Scrape a company's team/people page for contacts in the relevant department.

    Returns dict with contacts list or None on failure.
    """
    dept_hint = department or "engineering"
    if company_url:
        start_url = company_url.rstrip("/")
    else:
        start_url = f"https://www.google.com/search?q={company_name}+team+{dept_hint}"

    goal = (
        f"Find people at {company_name} in {dept_hint}. "
        "Try the company website team page, about page, or LinkedIn search. "
        "Copy all names, titles, and departments you find. Return the raw text."
    )

    return await _run_source("team", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 5: Glassdoor (best effort)
# ---------------------------------------------------------------------------


async def fetch_glassdoor(company_name: str) -> dict[str, Any] | None:
    """Scrape Glassdoor for company rating and sentiment. Best effort.

    Uses STEALTH profile with proxy since Glassdoor blocks bots aggressively.
    Returns dict with rating, ceo_approval, pros, cons or None on failure.
    """
    from tinyfish import BrowserProfile, ProxyConfig, ProxyCountryCode, RunStatus

    from app.services.ingest.tinyfish_adapter import _get_client

    start_url = f"https://www.google.com/search?q={company_name}+glassdoor+reviews"

    goal = (
        f"Find {company_name} on Glassdoor. "
        "Copy ALL visible text — overall rating, CEO approval, pros, cons from reviews, "
        "interview reviews, salary data. Return everything you see."
    )

    # Glassdoor requires STEALTH + proxy from the start
    try:
        client = _get_client()
        result = await client.agent.run(
            goal=goal,
            url=start_url,
            browser_profile=BrowserProfile.STEALTH,
            proxy_config=ProxyConfig(
                enabled=True, country_code=ProxyCountryCode.US
            ),
        )

        if result.status == RunStatus.COMPLETED and result.result:
            return _parse_result(result.result)

        logger.warning("Glassdoor fetch failed for %s: %s", company_name, getattr(result, "error", "unknown"))
        return None

    except Exception as e:
        _log_tinyfish_error("glassdoor", company_name, e)
        return None


# ---------------------------------------------------------------------------
# Source 6: Reddit interview experiences
# ---------------------------------------------------------------------------


async def fetch_reddit_interviews(company_name: str) -> dict[str, Any] | None:
    """Search Reddit for interview experience posts about the company.

    Returns dict with posts list or None on failure.
    """
    start_url = (
        f"https://www.google.com/search?q=site:reddit.com+{company_name}"
        f"+interview+experience"
    )

    goal = (
        f"Find Reddit posts about interview experiences at {company_name}. "
        "Click into the most relevant 2-3 posts and copy the text content — "
        "interview stages, questions asked, difficulty, tips. Return all the text."
    )

    return await _run_source("reddit_interviews", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 7: Reddit company culture
# ---------------------------------------------------------------------------


async def fetch_reddit_culture(company_name: str) -> dict[str, Any] | None:
    """Search Reddit for work culture and WLB posts about the company.

    Returns dict with posts list or None on failure.
    """
    start_url = (
        f"https://www.google.com/search?q=site:reddit.com+{company_name}"
        f"+work+culture+OR+wlb+OR+%22work+life%22"
    )

    goal = (
        f"Find Reddit posts about working at {company_name}. "
        "Click into the most relevant 2-3 posts and copy the text — "
        "work-life balance, management, compensation, culture. Return all the text."
    )

    return await _run_source("reddit_culture", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 8: Engineering blog / tech articles
# ---------------------------------------------------------------------------


async def fetch_engineering_blog(
    company_name: str, company_url: str | None
) -> dict[str, Any] | None:
    """Search for the company's engineering blog or recent tech articles.

    Returns dict with blog URL and posts list or None on failure.
    """
    start_url = (
        f"https://www.google.com/search?q=%22{company_name.replace(' ', '+')}%22"
        f"+company+linkedin+OR+about+OR+blog"
    )

    goal = (
        f"Search for {company_name} company LinkedIn page or blog. "
        "Go to the most relevant result. "
        "Copy all visible text — company description, employee count, recent posts, "
        "technologies, any articles or updates. Return all the text."
    )

    return await _run_source("engineering_blog", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Source 9: Levels.fyi salary data
# ---------------------------------------------------------------------------


async def fetch_levels_fyi(
    company_name: str, job_title: str | None = None
) -> dict[str, Any] | None:
    """Scrape levels.fyi for compensation data at the company.

    Returns dict with salary ranges, levels, and total comp or None on failure.
    """
    title_hint = job_title or "Software Engineer"
    start_url = f"https://www.levels.fyi/companies/{company_name.lower().replace(' ', '-')}/salaries/{title_hint.lower().replace(' ', '-')}"

    goal = (
        f"Go to levels.fyi and find salary/compensation data for {title_hint} at {company_name}. "
        f"If the direct URL doesn't work, search for '{company_name}' on levels.fyi. "
        "Copy ALL visible salary data — base salary, total comp, stock, bonus, "
        "compensation by level. Return all the text and numbers you see."
    )

    return await _run_source("levels_fyi", company_name, start_url, goal)


# ---------------------------------------------------------------------------
# Shared runner: LITE first, retry STEALTH on failure
# ---------------------------------------------------------------------------


async def _run_source(
    source_name: str,
    company_name: str,
    start_url: str,
    goal: str,
) -> dict[str, Any] | None:
    """Run a TinyFish source with LITE, retry STEALTH+proxy on failure."""
    from tinyfish import BrowserProfile, RunStatus

    from app.services.ingest.tinyfish_adapter import _get_client

    client = _get_client()

    # Attempt 1: LITE (no timeout — let TinyFish finish)
    try:
        result = await client.agent.run(
            goal=goal,
            url=start_url,
            browser_profile=BrowserProfile.LITE,
        )

        if result.status == RunStatus.COMPLETED and result.result:
            data = _parse_result(result.result)
            if data:
                logger.info("%s fetch OK for %s", source_name, company_name)
                return data

    except Exception as e:
        _log_tinyfish_error(source_name, company_name, e)

    # Attempt 2: STEALTH + proxy
    try:
        await asyncio.sleep(RETRY_DELAY)
        from tinyfish import ProxyConfig, ProxyCountryCode

        result = await client.agent.run(
            goal=goal,
            url=start_url,
            browser_profile=BrowserProfile.STEALTH,
            proxy_config=ProxyConfig(
                enabled=True, country_code=ProxyCountryCode.US
            ),
        )

        if result.status == RunStatus.COMPLETED and result.result:
            data = _parse_result(result.result)
            if data:
                logger.info("%s STEALTH fetch OK for %s", source_name, company_name)
                return data

        logger.warning("%s STEALTH also failed for %s", source_name, company_name)
        return None

    except Exception as e:
        _log_tinyfish_error(source_name, company_name, e)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_result(raw: Any) -> dict[str, Any] | None:
    """Parse TinyFish result into a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"raw": raw[:5000]} if raw else None
    return None


def _log_tinyfish_error(source: str, company: str, error: Exception) -> None:
    """Classify and log TinyFish errors."""
    error_str = str(error)
    if "RATE_LIMIT_EXCEEDED" in error_str:
        logger.warning("TinyFish rate limited on %s for %s", source, company)
    elif "INSUFFICIENT_CREDITS" in error_str:
        logger.error("TinyFish credits exhausted on %s for %s", source, company)
    else:
        logger.warning("TinyFish error on %s for %s: %s", source, company, error_str[:200])
