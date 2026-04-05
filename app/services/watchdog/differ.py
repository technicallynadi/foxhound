"""Posting diff detection and summarization.

Compares old and new posting text using difflib.SequenceMatcher,
generates a human-readable summary of what changed and why it
might matter to the applicant.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher, unified_diff

logger = logging.getLogger(__name__)


def similarity_ratio(old_text: str, new_text: str) -> float:
    """Return 0.0-1.0 similarity ratio between two texts."""
    old_norm = _normalize(old_text)
    new_norm = _normalize(new_text)
    return SequenceMatcher(None, old_norm, new_norm).ratio()


def is_meaningfully_changed(old_text: str, new_text: str) -> bool:
    """True if less than 98 percent similar (after normalization)."""
    return similarity_ratio(old_text, new_text) < 0.98


def get_change_magnitude(old_text: str, new_text: str) -> str:
    """Classify the size of the change: 'minor' | 'moderate' | 'major'."""
    ratio = similarity_ratio(old_text, new_text)
    if ratio >= 0.95:
        return "minor"
    if ratio >= 0.80:
        return "moderate"
    return "major"


def summarize_diff(old_text: str, new_text: str) -> str:
    """Generate a human-readable summary of posting changes.

    Returns a concise description like:
    "Experience requirement changed (3y -> 5y) | Removed: some line | Added: some line"
    """
    old_lines = old_text.strip().splitlines()
    new_lines = new_text.strip().splitlines()

    diff_lines = list(unified_diff(old_lines, new_lines, lineterm=""))

    added = [line[2:] for line in diff_lines if line.startswith("+ ") and not line.startswith("+++")]
    removed = [line[2:] for line in diff_lines if line.startswith("- ") and not line.startswith("---")]

    if not added and not removed:
        return "Minor formatting changes detected."

    parts: list[str] = []

    # Detect common patterns first
    pattern_summary = _detect_patterns(added, removed)
    if pattern_summary:
        parts.append(pattern_summary)

    if removed:
        parts.append(f"Removed: {_truncate_lines(removed)}")
    if added:
        parts.append(f"Added: {_truncate_lines(added)}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------


def _detect_patterns(added: list[str], removed: list[str]) -> str | None:
    """Detect common posting change patterns (experience, salary, remote)."""
    added_lower = " ".join(added).lower()
    removed_lower = " ".join(removed).lower()

    patterns: list[str] = []

    # Years of experience changed
    old_years = re.findall(r"(\d+)\+?\s*years?", removed_lower)
    new_years = re.findall(r"(\d+)\+?\s*years?", added_lower)
    if old_years and new_years and old_years != new_years:
        patterns.append(f"Experience requirement changed ({old_years[0]}y -> {new_years[0]}y)")

    # Salary changed
    old_salary = re.findall(r"\$[\d,]+k?", removed_lower)
    new_salary = re.findall(r"\$[\d,]+k?", added_lower)
    if old_salary and new_salary and old_salary != new_salary:
        patterns.append("Salary range updated")

    # Remote/location changed
    remote_terms = {"remote", "hybrid", "on-site", "onsite", "in-office"}
    old_remote = remote_terms & set(removed_lower.split())
    new_remote = remote_terms & set(added_lower.split())
    if old_remote != new_remote:
        patterns.append("Location/remote policy changed")

    return "; ".join(patterns) if patterns else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Normalize whitespace for comparison."""
    return " ".join(text.split()).strip().lower()


def _truncate_lines(lines: list[str], max_chars: int = 200) -> str:
    """Join lines into a truncated summary string."""
    joined = "; ".join(line.strip() for line in lines if line.strip())
    if len(joined) > max_chars:
        return joined[: max_chars - 3] + "..."
    return joined
