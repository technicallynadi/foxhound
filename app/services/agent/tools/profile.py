"""Profile and preferences tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool


@tool(
    name="get_profile",
    description=(
        "Get the user's current profile, skills, experience, and job preferences. "
        "Use this when the user asks about their profile, what's on file, "
        "or wants to see their current settings."
    ),
    input_schema={"type": "object", "properties": {}},
    permissions=["read"],
    side_effects=False,
)
async def get_profile(db: AsyncSession, user_id: str, params: dict) -> dict:
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        return {"error": "no_profile", "message": "No profile found. Upload your resume to get started."}

    skills = json.loads(profile.skills_json or "[]")
    target_titles = json.loads(profile.target_titles_json or "[]")
    target_locations = json.loads(profile.target_locations_json or "[]")
    experience = json.loads(profile.experience_json or "[]")
    answer_bank = json.loads(profile.answer_bank_json or "{}")

    return {
        "name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "email": profile.email,
        "location": profile.location,
        "summary": profile.summary,
        "skills": skills[:15],
        "years_experience": profile.years_experience,
        "experience": [
            {"title": e.get("title"), "company": e.get("company"), "years": e.get("years")}
            for e in experience[:5] if isinstance(e, dict)
        ],
        "preferences": {
            "target_titles": target_titles,
            "target_locations": target_locations,
            "remote_preference": profile.remote_preference,
            "salary_floor": profile.salary_floor,
            "seniority": profile.seniority_level,
        },
        "tier": profile.tier,
        "applications_this_month": profile.applications_this_month,
        "monthly_limit": profile.monthly_apply_limit,
        "autopilot_enabled": bool(profile.autopilot_enabled),
        "answer_bank_entries": len(answer_bank),
        "message": f"Profile for {profile.first_name or 'user'}. {profile.tier.title()} tier, {profile.applications_this_month}/{profile.monthly_apply_limit} apps used.",
    }


@tool(
    name="update_preferences",
    description=(
        "Update the user's job search preferences. Use this when the user "
        "wants to change target titles, locations, remote preference, salary floor, etc."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_titles": {"type": "array", "items": {"type": "string"}, "description": "Job titles to target"},
            "target_locations": {"type": "array", "items": {"type": "string"}, "description": "Preferred locations"},
            "remote_preference": {"type": "string", "enum": ["remote", "hybrid", "onsite", "any"]},
            "salary_floor": {"type": "integer", "description": "Minimum salary (USD)"},
            "seniority_level": {"type": "string", "description": "Target seniority (junior, mid, senior, staff)"},
        },
    },
    permissions=["write"],
    side_effects=False,
)
async def update_preferences(db: AsyncSession, user_id: str, params: dict) -> dict:
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        return {"error": "no_profile", "message": "No profile found. Upload your resume first."}

    updated = []

    if "target_titles" in params:
        profile.target_titles_json = json.dumps(params["target_titles"])
        updated.append(f"target titles: {', '.join(params['target_titles'])}")

    if "target_locations" in params:
        profile.target_locations_json = json.dumps(params["target_locations"])
        updated.append(f"locations: {', '.join(params['target_locations'])}")

    if "remote_preference" in params:
        profile.remote_preference = params["remote_preference"]
        updated.append(f"remote: {params['remote_preference']}")

    if "salary_floor" in params:
        profile.salary_floor = params["salary_floor"]
        updated.append(f"min salary: ${params['salary_floor']:,}")

    if "seniority_level" in params:
        profile.seniority_level = params["seniority_level"]
        updated.append(f"seniority: {params['seniority_level']}")

    if not updated:
        return {"message": "No changes specified. What would you like to update?"}

    profile.updated_at = datetime.now(UTC)
    await db.commit()

    return {"changes": updated, "message": f"Updated: {', '.join(updated)}."}
