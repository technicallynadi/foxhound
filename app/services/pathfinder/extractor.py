"""Claude Haiku extraction of hiring manager signals from job descriptions.

Analyzes the job posting text to identify department, likely manager title,
reporting structure clues, and seniority level of the hiring manager.
NO external API calls — everything derived from the job description already in DB.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a hiring-manager intelligence analyst. Given a job posting, extract \
signals about who the hiring manager likely is.

Return ONLY valid JSON with this exact structure:
{
  "department": "the team or department this role sits in (e.g. 'Platform Engineering', 'Product', 'Data Science')",
  "likely_title": "the most probable title of the hiring manager (e.g. 'Engineering Manager', 'VP of Engineering', 'Director of Product')",
  "team_size_hint": "any clues about team size from the posting, or 'unknown'",
  "seniority_of_manager": "estimated seniority: 'manager' | 'senior_manager' | 'director' | 'vp' | 'c_level'",
  "reporting_clues": "direct quotes or paraphrased clues about who this role reports to",
  "confidence": "high | medium | low"
}

Rules:
- department: look for explicit team names, department mentions, org structure clues
- likely_title: infer from the role level — a senior engineer likely reports to an \
Engineering Manager or Director; a manager role likely reports to a VP or Director
- team_size_hint: look for phrases like "team of 5", "growing team", "small team", \
headcount clues
- seniority_of_manager: derive from likely_title
- reporting_clues: extract any "reports to", "you'll work with", "team lead" mentions
- confidence: "high" if explicit reporting info found, "medium" if strong inference, \
"low" if mostly guessing
- If the posting says nothing useful for a field, use a reasonable inference, never \
leave fields empty"""


async def extract_manager_signals(
    job_title: str,
    company: str,
    description: str,
    seniority: str | None = None,
) -> dict[str, Any]:
    """Extract hiring manager signals from a job description using Claude Haiku.

    Returns a dict with department, likely_title, team_size_hint,
    seniority_of_manager, reporting_clues, and confidence.
    """
    user_content = (
        f"Job Title: {job_title}\n"
        f"Company: {company}\n"
        f"Seniority Level: {seniority or 'Not specified'}\n\n"
        f"FULL JOB DESCRIPTION:\n{description[:8000]}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            temperature=0.2,
            system=_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()

        from app.services.pathfinder.json_parser import extract_json

        result = extract_json(text)
        if not result or not isinstance(result, dict):
            logger.warning("Pathfinder extraction: could not parse JSON from response")
            return _fallback_extraction(job_title, company, seniority)

        logger.info(
            "Pathfinder extraction for %s @ %s — dept=%s, title=%s, confidence=%s",
            job_title,
            company,
            result.get("department"),
            result.get("likely_title"),
            result.get("confidence"),
        )
        return result

    except json.JSONDecodeError as e:
        logger.warning("Pathfinder extraction JSON parse failed: %s", e)
        return _fallback_extraction(job_title, company, seniority)
    except Exception as e:
        logger.warning("Pathfinder extraction API call failed: %s", str(e)[:200])
        return _fallback_extraction(job_title, company, seniority)


def _fallback_extraction(
    job_title: str,
    company: str,
    seniority: str | None,
) -> dict[str, Any]:
    """Build a best-guess extraction when Claude is unavailable."""
    title_lower = job_title.lower()

    # Infer department from job title keywords
    department = "Engineering"
    if any(kw in title_lower for kw in ("product", "pm", "program")):
        department = "Product"
    elif any(kw in title_lower for kw in ("design", "ux", "ui")):
        department = "Design"
    elif any(kw in title_lower for kw in ("data", "analytics", "ml", "machine learning")):
        department = "Data"
    elif any(kw in title_lower for kw in ("devops", "sre", "platform", "infra")):
        department = "Platform Engineering"
    elif any(kw in title_lower for kw in ("market", "growth")):
        department = "Marketing"
    elif any(kw in title_lower for kw in ("sales", "account")):
        department = "Sales"

    # Infer manager seniority from role seniority
    seniority_map = {
        "junior": ("manager", "Engineering Manager"),
        "mid": ("manager", "Engineering Manager"),
        "senior": ("director", f"Director of {department}"),
        "staff": ("director", f"Director of {department}"),
        "principal": ("vp", f"VP of {department}"),
        "lead": ("director", f"Director of {department}"),
        "manager": ("vp", f"VP of {department}"),
        "director": ("vp", f"VP of {department}"),
        "vp": ("c_level", "CTO" if department == "Engineering" else f"Chief {department} Officer"),
    }

    seniority_key = (seniority or "mid").lower()
    manager_seniority, likely_title = seniority_map.get(seniority_key, ("manager", f"{department} Manager"))

    return {
        "department": department,
        "likely_title": likely_title,
        "team_size_hint": "unknown",
        "seniority_of_manager": manager_seniority,
        "reporting_clues": "No explicit reporting structure found in posting.",
        "confidence": "low",
    }
