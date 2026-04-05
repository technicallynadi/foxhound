"""TinyFish application prompt templates."""

from __future__ import annotations

import json
import logging
import os
import re

from app.api.routes.files import create_file_token
from app.core.config import settings
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.services.discovery.ats_detector import detect_ats

logger = logging.getLogger(__name__)

# Maps form field labels to profile data keys.
# Used to determine which profile fields to include in the prompt.
_FIELD_TO_PROFILE = {
    "first_name": ["first name", "given name", "fname"],
    "last_name": ["last name", "surname", "family name", "lname"],
    "full_name": ["full name", "name", "your name"],
    "email": ["email", "e-mail"],
    "phone": ["phone", "telephone", "mobile", "cell"],
    "linkedin": ["linkedin"],
    "portfolio": ["website", "portfolio", "github", "url"],
    "location": ["location", "city", "address", "where"],
    "company": ["current company", "current employer", "company"],
    "title": ["current title", "current role", "job title", "current position"],
}


def _scan_needs_field(scan_labels: set[str], profile_key: str) -> bool:
    """Check if any scanned form label matches a profile field."""
    patterns = _FIELD_TO_PROFILE.get(profile_key, [])
    return any(p in label for label in scan_labels for p in patterns)


def _build_profile_block(profile: UserProfile, scan_labels: set[str] | None) -> str:
    """Build the profile details block, only including fields the form has.

    If scan_labels is None (no scan data), include all fields (safe default).
    """
    experience = json.loads(profile.experience_json or "[]")
    current = experience[0] if experience else {}

    name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()

    # Always include name and email — every form has these
    lines = [f"{name} is applying for a role. Their details:"]
    lines.append(f"- Email: {profile.email or ''}")

    # Conditionally include other fields
    include_all = scan_labels is None

    if include_all or _scan_needs_field(scan_labels, "phone"):
        if profile.phone:
            lines.append(f"- Phone: {profile.phone}")

    if include_all or _scan_needs_field(scan_labels, "linkedin"):
        if profile.linkedin_url:
            lines.append(f"- LinkedIn: {profile.linkedin_url}")

    if include_all or _scan_needs_field(scan_labels, "portfolio"):
        if profile.portfolio_url:
            lines.append(f"- Portfolio: {profile.portfolio_url}")

    if include_all or _scan_needs_field(scan_labels, "location"):
        if profile.location:
            lines.append(f"- Location: {profile.location}")

    if include_all or _scan_needs_field(scan_labels, "company") or _scan_needs_field(scan_labels, "title"):
        title = current.get("title", "")
        company = current.get("company", "")
        if title or company:
            lines.append(f"- Current role: {title} at {company}".rstrip(" at "))

    return "\n".join(lines)


def build_custom_questions_block(answers: list[dict]) -> str:
    """Build the custom questions block for the TinyFish prompt."""
    if not answers:
        return ""

    lines = ["Custom questions:"]
    for i, a in enumerate(answers, 1):
        lines.append(f'  Q{i}: "{a["question"]}"')
        lines.append(f'  A{i}: "{a["answer"]}"')
        lines.append("")
    return "\n".join(lines)


def build_dropdown_selections_block(scan_fields: list[dict] | None, profile: UserProfile | None = None) -> str:
    """Build dropdown selection instructions from scanned form fields."""
    if not scan_fields:
        return ""

    from app.services.apply.ats_profiles import get_dropdown_selection

    profile_data = {}
    if profile:
        profile_data = {"visa_status": profile.visa_status}

    lines = ["Dropdown selections:"]
    has_any = False
    for field in scan_fields:
        if field.get("field_type") not in ("select", "radio"):
            continue
        options = field.get("options", [])
        if not options:
            continue

        selection = get_dropdown_selection(field.get("label", ""), options, profile_data)
        if selection:
            lines.append(f'  Field: "{field["label"]}"')
            lines.append(f'  Select: "{selection}"')
            lines.append("")
            has_any = True

    return "\n".join(lines) if has_any else ""


def build_resume_js(profile: UserProfile, apply_url: str) -> list[str] | None:
    """Build JS commands to inject resume into the form's file input.

    Strategy per ATS:
    - Greenhouse: file proxy fetch (no CSP restrictions, single JS command)
    - Ashby: skip (CSP blocks external fetch, javascript: URLs restricted)
    - Lever: skip (hCaptcha blocks auto-apply anyway)
    - Unknown: try file proxy, fall back to skip

    Returns a list of JS commands, or None if resume upload should be skipped.
    """
    if not profile.resume_storage_path:
        return None

    ats = detect_ats(apply_url)
    filename = _safe_js_filename(profile.resume_filename)

    # Ashby blocks both javascript: URLs and external fetch via CSP
    if ats == "ashby":
        logger.info("Skipping resume injection for Ashby (CSP + JS restrictions)")
        return None

    # Lever: auto-apply blocked by hCaptcha, skip resume
    if ats == "lever":
        logger.info("Skipping resume injection for Lever (hCaptcha)")
        return None

    # Try file proxy approach (single fetch command — works on Greenhouse + unknown)
    base_url = settings.APP_BASE_URL.rstrip("/")
    if base_url and "127.0.0.1" not in base_url and "localhost" not in base_url:
        # Production: use file proxy
        parts = profile.resume_storage_path.split("/", 1)
        if len(parts) == 2:
            token = create_file_token(parts[0], parts[1])
            proxy_url = f"{base_url}/api/v1/files/serve/{token}"
            return [_build_resume_fetch_js(proxy_url, filename)]

    logger.info("No public base URL — skipping resume injection")
    return None


