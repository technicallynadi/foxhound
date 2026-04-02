"""Network map tool: TinyFish-powered LinkedIn connection finder.

Searches LinkedIn for people at a target company who share connections
with the user — same school, same previous employer, mutual interests.
Helps the user get warm introductions instead of cold applying.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="network_map",
    description=(
        "Find potential connections at a target company using TinyFish to search "
        "LinkedIn. Identifies people who share the user's background — same school, "
        "same previous employer, similar role, or mutual interests. Use when the "
        "user says 'find connections at [company]', 'who do I know at [company]', "
        "'help me network into [company]', or 'find people to reach out to at [company]'. "
        "Returns a list of potential contacts with their titles and connection angles."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "Target company name",
            },
            "department": {
                "type": "string",
                "description": "Target department (e.g. 'engineering', 'product', 'design')",
            },
            "role_context": {
                "type": "string",
                "description": "The role being applied for (helps find relevant contacts)",
            },
        },
        "required": ["company_name"],
    },
    permissions=["read"],
    side_effects=True,
    cost_estimate="high",
)
async def network_map(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Search LinkedIn for connections at a target company via TinyFish."""
    company = params.get("company_name", "").strip()
    department = params.get("department", "engineering")
    role_context = params.get("role_context", "")

    if not company:
        return {"error": "missing_company", "message": "Please specify a company name."}

    # Load user profile for matching context
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {"error": "no_profile", "message": "Set up your profile first."}

    # Build matching context from profile
    experience = json.loads(profile.experience_json or "[]")
    education = json.loads(profile.education_json or "[]") if hasattr(profile, "education_json") else []
    skills = json.loads(profile.skills_json or "[]")

    previous_companies = [exp.get("company", "") for exp in experience if exp.get("company")]
    schools = [edu.get("school", "") for edu in education if edu.get("school")]

    matching_context = []
    if previous_companies:
        matching_context.append(f"Previously worked at: {', '.join(previous_companies[:5])}")
    if schools:
        matching_context.append(f"Attended: {', '.join(schools[:3])}")
    if skills:
        matching_context.append(f"Skills: {', '.join(skills[:10])}")

    context_str = ". ".join(matching_context) if matching_context else "No prior context available."

    _CONTACT_SCHEMA = (
        'Return as JSON array: '
        '[{"name": "...", "title": "...", "linkedin_url": "...", '
        '"connection_angle": "...", "relevance": "high/medium/low"}]'
    )

    # Small focused searches — one per angle
    searches = [
        {
            "name": "team_search",
            "url": f"https://www.google.com/search?q=site:linkedin.com+{company.replace(' ', '+')}+{department}+manager+OR+lead+OR+director",
            "goal": (
                f"Find LinkedIn profiles of {department} team members at {company}. "
                "Click into 3-4 profiles. For each, extract name, title, and profile URL. "
                + _CONTACT_SCHEMA
            ),
        },
        {
            "name": "company_page",
            "url": f"https://www.google.com/search?q=site:linkedin.com+{company.replace(' ', '+')}+people",
            "goal": (
                f"Find the {company} LinkedIn company page and browse their people/employees. "
                f"Focus on {department} department. Extract name, title, LinkedIn URL "
                "for 3-4 relevant people. " + _CONTACT_SCHEMA
            ),
        },
    ]

    # Add school-specific search if we have education
    if schools:
        school = schools[0]
        searches.append({
            "name": "school_alumni",
            "url": f"https://www.google.com/search?q=site:linkedin.com+{company.replace(' ', '+')}+{school.replace(' ', '+')}",
            "goal": (
                f"Find people at {company} who went to {school}. "
                "Extract name, title, LinkedIn URL. Note the shared school. "
                + _CONTACT_SCHEMA
            ),
        })

    # Add previous company search
    if previous_companies:
        prev = previous_companies[0]
        searches.append({
            "name": "former_colleagues",
            "url": f"https://www.google.com/search?q=site:linkedin.com+{company.replace(' ', '+')}+{prev.replace(' ', '+')}",
            "goal": (
                f"Find people at {company} who previously worked at {prev}. "
                "Extract name, title, LinkedIn URL. Note the shared employer. "
                + _CONTACT_SCHEMA
            ),
        })

    # Run TinyFish searches in parallel with global semaphore
    from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE
    all_contacts = []

    async def _run_search(search: dict) -> list[dict]:
        async with TINYFISH_SEMAPHORE:
            try:
                from tinyfish import BrowserProfile, RunStatus
                from app.services.ingest.tinyfish_adapter import _get_client

                client = _get_client()
                result = await client.agent.run(
                    goal=search["goal"],
                    url=search["url"],
                    browser_profile=BrowserProfile.LITE,
                )

                if result.status == RunStatus.COMPLETED and result.result:
                    raw = result.result if isinstance(result.result, str) else json.dumps(result.result)
                    contacts = _parse_contacts(raw)
                    logger.info("Network '%s': found %d contacts", search["name"], len(contacts))
                    return contacts
                return []
            except Exception as e:
                logger.warning("Network '%s' failed: %s", search["name"], str(e)[:200])
                return []

    gathered = await asyncio.gather(*[_run_search(s) for s in searches])
    for contacts in gathered:
        all_contacts.extend(contacts)

    # Deduplicate by name
    seen = set()
    unique = []
    for c in all_contacts:
        name = c.get("name", "").lower()
        if name and name not in seen:
            seen.add(name)
            unique.append(c)

    if not unique:
        return {
            "status": "no_results",
            "company": company,
            "message": (
                f"Couldn't find specific connections at {company}. "
                "LinkedIn may require login for detailed results. "
                "Try searching LinkedIn directly or check if you have mutual connections."
            ),
        }

    return {
        "status": "found",
        "company": company,
        "contacts": unique[:8],
        "count": len(unique[:8]),
        "message": (
            f"Found {len(unique[:8])} potential contacts at {company}. "
            "Contacts with shared backgrounds are marked. "
            "Use these for warm outreach before or after applying."
        ),
    }


def _parse_contacts(raw: str) -> list[dict]:
    """Parse TinyFish output into contact list."""
    import re

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict) and c.get("name")]
        if isinstance(data, dict):
            if data.get("result"):
                return _parse_contacts(data["result"] if isinstance(data["result"], str) else json.dumps(data["result"]))
    except json.JSONDecodeError:
        pass

    match = re.search(r'\[[\s\S]*\]', raw)
    if match:
        try:
            data = json.loads(match.group(0))
            return [c for c in data if isinstance(c, dict) and c.get("name")]
        except json.JSONDecodeError:
            pass

    return []
