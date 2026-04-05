"""Career Trajectory: understands a user's career arc, not just keywords.

Parses experience_json and education_json to build:
- Seniority progression (Junior → Senior → Staff)
- Company tier pattern (startup → growth → enterprise)
- Skills evolution over time
- Compensation trajectory estimate
- Next logical move prediction
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Seniority levels in order
_SENIORITY_MAP = {
    "intern": 0,
    "trainee": 0,
    "junior": 1,
    "associate": 1,
    "entry": 1,
    "jr": 1,
    "mid": 2,
    "intermediate": 2,
    "senior": 3,
    "sr": 3,
    "lead": 3,
    "staff": 4,
    "principal": 4,
    "architect": 5,
    "distinguished": 5,
    "fellow": 5,
    "director": 6,
    "head": 6,
    "vp": 7,
    "cto": 8,
    "ceo": 8,
    "manager": 4,
    "engineering manager": 5,
}

_COMPANY_TIERS = {
    # FAANG/Big Tech
    "google": "enterprise",
    "meta": "enterprise",
    "apple": "enterprise",
    "amazon": "enterprise",
    "microsoft": "enterprise",
    "netflix": "enterprise",
    # Growth/Late-stage
    "stripe": "growth",
    "airbnb": "growth",
    "databricks": "growth",
    "shopify": "growth",
    "coinbase": "growth",
    "figma": "growth",
    "notion": "growth",
    "ramp": "growth",
    "anthropic": "growth",
    # Default detection by keywords
}


def build_trajectory(profile) -> dict[str, Any]:
    """Build a career trajectory model from a user profile.

    Args:
        profile: UserProfile ORM object

    Returns dict with trajectory data — store in profile or use inline.
    """
    experience = json.loads(profile.experience_json or "[]")
    education = json.loads(profile.education_json or "[]")
    skills = json.loads(profile.skills_json or "[]")

    if not experience:
        return {
            "level": "unknown",
            "arc": "insufficient_data",
            "next_move": None,
            "summary": "Not enough experience data to build trajectory.",
        }

    # --- Parse each role ---
    roles = []
    for exp in experience:
        title = exp.get("title", "").lower()
        company = exp.get("company", "")
        start = exp.get("start_date", "")
        end = exp.get("end_date", "")

        level = _detect_seniority(title)
        tier = _detect_company_tier(company)
        track = _detect_track(title)

        roles.append(
            {
                "title": exp.get("title", ""),
                "company": company,
                "level": level,
                "level_num": _SENIORITY_MAP.get(level, 2),
                "tier": tier,
                "track": track,
                "start": start,
                "end": end,
            }
        )

    # Sort by start date (most recent first)
    roles.sort(key=lambda r: r["start"] or "", reverse=True)

    # --- Current level ---
    current = roles[0] if roles else None
    current_level = current["level"] if current else "unknown"
    current_level_num = current["level_num"] if current else 2

    # --- Progression arc ---
    level_nums = [r["level_num"] for r in roles]
    if len(level_nums) >= 2:
        if level_nums[0] > level_nums[-1]:
            arc = "ascending"
        elif level_nums[0] == level_nums[-1]:
            arc = "lateral"
        else:
            arc = "descending"
    else:
        arc = "single_role"

    # --- Company tier progression ---
    tiers = [r["tier"] for r in roles if r["tier"]]
    tier_pattern = " → ".join(dict.fromkeys(reversed(tiers))) if tiers else "unknown"

    # --- Track (IC vs Management) ---
    tracks = [r["track"] for r in roles]
    if "management" in tracks and "ic" in tracks:
        career_track = "hybrid"
    elif "management" in tracks:
        career_track = "management"
    else:
        career_track = "ic"

    # --- Next move prediction ---
    next_move = _predict_next_move(current_level_num, arc, career_track, roles)

    # --- Skills evolution ---
    skills_summary = _categorize_skills(skills)

    # --- Companies list ---
    companies = [r["company"] for r in roles if r["company"]]

    # --- Education ---
    schools = [e.get("school", "") for e in education if e.get("school")]
    degrees = [e.get("degree", "") for e in education if e.get("degree")]

    trajectory = {
        "current_level": current_level,
        "current_level_num": current_level_num,
        "current_title": current["title"] if current else "",
        "current_company": current["company"] if current else "",
        "arc": arc,
        "career_track": career_track,
        "tier_pattern": tier_pattern,
        "roles_count": len(roles),
        "years_experience": profile.years_experience,
        "previous_companies": companies,
        "schools": schools,
        "degrees": degrees,
        "skills_categories": skills_summary,
        "next_move": next_move,
        "summary": _build_summary(current, arc, career_track, next_move, len(roles)),
    }

    return trajectory


def _detect_seniority(title: str) -> str:
    """Detect seniority level from a job title."""
    title_lower = title.lower()

    # Check explicit seniority keywords
    for keyword, level_name in [
        ("cto", "cto"),
        ("ceo", "ceo"),
        ("vp ", "vp"),
        ("vice president", "vp"),
        ("director", "director"),
        ("head of", "head"),
        ("distinguished", "distinguished"),
        ("fellow", "fellow"),
        ("principal", "principal"),
        ("staff", "staff"),
        ("architect", "architect"),
        ("engineering manager", "engineering manager"),
        ("manager", "manager"),
        ("senior", "senior"),
        ("sr.", "senior"),
        ("sr ", "senior"),
        ("lead", "lead"),
        ("junior", "junior"),
        ("jr.", "junior"),
        ("jr ", "junior"),
        ("associate", "associate"),
        ("entry", "entry"),
        ("intern", "intern"),
        ("trainee", "trainee"),
    ]:
        if keyword in title_lower:
            return level_name

    return "mid"  # Default to mid-level


def _detect_company_tier(company: str) -> str:
    """Detect company tier from name."""
    company_lower = company.lower().strip()

    if company_lower in _COMPANY_TIERS:
        return _COMPANY_TIERS[company_lower]

    # Heuristic detection
    if any(kw in company_lower for kw in ["inc", "corp", "group", "holdings"]):
        return "enterprise"

    return "startup"  # Default


def _detect_track(title: str) -> str:
    """Detect IC vs management track."""
    title_lower = title.lower()
    mgmt_keywords = ["manager", "director", "head of", "vp", "lead", "chief"]
    if any(kw in title_lower for kw in mgmt_keywords):
        return "management"
    return "ic"


def _predict_next_move(current_level: int, arc: str, track: str, roles: list[dict]) -> dict[str, str]:
    """Predict the logical next career move."""
    level_names = {
        0: "Intern/Entry",
        1: "Junior",
        2: "Mid-level",
        3: "Senior",
        4: "Staff/Principal",
        5: "Architect/Distinguished",
        6: "Director",
        7: "VP",
        8: "C-level",
    }

    if arc == "ascending":
        next_level = min(current_level + 1, 8)
        if track == "ic":
            return {
                "level": level_names.get(next_level, "Next level"),
                "suggestion": f"Target {level_names.get(next_level, 'next level')} IC roles",
                "alt": f"Consider pivoting to {level_names.get(current_level, '')} management"
                if current_level >= 3
                else None,
            }
        else:
            return {
                "level": level_names.get(next_level, "Next level"),
                "suggestion": f"Target {level_names.get(next_level, 'next level')} management roles",
            }

    if arc == "lateral":
        return {
            "level": level_names.get(current_level, "Current level"),
            "suggestion": "Consider a step up — your trajectory shows lateral moves. Target one level higher.",
            "alt": "Or target a higher-tier company at the same level for a comp increase",
        }

    return {
        "level": level_names.get(current_level, "Current"),
        "suggestion": "Focus on roles matching your current level",
    }


def _categorize_skills(skills: list[str]) -> dict[str, list[str]]:
    """Categorize skills into domains."""
    categories: dict[str, list[str]] = {
        "languages": [],
        "frontend": [],
        "backend": [],
        "infra": [],
        "data": [],
        "other": [],
    }

    lang_kw = {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c++",
        "ruby",
        "swift",
        "kotlin",
        "php",
        "scala",
    }
    fe_kw = {"react", "vue", "angular", "nextjs", "next.js", "css", "html", "tailwind", "svelte"}
    be_kw = {"django", "flask", "fastapi", "express", "node", "spring", "rails", "graphql", "rest", "grpc"}
    infra_kw = {"aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ci/cd", "linux", "nginx"}
    data_kw = {
        "sql",
        "postgresql",
        "mongodb",
        "redis",
        "elasticsearch",
        "kafka",
        "spark",
        "ml",
        "pytorch",
        "tensorflow",
    }

    for skill in skills:
        s = skill.lower().strip()
        if s in lang_kw:
            categories["languages"].append(skill)
        elif s in fe_kw or "frontend" in s or "front-end" in s:
            categories["frontend"].append(skill)
        elif s in be_kw or "backend" in s or "back-end" in s:
            categories["backend"].append(skill)
        elif s in infra_kw or "devops" in s or "cloud" in s:
            categories["infra"].append(skill)
        elif s in data_kw or "data" in s or "machine learning" in s:
            categories["data"].append(skill)
        else:
            categories["other"].append(skill)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def _build_summary(current: dict | None, arc: str, track: str, next_move: dict, role_count: int) -> str:
    """Build a human-readable trajectory summary."""
    if not current:
        return "Insufficient experience data."

    parts = []
    parts.append(f"Currently {current['title']} at {current['company']}.")

    if arc == "ascending":
        parts.append(f"Strong upward trajectory across {role_count} roles.")
    elif arc == "lateral":
        parts.append(f"Lateral progression across {role_count} roles — ready for a step up.")
    elif arc == "descending":
        parts.append("Recent career pivot — targeting new direction.")

    if track == "ic":
        parts.append("Individual contributor track.")
    elif track == "management":
        parts.append("Management track.")
    else:
        parts.append("Hybrid IC/management experience.")

    if next_move.get("suggestion"):
        parts.append(f"Next move: {next_move['suggestion']}")

    return " ".join(parts)
