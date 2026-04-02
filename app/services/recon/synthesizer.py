"""Claude Haiku synthesis for recon dossiers.

Takes raw source data from TinyFish + job posting and produces a structured
dossier with summary, hiring_velocity, tech_stack, insider_tip, confidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT = """\
You are a company intelligence analyst for job seekers. Analyze the job posting \
description and extract a complete intelligence dossier.

Return ONLY valid JSON with this exact structure:
{
  "summary": "1-2 sentence company overview — what they do, industry, any size/stage clues from the posting",
  "hiring_velocity": "signals from the posting about growth, team expansion, urgency",
  "tech_stack": ["every", "technology", "tool", "framework", "language", "platform", "mentioned"],
  "team_insight": "team structure, reporting, department, collaboration signals from the posting",
  "insider_tip": "specific, actionable advice — what to emphasize based on what the posting values most",
  "confidence": "high"
}

Rules:
- Extract EVERYTHING from the job description text
- tech_stack: scan the ENTIRE description for programming languages (Python, Java, Go, Rust, C++, TypeScript, JavaScript), frameworks (React, Node, Django, Spring, Rails), cloud (AWS, GCP, Azure), infra (Docker, Kubernetes, Terraform), databases (PostgreSQL, MySQL, Redis, MongoDB, Kafka), tools (Git, CI/CD, Jira), and the company's own products. NEVER return an empty array.
- hiring_velocity: look for phrases like "growing team", "new role", "scaling", "fast-paced", headcount clues
- team_insight: extract who they report to, team size, cross-functional collaboration mentions
- insider_tip: identify the TOP 2-3 skills/qualities the posting emphasizes MOST and advise the candidate to lead with those
- confidence is always "high" since we have the full job description
- Keep summary under 50 words
- Keep insider_tip under 50 words"""


async def synthesize_dossier(
    company_name: str,
    careers_data: dict[str, Any] | None,
    company_data: dict[str, Any] | None,
    posting_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run Claude Haiku synthesis on collected source data.

    Returns the synthesis dict or a fallback if the API call fails.
    """
    user_content = (
        f"Company: {company_name}\n\n"
        f"CAREERS PAGE DATA:\n{json.dumps(careers_data, default=str) if careers_data else 'Not available'}\n\n"
        f"ABOUT PAGE DATA:\n{json.dumps(company_data, default=str) if company_data else 'Not available'}\n\n"
        f"JOB POSTING DATA:\n{json.dumps(posting_data, default=str) if posting_data else 'Not available'}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0.2,
            system=_SYNTHESIS_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        synthesis = json.loads(text)
        logger.info("Synthesis complete for %s — confidence=%s", company_name, synthesis.get("confidence"))
        return synthesis

    except json.JSONDecodeError as e:
        logger.warning("Synthesis JSON parse failed for %s: %s", company_name, e)
        return _fallback_synthesis(company_name, careers_data, company_data, posting_data)
    except Exception as e:
        logger.warning("Synthesis API call failed for %s: %s", company_name, str(e)[:200])
        return _fallback_synthesis(company_name, careers_data, company_data, posting_data)


def _fallback_synthesis(
    company_name: str,
    careers_data: dict[str, Any] | None,
    company_data: dict[str, Any] | None,
    posting_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a basic dossier from raw data when Claude synthesis fails."""
    tech_stack: list[str] = []
    if careers_data and isinstance(careers_data.get("technologies"), list):
        tech_stack.extend(careers_data["technologies"])
    if posting_data and isinstance(posting_data.get("tech_stack"), list):
        tech_stack.extend(posting_data["tech_stack"])
    tech_stack = list(dict.fromkeys(tech_stack))  # dedupe preserving order

    summary_parts = [company_name]
    if company_data:
        if company_data.get("size"):
            summary_parts.append(f"{company_data['size']} employees")
        if company_data.get("mission"):
            summary_parts.append(str(company_data["mission"])[:100])

    hiring_velocity = "Unknown"
    if careers_data:
        roles = careers_data.get("open_roles")
        velocity = careers_data.get("hiring_velocity")
        if roles:
            hiring_velocity = f"{roles} open roles"
        if velocity:
            hiring_velocity += f" — {velocity}"

    sources_count = sum(1 for d in [careers_data, company_data, posting_data] if d)
    confidence = "high" if sources_count >= 2 else ("medium" if sources_count == 1 else "low")

    return {
        "summary": " — ".join(summary_parts),
        "hiring_velocity": hiring_velocity,
        "tech_stack": tech_stack[:20],
        "team_insight": "",
        "insider_tip": "Review the job requirements carefully and highlight matching experience.",
        "confidence": confidence,
    }
