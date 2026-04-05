"""Form scanner: TinyFish scan phase.

Phase 1 of the two-phase apply flow.
Navigates to the application URL and extracts all form fields
as structured JSON — without filling anything.

This tells us:
- What fields exist (name, email, custom questions, file upload, etc.)
- Which are required vs optional
- Dropdown/radio options (so we can select the right one)
- Whether the form has a CAPTCHA, login wall, or other blocker
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from app.services.agent.utils.url_validator import validate_apply_url

logger = logging.getLogger(__name__)


@dataclass
class FormField:
    label: str
    field_type: str  # text, textarea, select, radio, checkbox, file, hidden
    required: bool = False
    placeholder: str = ""
    options: list[str] = field(default_factory=list)  # for select/radio
    field_name: str = ""  # HTML name attribute
    current_value: str = ""


@dataclass
class ScanResult:
    status: str  # "scannable" | "login_required" | "captcha" | "not_found" | "error"
    fields: list[FormField] = field(default_factory=list)
    page_title: str = ""
    form_count: int = 0
    has_file_upload: bool = False
    has_captcha: bool = False
    requires_login: bool = False
    ats_type: str | None = None
    error: str | None = None
    raw_output: str = ""
    scan_duration_ms: int = 0


FORM_SCAN_PROMPT = """Scroll down the page to find the job application form. Extract all form fields from the application form.

For each visible form field, return:
- label: the visible label text (or placeholder if no label)
- field_type: text | textarea | select | radio | checkbox | file | email | tel | url | date | number
- required: true/false
- options: for select/radio fields, list ALL option texts exactly as shown (empty array for others)
- placeholder: any placeholder text

If a cookie or consent banner appears, close it first.
Do not fill any fields. Do not click Submit or Next.

If you see a login/signup page, return: {"status": "login_required", "fields": []}
If you see a CAPTCHA, return: {"status": "captcha", "fields": []}
If the page shows "job not found" or 404, return: {"status": "not_found", "fields": []}
If the position is filled/closed, return: {"status": "expired", "fields": []}

