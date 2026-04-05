"""Ashby posting API submitter.

Ashby's posting API:
  POST /posting-api/posting-info         → form schema + fields
  POST /posting-api/application-form/submit → submit application

No auth required. JSON API.
Docs: https://developers.ashbyhq.com/docs/application-form-api
"""

from __future__ import annotations

import base64
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

API_BASE = "https://api.ashbyhq.com/posting-api"


class AshbySubmitter(ATSApiSubmitter):
    """Submit applications via the Ashby posting API."""

    async def get_form_schema(self, url_info: ATSUrlInfo) -> ScanResult:
        """Fetch application form fields from Ashby API."""
        url = f"{API_BASE}/posting-info"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    url,
                    json={"postingId": url_info.job_id},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ApiSubmitFallbackError(
                    f"Ashby API returned {e.response.status_code}"
                ) from e
            except httpx.RequestError as e:
                raise ApiSubmitFallbackError(f"Ashby API request failed: {e}") from e

        data = resp.json()
        info = data.get("info") or data
        form_def = info.get("applicationFormDefinition") or {}
        sections = form_def.get("sections") or []

        fields: list[FormField] = []

        for section in sections:
            for field_def in section.get("fieldDefinitions") or []:
                label = field_def.get("title") or field_def.get("label") or ""
                required = field_def.get("isRequired", False)
                field_path = field_def.get("path", "")
                field_type_raw = field_def.get("type", "String")

                # Map Ashby types to our standard types
                type_map = {
                    "String": "text",
                    "LongText": "textarea",
                    "Email": "email",
                    "Phone": "tel",
                    "File": "file",
                    "URL": "url",
                    "ValueSelect": "select",
                    "MultiValueSelect": "select",
                    "Boolean": "select",
                    "Date": "date",
                    "Number": "number",
                }
                normalized_type = type_map.get(field_type_raw, "text")

                # Extract options
                options = []
                for opt in field_def.get("selectableValues") or []:
                    if isinstance(opt, dict):
                        options.append(opt.get("label", str(opt.get("value", ""))))
                    else:
                        options.append(str(opt))

                fields.append(FormField(
                    label=label,
                    field_type=normalized_type,
                    required=required,
                    options=options,
                    field_name=field_path,
                ))

        # Ensure we always have resume upload
        has_file = any(f.field_type == "file" for f in fields)
        if not has_file:
            fields.append(FormField(label="Resume/CV", field_type="file", required=True, field_name="_systemfield_resume"))

        logger.info(
            "Ashby API schema: %s/%s — %d fields",
            url_info.board_token, url_info.job_id, len(fields),
        )

        return ScanResult(
            status="scannable",
            fields=fields,
            page_title=info.get("title", ""),
            has_file_upload=True,
            ats_type="ashby",
        )

    async def submit(
        self,
        url_info: ATSUrlInfo,
        profile_data: dict[str, Any],
        custom_answers: list[dict],
        resume_bytes: bytes | None = None,
        resume_filename: str = "resume.pdf",
    ) -> ApiSubmitResult:
        """Submit application via Ashby posting API."""
        url = f"{API_BASE}/application-form/submit"

        # Build field values — Ashby uses path-based field mapping
        field_values: list[dict] = []

        # Standard fields — Ashby uses path conventions
        standard_map = {
            "_systemfield_name": profile_data.get("full_name", "")
                or f"{profile_data.get('first_name', '')} {profile_data.get('last_name', '')}".strip(),
            "_systemfield_email": profile_data.get("email", ""),
            "_systemfield_phone": profile_data.get("phone", ""),
            "_systemfield_linkedInUrl": profile_data.get("linkedin", ""),
            "_systemfield_websiteUrl": profile_data.get("portfolio", ""),
            "_systemfield_currentCompany": profile_data.get("current_company", ""),
            "_systemfield_location": profile_data.get("location", ""),
        }

        for path, value in standard_map.items():
            if value:
                field_values.append({"path": path, "value": value})

        # Custom answers
        for ans in custom_answers:
            field_name = ans.get("field_name", "")
            answer = ans.get("answer", "")
            if field_name and answer:
                field_values.append({"path": field_name, "value": answer})

        # Build payload
        payload: dict[str, Any] = {
            "postingId": url_info.job_id,
            "applicationForm": field_values,
        }

        # Resume — Ashby accepts base64 file in the submission
        if resume_bytes:
            b64 = base64.b64encode(resume_bytes).decode("utf-8")
            # Add resume as a file field value
            field_values.append({
                "path": "_systemfield_resume",
                "value": {
                    "fileName": resume_filename,
                    "mimeType": "application/pdf",
                    "content": b64,
                },
            })

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload)
            except httpx.RequestError as e:
                raise ApiSubmitFallbackError(f"Network error: {e}") from e

        if resp.status_code == 200:
            result_data = resp.json()
            if result_data.get("success") is False:
                error = result_data.get("error", "Unknown Ashby error")
                logger.warning("Ashby submit rejected: %s", error)
                return ApiSubmitResult(status="failed", error=str(error))

            logger.info("Ashby API submit SUCCESS: %s/%s", url_info.board_token, url_info.job_id)
            return ApiSubmitResult(
                status="submitted",
                confirmation_text="Application submitted via Ashby API",
                raw_response=result_data,
            )

        if resp.status_code == 429:
            return ApiSubmitResult(status="rate_limited", error="Rate limited by Ashby")

        logger.warning("Ashby submit %d: %s", resp.status_code, resp.text[:300])
        raise ApiSubmitFallbackError(
            f"Ashby API returned {resp.status_code}: {resp.text[:200]}"
        )
