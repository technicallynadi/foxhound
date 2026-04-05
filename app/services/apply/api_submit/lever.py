"""Lever Postings API submitter.

Public API, no auth required for most companies:
  GET  /v0/postings/{company}/{posting_id}  → posting details
  POST /v0/postings/{company}/{posting_id}  → submit application

This is especially valuable because Lever uses hCaptcha on its web forms,
making browser automation impossible. The API bypasses this entirely.

Docs: https://github.com/lever/postings-api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.apply.api_submit.base import (
    ApiSubmitFallbackError,
    ApiSubmitResult,
    ATSApiSubmitter,
)
from app.services.apply.ats_url_parser import ATSUrlInfo
from app.services.apply.form_scanner import FormField, ScanResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.lever.co/v0/postings"


class LeverSubmitter(ATSApiSubmitter):
    """Submit applications via the Lever Postings API."""

    async def get_form_schema(self, url_info: ATSUrlInfo) -> ScanResult:
        """Fetch posting details from Lever API."""
        url = f"{API_BASE}/{url_info.board_token}/{url_info.job_id}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ApiSubmitFallbackError(
                    f"Lever API returned {e.response.status_code}"
                ) from e
            except httpx.RequestError as e:
                raise ApiSubmitFallbackError(f"Lever API request failed: {e}") from e

        data = resp.json()

        # Build FormField list
        fields: list[FormField] = []

        # Standard Lever fields
        fields.append(FormField(label="Full Name", field_type="text", required=True, field_name="name"))
        fields.append(FormField(label="Email", field_type="email", required=True, field_name="email"))
        fields.append(FormField(label="Phone", field_type="tel", required=False, field_name="phone"))
        fields.append(FormField(label="Current Company", field_type="text", required=False, field_name="org"))
        fields.append(FormField(label="Resume/CV", field_type="file", required=True, field_name="resume"))
        fields.append(FormField(label="LinkedIn", field_type="url", required=False, field_name="urls[LinkedIn]"))
        fields.append(FormField(label="Website", field_type="url", required=False, field_name="urls[Portfolio]"))
        fields.append(FormField(label="Cover Letter", field_type="textarea", required=False, field_name="comments"))

        # Custom questions from Lever's "lists" field
        lists = data.get("lists") or []
        for lst in lists:
            label = lst.get("text", "")
            required = lst.get("required", False)

            # Lever custom fields can be text or select
            options = lst.get("options") or []
            if options:
                # Select/radio field
                fields.append(FormField(
                    label=label,
                    field_type="select",
                    required=required,
                    options=options,
                    field_name=f"cards[{label}]",
                ))
            else:
                fields.append(FormField(
                    label=label,
                    field_type="textarea" if len(label) > 60 else "text",
                    required=required,
                    field_name=f"cards[{label}]",
                ))

        logger.info(
            "Lever API schema: %s/%s — %d fields (%d custom questions)",
            url_info.board_token, url_info.job_id, len(fields), len(lists),
        )

        return ScanResult(
            status="scannable",
            fields=fields,
            page_title=data.get("text", ""),
            has_file_upload=True,
            ats_type="lever",
        )

    async def submit(
        self,
        url_info: ATSUrlInfo,
        profile_data: dict[str, Any],
        custom_answers: list[dict],
        resume_bytes: bytes | None = None,
        resume_filename: str = "resume.pdf",
    ) -> ApiSubmitResult:
        """Submit application via Lever Postings API."""
        url = f"{API_BASE}/{url_info.board_token}/{url_info.job_id}"

        # Build form data — Lever uses flat field names
        full_name = profile_data.get("full_name", "")
        if not full_name:
            full_name = f"{profile_data.get('first_name', '')} {profile_data.get('last_name', '')}".strip()

        form_data: dict[str, str] = {
            "name": full_name,
            "email": profile_data.get("email", ""),
            "phone": profile_data.get("phone", ""),
            "org": profile_data.get("current_company", ""),
            "urls[LinkedIn]": profile_data.get("linkedin", ""),
            "urls[Portfolio]": profile_data.get("portfolio", ""),
        }

        # Custom answers → cards format
        for ans in custom_answers:
            question = ans.get("question", "")
            answer = ans.get("answer", "")
            field_name = ans.get("field_name", "")

            if field_name:
                form_data[field_name] = answer
            else:
                form_data[f"cards[{question}]"] = answer

        form_data = {k: v for k, v in form_data.items() if v}

        files: dict[str, tuple[str, bytes, str]] = {}
        if resume_bytes:
            files["resume"] = (resume_filename, resume_bytes, "application/pdf")

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, data=form_data, files=files or None)
            except httpx.RequestError as e:
                raise ApiSubmitFallbackError(f"Network error: {e}") from e

        if resp.status_code == 200:
            logger.info("Lever API submit SUCCESS: %s/%s", url_info.board_token, url_info.job_id)
            return ApiSubmitResult(
                status="submitted",
                confirmation_text="Application submitted via Lever API",
                raw_response=resp.json() if "application/json" in resp.headers.get("content-type", "") else {},
            )

        if resp.status_code in (401, 403):
            raise ApiSubmitFallbackError(
                f"Lever API auth required ({resp.status_code}) — falling back to browser"
            )

        if resp.status_code == 429:
            return ApiSubmitResult(status="rate_limited", error="Rate limited by Lever")

        logger.warning("Lever submit %d: %s", resp.status_code, resp.text[:300])
        return ApiSubmitResult(
            status="failed",
            error=f"Lever API {resp.status_code}: {resp.text[:200]}",
        )
