"""Claude Haiku outreach message drafting for hiring manager contact.

Generates a short LinkedIn connection request (300 chars) and a longer
email draft, personalized based on job posting, user profile, and
extracted overlap signals.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_OUTREACH_PROMPT = """\
You are a professional networking coach helping a job seeker reach out to a \
hiring manager. Draft two messages:

1. **linkedin_note**: A LinkedIn connection request (MUST be under 280 characters). \
Mention the specific role, one genuine overlap/connection point, and express \
interest without being desperate. No exclamation marks. Professional but warm.

2. **email_draft**: A short email (3-5 sentences). Subject line + body. \
Reference the specific role, highlight 1-2 relevant overlaps, and end with \
a soft ask (coffee chat, 15-min call, or insight about the team). \
Don't attach a resume — this is a warm intro, not an application.

Return ONLY valid JSON:
{
  "linkedin_note": "the connection request text (under 280 chars)",
  "email_subject": "concise email subject line",
  "email_body": "the email body text",
  "personalization_hooks": ["list", "of", "specific", "hooks", "used"]
}

Rules:
- Be specific to this role and company — no generic templates
- Reference the overlap/connection points provided
- Keep the tone professional but human — not robotic or sycophantic
- The linkedin_note MUST be under 280 characters (LinkedIn limit is 300, leave buffer)
- Never mention AI, automation, or that this message was generated
- The email should feel like it was written by a thoughtful human
- Include the user's name in the email sign-off"""


async def draft_outreach(
    job_title: str,
    company: str,
    description: str,
    manager_title: str,
    user_name: str,
    user_summary: str | None,
    overlap_summary: str,
    company_context: str | None = None,
    contacts_found: list[dict] | None = None,
) -> dict[str, Any]:
    """Draft personalized outreach messages using Claude Haiku.

    Args:
        job_title: The job posting title.
        company: Company name.
        description: Job description (truncated for context).
        manager_title: Extracted likely hiring manager title.
        user_name: User's full name for sign-off.
        user_summary: User's professional summary from profile.
        overlap_summary: One-liner from OverlapResult.summary_for_outreach().

    Returns:
        Dict with linkedin_note, email_subject, email_body, personalization_hooks.
    """
    parts = [
        f"ROLE: {job_title} at {company}",
        f"HIRING MANAGER (likely): {manager_title}",
        f"\nJOB DESCRIPTION (excerpt):\n{description[:3000]}",
    ]
    if company_context:
        parts.append(f"\nCOMPANY RESEARCH (from live web scrape):\n{company_context[:1500]}")
    if contacts_found:
        contact_lines = []
        for c in contacts_found[:5]:
            line = f"- {c.get('name', 'Unknown')} — {c.get('title', '')}"
            if c.get('connection_angle'):
                line += f" (connection: {c['connection_angle']})"
            contact_lines.append(line)
        parts.append(f"\nCONTACTS FOUND AT {company.upper()} (from LinkedIn):\n" + "\n".join(contact_lines))
    parts.extend([
        f"\nCANDIDATE NAME: {user_name}",
        f"CANDIDATE SUMMARY: {user_summary or 'Not provided'}",
        f"\nOVERLAP/CONNECTION POINTS: {overlap_summary}",
    ])
    user_content = "\n".join(parts)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            temperature=0.7,
            system=_OUTREACH_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()

        from app.services.pathfinder.json_parser import extract_json
        result = extract_json(text)
        if not result or not isinstance(result, dict):
            logger.warning("Pathfinder outreach: could not parse JSON from response")
            return _fallback_outreach(job_title, company, manager_title, user_name, overlap_summary)

        # Enforce LinkedIn character limit
        note = result.get("linkedin_note", "")
        if len(note) > 300:
            result["linkedin_note"] = note[:297] + "..."
            logger.warning("LinkedIn note truncated from %d chars", len(note))

        logger.info(
            "Pathfinder outreach drafted for %s @ %s — hooks=%s",
            job_title, company, result.get("personalization_hooks", []),
        )
        return result

    except json.JSONDecodeError as e:
        logger.warning("Pathfinder outreach JSON parse failed: %s", e)
        return _fallback_outreach(job_title, company, manager_title, user_name, overlap_summary)
    except Exception as e:
        logger.warning("Pathfinder outreach API call failed: %s", str(e)[:200])
        return _fallback_outreach(job_title, company, manager_title, user_name, overlap_summary)


def _fallback_outreach(
    job_title: str,
    company: str,
    manager_title: str,
    user_name: str,
    overlap_summary: str,
) -> dict[str, Any]:
    """Generate a basic outreach template when Claude is unavailable."""
    linkedin_note = (
        f"Hi — I saw the {job_title} role at {company} and would love to "
        f"connect. My background in {overlap_summary[:80]} aligns well with the team."
    )
    if len(linkedin_note) > 300:
        linkedin_note = (
            f"Hi — I'm interested in the {job_title} role at {company}. "
            f"Would love to connect and learn more about the team."
        )

    email_body = (
        f"Hi,\n\n"
        f"I came across the {job_title} position at {company} and wanted to reach out. "
        f"My background includes {overlap_summary}, which seems well-aligned "
        f"with what the team is building.\n\n"
        f"Would you be open to a brief conversation about the role and the team? "
        f"Happy to work around your schedule.\n\n"
        f"Best,\n{user_name}"
    )

    return {
        "linkedin_note": linkedin_note[:300],
        "email_subject": f"Re: {job_title} at {company}",
        "email_body": email_body,
        "personalization_hooks": ["role interest", "background alignment"],
    }
