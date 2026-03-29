"""Detect ATS type from job application URL patterns."""

from __future__ import annotations

import re

ATS_PATTERNS: list[tuple[str, str]] = [
    (r"boards\.greenhouse\.io", "greenhouse"),
    (r"job-boards\.greenhouse\.io", "greenhouse"),
    (r"jobs\.lever\.co", "lever"),
    (r"\.myworkdayjobs\.com", "workday"),
    (r"jobs\.ashbyhq\.com", "ashby"),
    (r"jobs\.smartrecruiters\.com", "smartrecruiters"),
    (r"\.icims\.com", "icims"),
]

SUPPORTED_ATS = {"greenhouse", "ashby"}

# Lever uses hCaptcha on all apply forms — auto-apply not possible.
CAPTCHA_ATS = {"lever"}


def detect_ats(url: str) -> str | None:
    """Return ATS name from URL, or None if unknown."""
    for pattern, ats_name in ATS_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return ats_name
    return None


def is_auto_apply_supported(ats_type: str | None) -> bool:
    """Return True if we support auto-applying to this ATS.

    Lever is excluded — they serve hCaptcha on every apply form.
    """
    return ats_type in SUPPORTED_ATS
