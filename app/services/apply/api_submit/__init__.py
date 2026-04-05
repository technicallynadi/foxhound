"""ATS API direct submission — bypasses browser automation.

Registry that maps ATS type → submitter. The orchestrator checks here
first; if a submitter exists, it uses the API path. Otherwise falls
back to TinyFish/Playwright browser automation.
"""

from __future__ import annotations

from app.services.apply.api_submit.base import ATSApiSubmitter


def get_api_submitter(ats_type: str | None) -> ATSApiSubmitter | None:
    """Return the API submitter for an ATS type, or None."""
    if not ats_type:
        return None
    # Lazy imports to avoid circular deps
    if ats_type == "greenhouse":
        from app.services.apply.api_submit.greenhouse import GreenhouseSubmitter

        return GreenhouseSubmitter()
    if ats_type == "lever":
        from app.services.apply.api_submit.lever import LeverSubmitter

        return LeverSubmitter()
    if ats_type == "ashby":
        from app.services.apply.api_submit.ashby import AshbySubmitter

        return AshbySubmitter()
    return None
