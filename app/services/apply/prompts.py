"""TinyFish application prompt templates."""

from __future__ import annotations

import json
import os
import re

from app.api.routes.files import create_file_token
from app.core.config import settings
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile

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


def build_dropdown_selections_block(
    scan_fields: list[dict] | None, profile: UserProfile | None = None
) -> str:
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

        selection = get_dropdown_selection(
            field.get("label", ""), options, profile_data
        )
        if selection:
            lines.append(f'  Field: "{field["label"]}"')
            lines.append(f'  Select: "{selection}"')
            lines.append("")
            has_any = True

    return "\n".join(lines) if has_any else ""


def build_prompt(
    profile: UserProfile,
    job: JobListing,
    answers: list[dict] | None = None,
    scan_fields: list[dict] | None = None,
) -> str:
    """Build the complete TinyFish application prompt.

    Only includes profile fields that the form scan found on the page.
    This minimizes PII exposure in the TinyFish goal prompt.
    """
    # Extract scanned field labels for minimization
    scan_labels: set[str] | None = None
    if scan_fields:
        scan_labels = {f.get("label", "").lower().strip() for f in scan_fields}

    profile_block = _build_profile_block(profile, scan_labels)
    custom_block = build_custom_questions_block(answers or [])
    dropdown_block = build_dropdown_selections_block(scan_fields, profile)

    resume_url = ""
    resume_filename = _safe_js_filename(profile.resume_filename)
    if profile.resume_storage_path:
        parts = profile.resume_storage_path.split("/", 1)
        if len(parts) == 2:
            token = create_file_token(parts[0], parts[1])
            # Use public Fly URL so TinyFish (cloud browser) can fetch the resume
            # The /api/v1/files/serve endpoint has Access-Control-Allow-Origin: *
            fly_url = os.environ.get("FOXHOUND_PUBLIC_URL", settings.APP_BASE_URL).rstrip("/")
            resume_url = f"{fly_url}/api/v1/files/serve/{token}"

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

    if resume_url:
        steps.append(
            f"4. Upload resume: run in address bar: javascript:void((async()=>{{const r=await fetch('{resume_url}');"
            f"const b=await r.blob();const f=new File([b],'{resume_filename}',"
            f"{{type:'application/pdf'}});const dt=new DataTransfer();dt.items.add(f);"
            f"const inputs=document.querySelectorAll('input[type=file]');"
            f"if(inputs.length===0)return;const input=inputs[0];input.files=dt.files;"
            f"input.dispatchEvent(new Event('change',{{bubbles:true}}));"
            f"input.dispatchEvent(new Event('input',{{bubbles:true}}))}})())"
        )
        steps.append(f"{len(steps)+1}. Click the Submit / Apply button")
        steps.append(f"{len(steps)+1}. Wait for the confirmation page")
    else:
        steps.append("4. Click the Submit / Apply button")
        steps.append("5. Wait for the confirmation page")

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
