"""Question classification for job application forms.

Two-tier approach:
- Tier 1: Fast keyword matching (no LLM cost)
- Tier 2: LLM classification for ambiguous cases
"""

from __future__ import annotations

import json
import logging

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1: Keyword patterns
# ---------------------------------------------------------------------------

AUTOFILL_PATTERNS: dict[str, list[str]] = {
    "first_name": ["first name"],
    "last_name": ["last name", "surname", "family name"],
    "full_name": ["full name", "your name", "candidate name"],
    "email": ["email"],
    "phone": ["phone", "telephone", "mobile"],
    "linkedin": ["linkedin"],
    "portfolio": ["website", "portfolio", "url", "github"],
    "location": ["city", "location", "where are you based"],
    "visa_status": [
        "authorized to work", "work authorization", "sponsorship",
        "legally authorized", "visa", "right to work", "eligible to work",
    ],
    "education": ["highest degree", "degree", "university", "school", "gpa"],
    "years_experience": ["years of experience", "years experience", "how many years"],
}

DRAFT_PATTERNS: list[str] = [
    "why do you want", "why are you interested", "tell us about yourself",
    "describe your experience", "what interests you", "cover letter",
    "why should we hire", "what makes you a good", "greatest achievement",
    "biggest accomplishment", "why are you leaving", "career goals",
    "what are you passionate", "how did you hear about",
]

ASK_DIRECTLY_PATTERNS: list[str] = [
    "salary", "compensation", "pay expectation", "desired pay",
    "start date", "earliest start", "when can you start", "notice period",
    "references",
    "criminal", "background check", "felony", "conviction",
    "disability", "accommodation",
    "gender", "race", "ethnicity", "veteran",
]


def classify_question(field_label: str, options: list[str] | None = None) -> str:
    """Tier 1 keyword classification.

    Returns: "auto" | "draft_and_approve" | "ask_directly" | "unknown"
    """
    text = field_label.lower().strip()

    # Sensitive takes priority
    for pattern in ASK_DIRECTLY_PATTERNS:
        if pattern in text:
            return "ask_directly"

    # Narrative
    for pattern in DRAFT_PATTERNS:
        if pattern in text:
            return "draft_and_approve"

    # Auto-fillable
    for patterns in AUTOFILL_PATTERNS.values():
        for pattern in patterns:
            if pattern in text:
                return "auto"

    return "unknown"


# ---------------------------------------------------------------------------
# Tier 2: LLM classification
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """Classify this job application question into exactly one category.

Question: "{field_label}"
Options if select/radio: {options}

Categories:
- "auto": Factual info findable on a resume (name, email, experience count, degree).
- "draft": Narrative/opinion where an AI can draft a contextual answer for human review.
- "ask": Sensitive, personal, or requires info not on a resume (salary, start date, EEO).

Return ONLY the category name: "auto", "draft", or "ask"."""


async def classify_with_llm(field_label: str, options: list[str] | None = None) -> str:
    """Tier 2 LLM classification for ambiguous questions."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    prompt = CLASSIFY_PROMPT.format(
        field_label=field_label,
        options=json.dumps(options or []),
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.content[0].text.strip().lower().strip('"')
        if result == "auto":
            return "auto"
        if result == "draft":
            return "draft_and_approve"
        if result == "ask":
            return "ask_directly"
    except Exception as e:
        logger.warning("LLM classification failed for '%s': %s", field_label, e)

    return "ask_directly"  # Safe default
