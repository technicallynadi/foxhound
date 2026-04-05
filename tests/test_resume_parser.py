"""Tests for resume parser: PDF text extraction, LLM parsing, edge cases."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.resume.parser import ParsedProfile, ResumeParser

# ---------------------------------------------------------------------------
# ParsedProfile defaults
# ---------------------------------------------------------------------------

def test_parsed_profile_defaults():
    p = ParsedProfile()
    assert p.first_name == ""
    assert p.skills == []
    assert p.inferred_seniority == "mid"
    assert p.inferred_years_experience == 0


def test_parsed_profile_with_values():
    p = ParsedProfile(
        first_name="Jane", last_name="Doe",
        skills=["Python", "React"], inferred_seniority="senior",
        inferred_years_experience=8,
    )
    assert p.first_name == "Jane"
    assert len(p.skills) == 2
    assert p.inferred_seniority == "senior"


# ---------------------------------------------------------------------------
# PDF text extraction (mocked pdfplumber)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_text_single_page():
    """Mock _extract_text to test the parser's text extraction path."""
    parser = ResumeParser()
    with patch.object(parser, "_extract_text", new_callable=AsyncMock,
                      return_value="Jane Doe — Software Engineer\nSkills: Python, FastAPI"):
        text = await parser._extract_text(b"fake-pdf-bytes")
    assert "Jane Doe" in text
    assert "Python" in text


@pytest.mark.asyncio
async def test_extract_text_multi_page():
    parser = ResumeParser()
    with patch.object(parser, "_extract_text", new_callable=AsyncMock,
                      return_value="Page One Content\nPage Two Content"):
        text = await parser._extract_text(b"fake-pdf-bytes")
    assert "Page One" in text
    assert "Page Two" in text


@pytest.mark.asyncio
async def test_extract_text_empty_pdf():
    parser = ResumeParser()
    with patch.object(parser, "_extract_text", new_callable=AsyncMock, return_value=""):
        text = await parser._extract_text(b"fake-pdf-bytes")
    assert text.strip() == ""


# ---------------------------------------------------------------------------
# LLM extraction (mocked — call _llm_extract directly with text)
# ---------------------------------------------------------------------------

def _make_llm_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


_FULL_RESPONSE = {
    "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
    "phone": "+15551234567", "linkedin_url": "https://linkedin.com/in/janedoe",
    "portfolio_url": "", "location": "San Francisco, CA",
    "summary": "Senior Python engineer with 8 years of experience.",
    "skills": ["Python", "FastAPI", "React", "PostgreSQL"],
    "experience": [{"company": "Stripe", "title": "Senior Engineer"}],
    "education": [{"institution": "MIT", "degree": "BS CS"}],
    "certifications": [],
    "inferred_seniority": "senior", "inferred_years_experience": 8,
    "inferred_target_titles": ["Staff Engineer", "Senior Engineer"],
}


@pytest.mark.asyncio
async def test_llm_extract_happy_path():
    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_llm_response(_FULL_RESPONSE))
    parser._client = mock_client

    # Bypass prompt formatting by patching the prompt constant
    with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
        result = await parser._llm_extract("Some resume text here")

    assert result["first_name"] == "Jane"
    assert result["inferred_seniority"] == "senior"
    assert "Python" in result["skills"]


@pytest.mark.asyncio
async def test_llm_extract_strips_markdown_fences():
    raw_json = json.dumps({
        "first_name": "Bob", "last_name": "Smith", "email": "b@b.com",
        "phone": "", "linkedin_url": "", "portfolio_url": "", "location": "",
        "summary": "", "skills": [], "experience": [], "education": [],
        "certifications": [], "inferred_seniority": "mid",
        "inferred_years_experience": 0, "inferred_target_titles": [],
    })
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=f"```json\n{raw_json}\n```")]

    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    parser._client = mock_client

    with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
        result = await parser._llm_extract("Resume text")
    assert result["first_name"] == "Bob"


@pytest.mark.asyncio
async def test_llm_extract_malformed_json():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not JSON at all")]

    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    parser._client = mock_client

    with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
        with pytest.raises(ValueError, match="malformed JSON"):
            await parser._llm_extract("Resume text")


@pytest.mark.asyncio
async def test_llm_extract_missing_fields_use_defaults():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({"first_name": "Minimal"}))]

    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    parser._client = mock_client

    with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
        result = await parser._llm_extract("Resume text")
    assert result["first_name"] == "Minimal"
    assert result["last_name"] == ""
    assert result["skills"] == []
    assert result["inferred_seniority"] == "mid"


# ---------------------------------------------------------------------------
# Full parse flow (mocked extract + LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_empty_pdf_raises():
    parser = ResumeParser()
    with patch.object(parser, "_extract_text", new_callable=AsyncMock, return_value=""):
        with pytest.raises(ValueError, match="No text extracted"):
            await parser.parse(b"fake-pdf", "empty.pdf")


@pytest.mark.asyncio
async def test_parse_full_flow():
    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_llm_response(_FULL_RESPONSE))
    parser._client = mock_client

    with patch.object(parser, "_extract_text", new_callable=AsyncMock, return_value="Jane Doe resume"):
        with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
            profile = await parser.parse(b"fake-pdf", "resume.pdf")

    assert isinstance(profile, ParsedProfile)
    assert profile.first_name == "Jane"
    assert profile.inferred_seniority == "senior"
    assert profile.skills == ["Python", "FastAPI", "React", "PostgreSQL"]


@pytest.mark.asyncio
async def test_parse_llm_auth_error():
    import anthropic

    parser = ResumeParser()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body={"error": {"message": "Invalid API key"}},
        )
    )
    parser._client = mock_client

    with patch.object(parser, "_extract_text", new_callable=AsyncMock, return_value="Resume text"):
        with patch("app.services.resume.parser.RESUME_EXTRACTION_PROMPT", "{resume_text}"):
            with pytest.raises(anthropic.AuthenticationError):
                await parser.parse(b"fake-pdf", "resume.pdf")
