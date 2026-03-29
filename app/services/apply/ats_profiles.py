"""ATS-specific form profiles.

Every ATS has a different form structure. This module captures what we know
about each one so the scanner and filler can handle the differences.

Key variations across ATS platforms:
- Single page vs multi-page forms
- Account creation required vs anonymous apply
- File upload method (button, drag-drop, inline)
- Dropdown options (how did you hear, visa status, etc.)
- Custom question placement (inline, separate page, modal)
- Submit button text and location
- Confirmation page patterns
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ATSProfile:
    """Known behavior patterns for a specific ATS."""

    name: str
    multi_page: bool = False
    requires_account: bool = False
    typical_pages: list[str] = field(default_factory=list)
    file_upload_method: str = "button"  # button | drag_drop | inline
    resume_field_label: str = "Resume/CV"
    submit_button_text: list[str] = field(default_factory=list)
    confirmation_patterns: list[str] = field(default_factory=list)
    known_dropdowns: dict[str, list[str]] = field(default_factory=dict)
    next_button_text: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


GREENHOUSE_PROFILE = ATSProfile(
    name="greenhouse",
    multi_page=False,
    requires_account=False,
    typical_pages=["Single page with all fields"],
    file_upload_method="button",
    resume_field_label="Resume/CV",
    submit_button_text=["Submit Application", "Submit", "Apply"],
    confirmation_patterns=[
        "Application submitted",
        "Thank you for applying",
        "We have received your application",
    ],
    known_dropdowns={
        "how_did_you_hear": [
            "LinkedIn", "Indeed", "Glassdoor", "Company Website",
            "Friend/Referral", "Job Board", "Social Media", "Other",
        ],
        "authorized_to_work": ["Yes", "No"],
        "sponsorship_needed": ["Yes", "No"],
        "gender": ["Male", "Female", "Non-binary", "Prefer not to say", "Decline to self identify"],
        "race": ["Decline to self identify"],
        "veteran": ["I am not a protected veteran", "Decline to self identify"],
        "disability": ["No, I do not have a disability", "Decline to self identify"],
    },
    notes=[
        "Greenhouse forms are usually single-page",
        "Custom questions appear below standard fields",
        "File upload is a standard <input type='file'>",
        "EEO/demographic questions are optional — select 'Decline' or skip",
    ],
)

LEVER_PROFILE = ATSProfile(
    name="lever",
    multi_page=False,
    requires_account=False,
    typical_pages=["Single page: info + resume + custom questions"],
    file_upload_method="button",
    resume_field_label="Resume/CV",
    submit_button_text=["Submit application", "Submit", "Apply for this job"],
    confirmation_patterns=[
        "Application submitted",
        "Thanks for applying",
        "Your application has been submitted",
    ],
    known_dropdowns={
        "how_did_you_hear": [
            "LinkedIn", "Glassdoor", "Company Website", "Referral", "Other",
        ],
    },
    notes=[
        "Lever forms are single-page with a clean layout",
        "Resume upload is prominent at the top",
        "Custom questions appear as additional fields below",
        "Some Lever forms have a cover letter textarea",
    ],
)

WORKDAY_PROFILE = ATSProfile(
    name="workday",
    multi_page=True,
    requires_account=True,
    typical_pages=[
        "Page 1: Create account / Sign in",
        "Page 2: Personal information (name, email, phone, address)",
        "Page 3: Experience (work history, education)",
        "Page 4: Resume upload + cover letter",
        "Page 5: Self-identification (EEO, veteran, disability)",
        "Page 6: Review and submit",
    ],
    file_upload_method="button",
    resume_field_label="Resume",
    submit_button_text=["Submit", "Submit Application"],
    confirmation_patterns=["Successfully Submitted", "Application Submitted"],
    next_button_text=["Next", "Continue", "Save and Continue"],
    known_dropdowns={
        "country": ["United States"],
        "state": [],  # varies
        "phone_type": ["Mobile", "Home", "Work"],
    },
    notes=[
        "REQUIRES account creation — TinyFish may need to handle signup",
        "Multi-page: must click 'Next' between pages",
        "Address fields are detailed (street, city, state, zip, country)",
        "Workday has its own autofill from resume — may conflict with ours",
        "Session can timeout if too slow between pages",
    ],
)

ASHBY_PROFILE = ATSProfile(
    name="ashby",
    multi_page=False,
    requires_account=False,
    typical_pages=["Single page with sections"],
    file_upload_method="button",
    resume_field_label="Resume",
    submit_button_text=["Submit Application", "Submit", "Apply"],
    confirmation_patterns=[
        "Application submitted",
        "Thank you for your application",
    ],
    known_dropdowns={
        "how_did_you_hear": [
            "LinkedIn", "Twitter", "Company Blog", "Referral",
            "Job Board", "Search Engine", "Other",
        ],
    },
    notes=[
        "Ashby forms are clean, single-page",
        "Similar to Greenhouse layout",
        "Some have compensation expectation fields",
        "Custom questions are inline",
    ],
)

# Registry of all known ATS profiles
ATS_PROFILES: dict[str, ATSProfile] = {
    "greenhouse": GREENHOUSE_PROFILE,
    "lever": LEVER_PROFILE,
    "workday": WORKDAY_PROFILE,
    "ashby": ASHBY_PROFILE,
}

# Default dropdown selections for common EEO/demographic questions
# These are "decline to answer" options — safe defaults
DEFAULT_DROPDOWN_SELECTIONS: dict[str, str] = {
    "gender": "Decline to self identify",
    "race": "Decline to self identify",
    "ethnicity": "Decline to self identify",
    "veteran": "I am not a protected veteran",
    "disability": "No, I do not have a disability",
    "how_did_you_hear": "Job Board",
}


def get_ats_profile(ats_type: str | None) -> ATSProfile | None:
    """Get the ATS profile for a given type, or None if unknown."""
    if not ats_type:
        return None
    return ATS_PROFILES.get(ats_type.lower())


def get_dropdown_selection(field_label: str, options: list[str], profile_data: dict | None = None) -> str | None:
    """Pick the best dropdown option based on field label and available options.

    For EEO/demographic questions, defaults to "Decline" options.
    For factual questions, tries to match from profile data.
    """
    label_lower = field_label.lower()

    # EEO/demographic — always decline
    for key, default_value in DEFAULT_DROPDOWN_SELECTIONS.items():
        if key in label_lower:
            # Find the closest match in available options
            for opt in options:
                if default_value.lower() in opt.lower() or "decline" in opt.lower():
                    return opt
            # If no decline option, return last option (usually "prefer not to say")
            if options:
                for opt in options:
                    if "prefer not" in opt.lower() or "not to" in opt.lower():
                        return opt

    # Work authorization
    if any(kw in label_lower for kw in ["authorized", "authorization", "legally"]):
        if profile_data and profile_data.get("visa_status") in ("citizen", "green_card"):
            for opt in options:
                if "yes" in opt.lower():
                    return opt

    # Sponsorship
    if "sponsor" in label_lower:
        if profile_data and profile_data.get("visa_status") in ("citizen", "green_card"):
            for opt in options:
                if "no" in opt.lower():
                    return opt
        elif profile_data and profile_data.get("visa_status") in ("h1b", "opt", "need_sponsorship"):
            for opt in options:
                if "yes" in opt.lower():
                    return opt

    # How did you hear — default to Job Board
    if "how did you" in label_lower or "hear about" in label_lower or "source" in label_lower:
        for opt in options:
            if "job board" in opt.lower() or "other" in opt.lower():
                return opt
        if options:
            return options[-1]  # Usually "Other" is last

    return None