Return as JSON with this exact structure:
{
  "status": "scannable",
  "page_title": "Job Title - Company",
  "has_file_upload": true,
  "has_captcha": false,
  "form_count": 1,
  "fields": [
    {"label": "First Name", "field_type": "text", "required": true, "options": [], "placeholder": ""},
    {"label": "Country", "field_type": "select", "required": true, "options": ["United States", "Canada"], "placeholder": ""}
  ]
}"""


def _pick_browser_profile(apply_url: str) -> tuple:
    """Pick the right TinyFish browser profile based on the ATS.

    - Greenhouse: STEALTH + proxy (bot detection, but works with stealth)
    - Ashby: LITE, no proxy (stealth triggers spam detection)
    - Lever: LITE (hCaptcha blocks regardless, but scan still useful)
    - Unknown: STEALTH + proxy (safe default)
    """
    from tinyfish import BrowserProfile, ProxyConfig, ProxyCountryCode

    from app.services.discovery.ats_detector import detect_ats

    ats = detect_ats(apply_url)

    if ats == "ashby":
        return BrowserProfile.LITE, None
    if ats == "lever":
        return BrowserProfile.LITE, None
    # Greenhouse and unknown: stealth + proxy
    return BrowserProfile.STEALTH, ProxyConfig(enabled=True, country_code=ProxyCountryCode.US)


async def scan_form(apply_url: str, use_stealth: bool = True) -> ScanResult:
    """Scan a job application form to discover its fields.

    This is Phase 1 of the two-phase apply flow.
    Returns structured field data without modifying the form.

    Browser profile is selected per ATS:
    - Greenhouse: STEALTH + proxy
    - Ashby: LITE (stealth triggers spam detection)
    - Lever: LITE (hCaptcha blocks regardless)
    """
    from app.services.ingest.tinyfish_adapter import _get_client

    goal = FORM_SCAN_PROMPT

    t0 = time.monotonic()

    if not validate_apply_url(apply_url):
        return ScanResult(
            status="error",
            error="Blocked unsafe apply URL (failed ATS allowlist validation)",
            scan_duration_ms=int((time.monotonic() - t0) * 1000),
        )

    try:
        client = _get_client()

        browser_profile, proxy_config = _pick_browser_profile(apply_url)
        kwargs: dict = {"goal": goal, "url": apply_url, "browser_profile": browser_profile}
        if proxy_config:
            kwargs["proxy_config"] = proxy_config

        result = await client.agent.run(**kwargs)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Use result.result if available
        if result.result and isinstance(result.result, dict):
            raw_dict = result.result
            # Handle nested {"result": "```json...```"} format
            if "result" in raw_dict and isinstance(raw_dict["result"], str):
                inner = raw_dict["result"]
                # Strip markdown code blocks
                inner = re.sub(r"^```json\s*", "", inner.strip())
                inner = re.sub(r"\s*```$", "", inner.strip())
                return _parse_scan_result(inner, duration_ms)
            return _parse_scan_result(json.dumps(raw_dict), duration_ms)

        raw = str(result)
        return _parse_scan_result(raw, duration_ms)

    except Exception as e:
        error_str = str(e)
        # Check for specific TinyFish error codes
        if "RATE_LIMIT_EXCEEDED" in error_str:
            error_str = "TinyFish rate limited — retry in a few seconds"
        elif "INSUFFICIENT_CREDITS" in error_str:
            error_str = "TinyFish credits exhausted"

        return ScanResult(
            status="error",
            error=error_str,
            scan_duration_ms=int((time.monotonic() - t0) * 1000),
        )


def _parse_scan_result(raw: str, duration_ms: int) -> ScanResult:
    """Parse TinyFish scan output into structured ScanResult."""
    # Try to extract JSON from the raw output
    try:
        json_match = re.search(r'\{[\s\S]*"fields"[\s\S]*\}', raw)
        if json_match:
            data = json.loads(json_match.group())
            fields = [
                FormField(
                    label=f.get("label", ""),
                    field_type=f.get("field_type", "text"),
                    required=f.get("required", False),
                    placeholder=f.get("placeholder", ""),
                    options=f.get("options", []),
                    field_name=f.get("field_name", ""),
                )
                for f in data.get("fields", [])
            ]
            return ScanResult(
                status=data.get("status", "scannable"),
                fields=fields,
                page_title=data.get("page_title", ""),
                form_count=data.get("form_count", 1),
                has_file_upload=data.get("has_file_upload", False),
                has_captcha=data.get("has_captcha", False),
                ats_type=_detect_ats_from_scan(data),
                raw_output=raw[:2000],
                scan_duration_ms=duration_ms,
            )
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: check for known status keywords (only when JSON parsing failed)
    raw_lower = raw.lower()
    if "login" in raw_lower or "sign in" in raw_lower or "create account" in raw_lower:
        return ScanResult(status="login_required", raw_output=raw[:2000], scan_duration_ms=duration_ms)
    # Only flag as CAPTCHA if the result explicitly says it's blocked — not just mentioning the word
    if ("captcha" in raw_lower and "blocked" in raw_lower) or raw_lower.strip().startswith('{"status": "captcha'):
        return ScanResult(status="captcha", has_captcha=True, raw_output=raw[:2000], scan_duration_ms=duration_ms)
    if "not found" in raw_lower or "404" in raw_lower:
        return ScanResult(status="not_found", raw_output=raw[:2000], scan_duration_ms=duration_ms)

    return ScanResult(
        status="error", error="Could not parse scan result", raw_output=raw[:2000], scan_duration_ms=duration_ms
    )


def _detect_ats_from_scan(data: dict) -> str | None:
    """Try to detect ATS type from scanned page content."""
    title = (data.get("page_title") or "").lower()
    if "greenhouse" in title:
        return "greenhouse"
    if "lever" in title:
        return "lever"
    if "workday" in title:
        return "workday"
    if "ashby" in title:
        return "ashby"
    return None


# ---------------------------------------------------------------------------
# Field matching — maps scanned fields to profile data
# ---------------------------------------------------------------------------

# Standard field patterns we can auto-fill from the profile
FIELD_PATTERNS: dict[str, list[str]] = {
    "first_name": ["first name", "given name", "first_name", "fname"],
    "last_name": ["last name", "surname", "family name", "last_name", "lname"],
    "full_name": ["full name", "name", "your name"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "telephone", "mobile", "cell", "phone number"],
    "phone_country_code": ["country code", "phone country", "dialing code", "dial code"],
    "linkedin": ["linkedin", "linkedin url", "linkedin profile"],
    "portfolio": ["website", "portfolio", "personal site", "url", "github"],
    "location": ["location", "city", "address", "where are you located"],
    "current_company": ["current company", "current employer", "company"],
    "current_title": ["current title", "current role", "job title", "current position"],
    "years_experience": ["years of experience", "years experience", "how many years"],
    "salary": ["salary", "compensation", "pay", "expected salary", "desired salary"],
    "start_date": ["start date", "availability", "when can you start", "notice period"],
    "visa": ["visa", "work authorization", "authorized to work"],
    "education": ["education", "degree", "university", "school"],
    "work_preference": ["working policy", "work arrangement", "remote or onsite", "hybrid"],
    "clearance": ["security clearance", "clearance level"],
}

# Fields that are custom/narrative and may need user input
NARRATIVE_PATTERNS: list[str] = [
    "why",
    "tell us",
    "describe",
    "what interests",
    "what excites",
    "what motivates",
    "cover letter",
    "additional information",
    "anything else",
    "biggest achievement",
    "proudest",
]

# Sensitive fields we must ask the user about
SENSITIVE_PATTERNS: list[str] = [
    "salary",
    "compensation",
    "pay expectation",
    "criminal",
    "background check",
    "felony",
    "disability",
    "veteran",
    "gender",
    "race",
    "ethnicity",
    "start date",
    "notice period",
    "sponsorship",
    "visa",
    "right to work",
    "authorized to work",
    "eligible to work",
]


def classify_field(label: str) -> str:
    """Classify a form field into auto_fill | narrative | sensitive | unknown.

    Returns the classification type.
    """
    label_lower = label.lower().strip()

    # Check sensitive first (takes priority)
    for pattern in SENSITIVE_PATTERNS:
        if pattern in label_lower:
            return "sensitive"

    # Check narrative
    for pattern in NARRATIVE_PATTERNS:
        if pattern in label_lower:
            return "narrative"

    # Check auto-fillable
    for field_key, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if pattern in label_lower:
                return "auto_fill"

    return "unknown"


def match_field_to_profile(label: str) -> str | None:
    """Return the profile field key that matches this form label, or None."""
    label_lower = label.lower().strip()
    for field_key, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if pattern in label_lower:
                return field_key
    return None


def analyze_scan(scan_result: ScanResult) -> dict:
    """Analyze a scan result and classify all fields.

    Returns:
    {
        "auto_fill": [{"label": ..., "profile_field": ...}, ...],
        "narrative": [{"label": ..., "field_type": ...}, ...],
        "sensitive": [{"label": ..., "field_type": ...}, ...],
        "unknown": [{"label": ..., "field_type": ...}, ...],
        "has_resume_upload": bool,
        "needs_user_input": bool,
        "total_fields": int,
        "auto_fillable_count": int,
    }
    """
    auto_fill = []
    narrative = []
    sensitive = []
    unknown = []

    for field in scan_result.fields:
        if field.field_type == "file":
            continue  # Handle resume upload separately

        classification = classify_field(field.label)
        entry = {
            "label": field.label,
            "field_type": field.field_type,
            "required": field.required,
            "options": field.options,
        }

        if classification == "auto_fill":
            entry["profile_field"] = match_field_to_profile(field.label)
            auto_fill.append(entry)
        elif classification == "narrative":
            narrative.append(entry)
        elif classification == "sensitive":
            sensitive.append(entry)
        else:
            unknown.append(entry)

    needs_user = len(narrative) > 0 or len(sensitive) > 0 or len(unknown) > 0

    return {
        "auto_fill": auto_fill,
        "narrative": narrative,
        "sensitive": sensitive,
        "unknown": unknown,
        "has_resume_upload": scan_result.has_file_upload,
        "needs_user_input": needs_user,
        "total_fields": len(scan_result.fields),
        "auto_fillable_count": len(auto_fill),
    }