def _build_resume_fetch_js(proxy_url: str, filename: str) -> str:
    """Single JS command that fetches resume from our proxy and injects into file input.

    Uses DataTransfer API + React _valueTracker reset for compatibility
    with React-based ATS forms (Greenhouse, Lever).
    """
    return (
        f"javascript:void((async function(){{"
        f"try{{"
        f"var r=await fetch('{proxy_url}');"
        f"if(!r.ok){{document.title='FETCH_FAILED:'+r.status;return}}"
        f"var b=await r.blob();"
        f"var f=new File([b],'{filename}',{{type:'application/pdf'}});"
        f"var dt=new DataTransfer();"
        f"dt.items.add(f);"
        f"var inp=document.querySelector('input[type=file]');"
        f"if(inp){{"
        f"inp.files=dt.files;"
        # Reset React's internal value tracker so it detects the change
        f"var t=inp._valueTracker;if(t)t.setValue('');"
        # Fire both events: React listens on 'input', native on 'change'
        f"inp.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"inp.dispatchEvent(new Event('change',{{bubbles:true}}));"
        f"document.title='RESUME_UPLOADED'}}"
        f"else{{document.title='NO_FILE_INPUT'}}"
        f"}}catch(e){{document.title='FETCH_FAILED:'+e.message}}"
        f"}})())"
    )


def build_prompt(
    profile: UserProfile,
    job: JobListing,
    answers: list[dict] | None = None,
    scan_fields: list[dict] | None = None,
    resume_b64: str | None = None,
) -> str:
    """Build the complete TinyFish application prompt.

    Only includes profile fields that the form scan found on the page.
    This minimizes PII exposure in the TinyFish goal prompt.

    Resume injection uses the file proxy approach (single fetch command)
    instead of base64 chunks. resume_b64 is kept for backwards compat
    but no longer used — the proxy URL is generated from the profile's
    storage path.
    """
    # Extract scanned field labels for minimization
    scan_labels: set[str] | None = None
    if scan_fields:
        scan_labels = {f.get("label", "").lower().strip() for f in scan_fields}

    profile_block = _build_profile_block(profile, scan_labels)
    custom_block = build_custom_questions_block(answers or [])
    dropdown_block = build_dropdown_selections_block(scan_fields, profile)

    # Get resume injection JS (per-ATS strategy)
    resume_js_commands = build_resume_js(profile, job.apply_url)

    # Build the goal prompt
    sections = [
        f"Fill out the job application form with this information:\n\n{profile_block}",
    ]

    if dropdown_block:
        sections.append(dropdown_block)
    if custom_block:
        sections.append(custom_block)

    steps = [
        "1. If a cookie/consent banner appears, close it first",
        "2. Fill all matching form fields with the information above",
        "3. For dropdowns, select the exact option text listed",
    ]

    if resume_js_commands:
        step_num = 4
        steps.append(f"{step_num}. Upload resume by running this command in the address bar:")
        for js_cmd in resume_js_commands:
            step_num += 1
            steps.append(f"   {step_num}. Run in address bar: {js_cmd}")
        step_num += 1
        steps.append(f"{step_num}. Click the Submit / Apply button")
        step_num += 1
        steps.append(f"{step_num}. Wait for the confirmation page")
    else:
        steps.append("4. Skip the resume/file upload field if present")
        steps.append("5. Click the Submit / Apply button")
        steps.append("6. Wait for the confirmation page")

    sections.append("Complete these steps:\n\n" + "\n".join(steps))

    sections.append(
        'If you see a login/signup page, stop and report status "needs_account".\n'
        'If you see a CAPTCHA, stop and report status "captcha_detected".\n'
        'If email verification is required, stop and report status "email_verification_required".\n'
        'If you see "I certify this was completed by me personally", stop and report status "personal_certification_required".\n'
        "Do not fill hidden fields.\n\n"
        "Return JSON:\n"
        "{\n"
        '  "status": "submitted",\n'
        '  "fields_filled": ["first_name", "last_name", "email"],\n'
        '  "resume_attached": true,\n'
        '  "confirmation_text": "Thank you for applying!",\n'
        '  "errors": []\n'
        "}"
    )

    return "\n\n".join(sections)


def _safe_js_filename(name: str | None) -> str:
    """Sanitize filename for safe interpolation into a JS string literal."""
    safe = os.path.basename(name or "resume.pdf")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", safe)
    if not safe.lower().endswith(".pdf"):
        safe = "resume.pdf"
    return safe
