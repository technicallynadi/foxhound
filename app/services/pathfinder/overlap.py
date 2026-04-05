"""Find overlap between user profile and job posting.

Pure Python, no API calls. Identifies shared skills, industry match,
location match, and seniority alignment to personalize outreach messages.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OverlapResult:
    """Structured result of profile-to-job overlap analysis."""

    shared_skills: list[str] = field(default_factory=list)
    user_only_skills: list[str] = field(default_factory=list)
    job_only_skills: list[str] = field(default_factory=list)
    industry_match: bool = False
    industry_details: str = ""
    location_match: bool = False
    location_details: str = ""
    seniority_alignment: str = "unknown"  # "match" | "stretch" | "overqualified" | "unknown"
    overlap_score: int = 0  # 0-100

    def to_dict(self) -> dict[str, Any]:
        return {
            "shared_skills": self.shared_skills,
            "user_only_skills": self.user_only_skills[:10],
            "job_only_skills": self.job_only_skills[:10],
            "industry_match": self.industry_match,
            "industry_details": self.industry_details,
            "location_match": self.location_match,
            "location_details": self.location_details,
            "seniority_alignment": self.seniority_alignment,
            "overlap_score": self.overlap_score,
        }

    def summary_for_outreach(self) -> str:
        """One-liner summary for use in outreach personalization."""
        parts: list[str] = []
        if self.shared_skills:
            top = self.shared_skills[:3]
            parts.append(f"shared skills: {', '.join(top)}")
        if self.industry_match:
            parts.append(f"industry match ({self.industry_details})")
        if self.location_match:
            parts.append(f"same area ({self.location_details})")
        if self.seniority_alignment == "match":
            parts.append("seniority fit")
        return "; ".join(parts) if parts else "general interest in the role"


def _parse_json_field(raw: str | None) -> list[str]:
    """Safely parse a JSON list field, returning lowercase strings."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item).lower().strip() for item in data if item]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _normalize_skill(skill: str) -> str:
    """Normalize a skill string for comparison."""
    s = skill.lower().strip()
    # Common aliases
    aliases = {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "k8s": "kubernetes",
        "postgres": "postgresql",
        "react.js": "react",
        "reactjs": "react",
        "node.js": "node",
        "nodejs": "node",
        "vue.js": "vue",
        "vuejs": "vue",
        "next.js": "next",
        "nextjs": "next",
        "golang": "go",
        "c#": "csharp",
        "c++": "cpp",
    }
    return aliases.get(s, s)


def _normalize_location(loc: str | None) -> str:
    """Normalize location for loose comparison."""
    if not loc:
        return ""
    parts = loc.lower().strip().replace(",", " ").split()
    # Drop common filler words
    filler = {"area", "metro", "greater", "the", "of"}
    return " ".join(p for p in parts if p not in filler)


_SENIORITY_RANK = {
    "intern": 0,
    "junior": 1,
    "entry": 1,
    "mid": 2,
    "mid-level": 2,
    "intermediate": 2,
    "senior": 3,
    "lead": 4,
    "staff": 4,
    "principal": 5,
    "manager": 5,
    "director": 6,
    "vp": 7,
    "c_level": 8,
    "executive": 8,
}


def find_overlap(
    user_skills_json: str | None,
    user_industries_json: str | None,
    user_location: str | None,
    user_seniority: str | None,
    user_experience_json: str | None,
    job_required_skills_json: str | None,
    job_preferred_skills_json: str | None,
    job_location: str | None,
    job_seniority: str | None,
    job_description: str | None = None,
) -> OverlapResult:
    """Compute overlap between a user profile and a job listing.

    All inputs are raw DB column values (JSON strings or plain strings).
    Returns an OverlapResult with match details.
    """
    result = OverlapResult()

    # --- Skills overlap ---
    user_skills = set(_normalize_skill(s) for s in _parse_json_field(user_skills_json))
    job_required = set(_normalize_skill(s) for s in _parse_json_field(job_required_skills_json))
    job_preferred = set(_normalize_skill(s) for s in _parse_json_field(job_preferred_skills_json))
    all_job_skills = job_required | job_preferred

    # Also extract skills from experience titles/descriptions
    experience_skills: set[str] = set()
    for exp in _parse_json_field(user_experience_json):
        # experience_json entries might be dicts serialized as strings or raw strings
        experience_skills.add(exp)

    result.shared_skills = sorted(user_skills & all_job_skills)
    result.user_only_skills = sorted(user_skills - all_job_skills)
    result.job_only_skills = sorted(all_job_skills - user_skills)

    # --- Industry match ---
    user_industries = set(_parse_json_field(user_industries_json))
    if user_industries and job_description:
        desc_lower = job_description.lower()
        matched = [ind for ind in user_industries if ind in desc_lower]
        if matched:
            result.industry_match = True
            result.industry_details = matched[0]

    # --- Location match ---
    user_loc = _normalize_location(user_location)
    job_loc = _normalize_location(job_location)
    if user_loc and job_loc:
        # Check if any word from user location appears in job location or vice versa
        user_words = set(user_loc.split())
        job_words = set(job_loc.split())
        common = user_words & job_words
        if common or "remote" in job_loc:
            result.location_match = True
            if "remote" in job_loc:
                result.location_details = "remote"
            else:
                result.location_details = " ".join(sorted(common))
    elif job_loc and "remote" in job_loc:
        result.location_match = True
        result.location_details = "remote"

    # --- Seniority alignment ---
    user_rank = _SENIORITY_RANK.get((user_seniority or "").lower(), -1)
    job_rank = _SENIORITY_RANK.get((job_seniority or "").lower(), -1)
    if user_rank >= 0 and job_rank >= 0:
        diff = user_rank - job_rank
        if abs(diff) <= 1:
            result.seniority_alignment = "match"
        elif diff > 1:
            result.seniority_alignment = "overqualified"
        else:
            result.seniority_alignment = "stretch"
    else:
        result.seniority_alignment = "unknown"

    # --- Overlap score (0-100) ---
    score = 0
    if all_job_skills:
        skill_pct = len(result.shared_skills) / len(all_job_skills)
        score += int(skill_pct * 50)  # skills worth up to 50 points
    if result.industry_match:
        score += 15
    if result.location_match:
        score += 15
    if result.seniority_alignment == "match":
        score += 20
    elif result.seniority_alignment == "stretch":
        score += 10

    result.overlap_score = min(score, 100)
    return result
