"""Auto-fill profile values for application form fields."""

from __future__ import annotations

import json

from app.db.models.user_profile import UserProfile
from app.services.agent.utils.question_classifier import AUTOFILL_PATTERNS

PROFILE_FIELD_MAP: dict[str, str] = {
    "first_name": "first_name",
    "last_name": "last_name",
    "full_name": "_full_name",
    "email": "email",
    "phone": "phone",
    "linkedin": "linkedin_url",
    "portfolio": "portfolio_url",
    "location": "location",
    "visa_status": "visa_status",
    "years_experience": "years_experience",
}


def extract_profile_value(profile: UserProfile, field_label: str) -> str | None:
    """Extract a value from the profile matching the field label.

    Returns None if the profile doesn't have the data.
    """
    text = field_label.lower().strip()

    for key, patterns in AUTOFILL_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                profile_attr = PROFILE_FIELD_MAP.get(key)
                if not profile_attr:
                    break
                if profile_attr == "_full_name":
                    first = profile.first_name or ""
                    last = profile.last_name or ""
                    val = f"{first} {last}".strip()
                    return val if val else None
                val = getattr(profile, profile_attr, None)
                if val is not None:
                    return str(val)
                return None

    # Education
    if any(kw in text for kw in ["degree", "university", "school", "education"]):
        edu = json.loads(profile.education_json or "[]")
        if edu:
            entry = edu[0]
            if isinstance(entry, dict):
                parts = []
                if entry.get("degree"):
                    parts.append(entry["degree"])
                if entry.get("school"):
                    parts.append(entry["school"])
                return ", ".join(parts) if parts else None
            return str(entry)

    return None


def check_answer_bank(profile: UserProfile, field_label: str) -> str | None:
    """Check if the answer bank has a stored answer for this question type."""
    bank = json.loads(profile.answer_bank_json or "{}")
    text = field_label.lower().strip()

    for pattern, answer in bank.items():
        if pattern in text:
            return answer

    return None


def update_answer_bank(profile: UserProfile, field_label: str, answer: str) -> None:
    """Store an answer in the answer bank for future reuse."""
    bank = json.loads(profile.answer_bank_json or "{}")

    # Determine the key pattern
    text = field_label.lower().strip()
    key = None
    for pattern in ["salary", "compensation", "pay", "start date", "notice period",
                     "visa", "authorization", "sponsorship", "criminal", "disability",
                     "gender", "race", "ethnicity", "veteran"]:
        if pattern in text:
            key = pattern
            break

    if key:
        bank[key] = answer
        profile.answer_bank_json = json.dumps(bank)
