"""Resume parser: PDF -> text -> LLM structured extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from uuid import uuid4

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedProfile:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    portfolio_url: str = ""
    location: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    inferred_seniority: str = "mid"
    inferred_years_experience: int = 0
    inferred_target_titles: list[str] = field(default_factory=list)


RESUME_EXTRACTION_PROMPT = """You are a resume parser. Extract the following fields from this resume text.
Return JSON only, no commentary.

Required fields:
- first_name, last_name, email, phone, linkedin_url, portfolio_url, location
- summary (2-3 sentence professional summary)
- skills (list of technical and soft skills)
- experience (list of {company, title, start_date, end_date, description, highlights[]})
- education (list of {institution, degree, field, year})
- certifications (list of strings)
- inferred_seniority: "intern"|"junior"|"mid"|"senior"|"staff"|"principal"
- inferred_years_experience: integer
- inferred_target_titles: list of 3-5 job titles this person would likely target

Resume text:"""


class ResumeParser:
    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def parse(self, pdf_bytes: bytes, filename: str) -> ParsedProfile:
        text = await self._extract_text(pdf_bytes)
        if not text.strip():
            raise ValueError(f"No text extracted from {filename}")
        structured = await self._llm_extract(text)
        return ParsedProfile(**structured)

    async def _extract_text(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF using pdfplumber (MIT license)."""
        import io
        import pdfplumber

        pages = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)

    async def _llm_extract(self, text: str) -> dict:
        """Single Anthropic API call with structured output."""
        client = self._get_client()
        prompt = RESUME_EXTRACTION_PROMPT + "\n\n" + text[:8000]

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError:
            logger.error("Anthropic API authentication failed")
            raise
        except anthropic.RateLimitError:
            logger.error("Anthropic API rate limited")
            raise

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON: %s", raw[:200])
            raise ValueError("LLM returned malformed JSON for resume extraction")

        # Normalize fields to match ParsedProfile
        return {
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "linkedin_url": data.get("linkedin_url", ""),
            "portfolio_url": data.get("portfolio_url", ""),
            "location": data.get("location", ""),
            "summary": data.get("summary", ""),
            "skills": data.get("skills", []),
            "experience": data.get("experience", []),
            "education": data.get("education", []),
            "certifications": data.get("certifications", []),
            "inferred_seniority": data.get("inferred_seniority", "mid"),
            "inferred_years_experience": data.get("inferred_years_experience", 0),
            "inferred_target_titles": data.get("inferred_target_titles", []),
        }
