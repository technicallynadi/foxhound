"""TinyFish team page lookup — find the actual hiring manager name.

Navigates to the company's team/about/people page and searches for
the manager of the specific department from the job posting.

This is a BACKGROUND ENRICHMENT — the user sees Claude's analysis instantly,
and if TinyFish finds an actual name, it updates the result.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 45-second timeout — shorter than Recon since this is enrichment, not primary
_TIMEOUT_S = 45


async def lookup_team_page(
    company_name: str,
    company_url: str | None,
    department: str,
    likely_title: str,
) -> dict[str, Any] | None:
    """Search a company's team/people page for the hiring manager.

    Returns dict with {name, title, team, source_url} or None if not found.
    """
    from tinyfish import BrowserProfile

    from app.services.ingest.tinyfish_adapter import _get_client

    if not company_url:
        # Try common URL patterns
        slug = company_name.lower().replace(" ", "").replace(",", "").replace(".", "")
        start_url = f"https://www.{slug}.com/about"
    else:
        start_url = company_url.rstrip("/")

    goal = (
        f"Navigate to {start_url}/team or {start_url}/about or {start_url}/people. "
        f"Find the person who manages the {department} team. "
        f"Look for titles containing '{likely_title}', 'Head of {department}', "
        f"'Director of {department}', or 'VP of {department}'. "
        f"Return ONLY the manager-level person for this specific team — "
        f"not individual contributors or unrelated departments. "
        f"Return JSON: "
        f'{{"name": "string", "title": "string", "team": "{department}", "found": true}} '
        f"or if not found: "
        f'{{"found": false, "reason": "string"}}'
    )

    try:
        client = _get_client()
        result = await asyncio.wait_for(
            client.agent.run(
                goal=goal,
                url=start_url,
                browser_profile=BrowserProfile.LITE,
            ),
            timeout=_TIMEOUT_S,
        )

        from tinyfish import RunStatus
        if result.status == RunStatus.COMPLETED and result.result:
            data = result.result if isinstance(result.result, dict) else {}
            if not data and isinstance(result.result, str):
                try:
                    data = json.loads(result.result)
                except (json.JSONDecodeError, TypeError):
                    return None

            if data.get("found"):
                logger.info(
                    "Pathfinder found manager for %s/%s: %s (%s)",
                    company_name, department, data.get("name"), data.get("title"),
                )
                return {
                    "name": data.get("name", ""),
                    "title": data.get("title", ""),
                    "team": data.get("team", department),
                    "source": "company_team_page",
                    "source_url": start_url,
                }

            logger.info("Pathfinder: no manager found on team page for %s/%s", company_name, department)
            return None

        return None

    except TimeoutError:
        logger.warning("Pathfinder team lookup timed out for %s (%ds)", company_name, _TIMEOUT_S)
        return None
    except Exception as e:
        error_str = str(e)
        if "RATE_LIMIT_EXCEEDED" in error_str:
            logger.warning("Pathfinder: TinyFish rate limited for %s", company_name)
        elif "INSUFFICIENT_CREDITS" in error_str:
            logger.warning("Pathfinder: TinyFish credits exhausted")
        else:
            logger.warning("Pathfinder team lookup failed for %s: %s", company_name, error_str[:200])
        return None
