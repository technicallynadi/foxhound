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

SUPPORTED_ATS = {"greenhouse", "ashby", "lever"}

# Lever uses hCaptcha on browser forms — but API submission bypasses it.
CAPTCHA_ATS = {"lever"}

# ATS platforms that support direct API submission (no browser needed)
API_SUBMIT_ATS = {"greenhouse", "lever", "ashby"}


def detect_ats(url: str) -> str | None:
    """Return ATS name from URL, or None if unknown."""
    for pattern, ats_name in ATS_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return ats_name
    return None


def is_auto_apply_supported(ats_type: str | None) -> bool:
    """Return True if we support auto-applying to this ATS.

    Lever is now supported via API submission (bypasses hCaptcha).
    """
    return ats_type in SUPPORTED_ATS


def is_api_submit_supported(ats_type: str | None) -> bool:
    """Return True if this ATS supports direct API submission."""
    return ats_type in API_SUBMIT_ATS
