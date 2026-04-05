"""Base types and protocol for ATS API submission."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.services.apply.ats_url_parser import ATSUrlInfo
from app.services.apply.form_scanner import ScanResult


class ApiSubmitFallbackError(Exception):
    """Raised when API submission fails and we should fall back to browser."""
    pass


@dataclass
class ApiSubmitResult:
    status: str  # "submitted" | "failed" | "rate_limited"
    confirmation_text: str = ""
    error: str = ""
    raw_response: dict = field(default_factory=dict)


class ATSApiSubmitter(ABC):
    """Abstract base for ATS API submitters.

    Each submitter implements two methods:
    1. get_form_schema() — replaces TinyFish scan
    2. submit() — replaces Playwright fill + submit
    """

    @abstractmethod
    async def get_form_schema(self, url_info: ATSUrlInfo) -> ScanResult:
        """Fetch the form schema from the ATS API.

        Returns a ScanResult with FormField objects, compatible with
        the existing analyze_scan() pipeline.

        Raises ApiSubmitFallbackError if the API is unavailable.
        """
        ...

    @abstractmethod
    async def submit(
        self,
        url_info: ATSUrlInfo,
        profile_data: dict[str, Any],
        custom_answers: list[dict],
        resume_bytes: bytes | None = None,
        resume_filename: str = "resume.pdf",
    ) -> ApiSubmitResult:
        """Submit the application via the ATS API.

        Args:
            url_info: Parsed ATS URL identifiers.
            profile_data: Flat dict from _build_profile_data().
            custom_answers: List of {"question": ..., "answer": ...} dicts.
            resume_bytes: PDF bytes for resume upload.
            resume_filename: Resume filename.

        Returns ApiSubmitResult.
        Raises ApiSubmitFallbackError if we should fall back to browser.
        """
        ...
