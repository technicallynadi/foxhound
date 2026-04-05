"""Greenhouse Job Board API submitter.

Public API, no auth required:
  GET  /v1/boards/{board}/jobs/{id}?questions=true  → form schema
  POST /v1/boards/{board}/jobs/{id}                 → submit application

Docs: https://developers.greenhouse.io/job-board.html
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

API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseSubmitter(ATSApiSubmitter):
    """Submit applications via the Greenhouse Job Board API."""

    async def get_form_schema(self, url_info: ATSUrlInfo) -> ScanResult:
        """Fetch job posting + application questions from Greenhouse API."""
        url = f"{API_BASE}/{url_info.board_token}/jobs/{url_info.job_id}?questions=true"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Greenhouse API %d for %s/%s",
                    e.response.status_code,
                    url_info.board_token,
                    url_info.job_id,
                )
                raise ApiSubmitFallbackError(f"Greenhouse API returned {e.response.status_code}") from e
            except httpx.RequestError as e:
                raise ApiSubmitFallbackError(f"Greenhouse API request failed: {e}") from e

        data = resp.json()
        questions = data.get("questions") or []

        # Build FormField list from API questions
        fields: list[FormField] = []
        seen_names: set[str] = set()

        # Custom questions from the API (includes standard fields like first_name, email)
        # Standard field name → better type mapping
        _STANDARD_TYPES = {
            "first_name": "text",
            "last_name": "text",
            "email": "email",
            "phone": "tel",
            "resume": "file",
            "cover_letter": "file",
            "location": "text",
            "linkedin_profile_url": "url",
            "website_url": "url",
        }

        for q in questions:
            q_fields = q.get("fields") or []
            label = q.get("label") or q.get("description") or ""
            required = q.get("required", False)

            if not q_fields:
                continue

            field_def = q_fields[0]
            field_name = field_def.get("name", "")

            # Skip duplicates
            if field_name in seen_names:
                continue
            seen_names.add(field_name)

            # Use standard type if this is a known field, otherwise map from API type
            field_type = field_def.get("type", "input_text")
            if field_name in _STANDARD_TYPES:
                normalized_type = _STANDARD_TYPES[field_name]
            else:
                type_map = {
                    "input_text": "text",
                    "input_hidden": "hidden",
                    "textarea": "textarea",
                    "multi_value_single_select": "select",
                    "multi_value_multi_select": "select",
                }
                normalized_type = type_map.get(field_type, "text")

            # Extract options for select fields
            options = []
            values = field_def.get("values") or []
            for v in values:
                if isinstance(v, dict):
                    options.append(v.get("label", str(v.get("value", ""))))
                else:
                    options.append(str(v))

            fields.append(
                FormField(
                    label=label,
                    field_type=normalized_type,
                    required=required,
                    options=options,
                    field_name=field_name,
                )
            )

        logger.info(
            "Greenhouse API schema: %s/%s — %d fields (%d custom questions)",
            url_info.board_token,
            url_info.job_id,
            len(fields),
            len(questions),
        )

        return ScanResult(
            status="scannable",
            fields=fields,
            page_title=data.get("title", ""),
            has_file_upload=True,
            ats_type="greenhouse",
        )

    async def submit(
        self,
        url_info: ATSUrlInfo,
        profile_data: dict[str, Any],
        custom_answers: list[dict],
        resume_bytes: bytes | None = None,
        resume_filename: str = "resume.pdf",
    ) -> ApiSubmitResult:
        """Submit application via Greenhouse Job Board API POST."""
        url = f"{API_BASE}/{url_info.board_token}/jobs/{url_info.job_id}"

        # Build form data — standard fields
        form_data: dict[str, str] = {
            "first_name": profile_data.get("first_name", ""),
            "last_name": profile_data.get("last_name", ""),
            "email": profile_data.get("email", ""),
            "phone": profile_data.get("phone", ""),
            "location": profile_data.get("location", ""),
            "linkedin_profile_url": profile_data.get("linkedin", ""),
            "website_url": profile_data.get("portfolio", ""),
        }

        # Map custom answers by field_name or question label
        for ans in custom_answers:
            question = ans.get("question", "")
            answer = ans.get("answer", "")
            field_name = ans.get("field_name", "")

            if field_name:
                form_data[field_name] = answer
            else:
                # Match by label — the field_name from get_form_schema
                # was stored in the ScanResult, but we may only have the label here
                form_data[question] = answer

        # Remove empty values
        form_data = {k: v for k, v in form_data.items() if v}

        # Build multipart payload
        files: dict[str, tuple[str, bytes, str]] = {}
        if resume_bytes:
            files["resume"] = (resume_filename, resume_bytes, "application/pdf")

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, data=form_data, files=files or None)
            except httpx.RequestError as e:
                logger.warning("Greenhouse submit request failed: %s", e)
                raise ApiSubmitFallbackError(f"Network error: {e}") from e

        if resp.status_code == 200:
            logger.info(
                "Greenhouse API submit SUCCESS: %s/%s",
                url_info.board_token,
                url_info.job_id,
            )
            return ApiSubmitResult(
                status="submitted",
                confirmation_text="Application submitted via Greenhouse API",
                raw_response=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
            )

        if resp.status_code == 422:
            # Validation error — missing required fields or invalid data
            error_body = resp.text[:500]
            logger.warning("Greenhouse submit 422: %s", error_body)
            return ApiSubmitResult(
                status="failed",
                error=f"Validation error: {error_body}",
            )

        if resp.status_code == 429:
            logger.warning("Greenhouse submit rate limited")
            return ApiSubmitResult(status="rate_limited", error="Rate limited by Greenhouse")

        logger.warning(
            "Greenhouse submit %d: %s",
            resp.status_code,
            resp.text[:300],
        )
        raise ApiSubmitFallbackError(f"Greenhouse API returned {resp.status_code}: {resp.text[:200]}")
