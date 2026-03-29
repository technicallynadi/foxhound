"""Tests for application orchestrator: two-phase apply flow, error states."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.apply.orchestrator import ApplicationOrchestrator


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_no_profile(db):
    orch = ApplicationOrchestrator()
    with pytest.raises(ValueError, match="No profile found"):
        await orch.apply(db, user_id="nonexistent", job_id="any")


@pytest.mark.asyncio
async def test_apply_free_tier_blocked(db, sample_profile, sample_jobs):
    from sqlalchemy import select
    from app.db.models.user_profile import UserProfile

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == sample_profile.user_id))
    profile = result.scalar_one()
    profile.tier = "free"
    await db.commit()

    orch = ApplicationOrchestrator()
    with pytest.raises(ValueError, match="Browse tier cannot apply"):
        await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)


@pytest.mark.asyncio
async def test_apply_monthly_limit(db, sample_profile, sample_jobs):
    from sqlalchemy import select
    from app.db.models.user_profile import UserProfile

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == sample_profile.user_id))
    profile = result.scalar_one()
    profile.applications_this_month = 50
    await db.commit()

    orch = ApplicationOrchestrator()
    with pytest.raises(ValueError, match="Monthly application limit"):
        await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)


@pytest.mark.asyncio
async def test_apply_no_job(db, sample_profile):
    orch = ApplicationOrchestrator()
    with pytest.raises(ValueError, match="Job not found"):
        await orch.apply(db, user_id=sample_profile.user_id, job_id="nonexistent")


# ---------------------------------------------------------------------------
# Auto-fill
# ---------------------------------------------------------------------------

def test_auto_fill_name():
    orch = ApplicationOrchestrator()
    profile = type("P", (), {
        "first_name": "Jane", "last_name": "Doe", "email": "j@j.com",
        "phone": "+1234", "linkedin_url": "https://li.com/jane",
        "portfolio_url": "https://jane.dev", "location": "SF",
    })()
    assert orch._auto_fill(profile, "full name") == "Jane Doe"
    assert orch._auto_fill(profile, "email address") == "j@j.com"
    assert orch._auto_fill(profile, "phone number") == "+1234"
    assert orch._auto_fill(profile, "linkedin profile") == "https://li.com/jane"
    assert orch._auto_fill(profile, "website") == "https://jane.dev"
    assert orch._auto_fill(profile, "city") == "SF"
    assert orch._auto_fill(profile, "favorite color") is None


# ---------------------------------------------------------------------------
# TinyFish result parsing
# ---------------------------------------------------------------------------

def test_parse_tinyfish_submitted():
    orch = ApplicationOrchestrator()
    result = orch._parse_tinyfish_result('{"status": "submitted", "fields_filled": ["name", "email"]}')
    assert result["status"] == "submitted"

def test_parse_tinyfish_captcha():
    orch = ApplicationOrchestrator()
    result = orch._parse_tinyfish_result("Could not proceed — CAPTCHA detected")
    assert result["status"] == "captcha_detected"

def test_parse_tinyfish_success_keyword():
    orch = ApplicationOrchestrator()
    result = orch._parse_tinyfish_result("Application successfully submitted!")
    assert result["status"] == "submitted"

def test_parse_tinyfish_unknown():
    orch = ApplicationOrchestrator()
    result = orch._parse_tinyfish_result("Something unexpected happened")
    assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# TinyFish execution (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_tinyfish_error():
    orch = ApplicationOrchestrator()
    with patch("app.services.ingest.tinyfish_adapter._get_client") as mock_get:
        mock_client = MagicMock()
        mock_client.agent.run = AsyncMock(side_effect=RuntimeError("connection failed"))
        mock_get.return_value = mock_client
        result = await orch._execute_tinyfish("prompt", "https://example.com")
    assert result["status"] == "failed"
    assert "connection failed" in result["error"]


@pytest.mark.asyncio
async def test_execute_tinyfish_rate_limited():
    orch = ApplicationOrchestrator()
    with patch("app.services.ingest.tinyfish_adapter._get_client") as mock_get:
        mock_client = MagicMock()
        mock_client.agent.run = AsyncMock(side_effect=RuntimeError("RATE_LIMIT_EXCEEDED"))
        mock_get.return_value = mock_client
        result = await orch._execute_tinyfish("prompt", "https://example.com")
    assert result["status"] == "rate_limited"


# ---------------------------------------------------------------------------
# Full apply flow (Phase 1 scan failure)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_scan_login_required(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import ScanResult

    orch = ApplicationOrchestrator()

    with patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = ScanResult(status="login_required")
        app = await orch.apply(
            db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id,
        )

    assert app.status == "needs_manual"
    assert app.error_type == "login_required"


@pytest.mark.asyncio
async def test_apply_scan_error(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import ScanResult

    orch = ApplicationOrchestrator()

    with patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = ScanResult(status="error", error="Timed out")
        app = await orch.apply(
            db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id,
        )

    assert app.status == "failed"
    assert app.error_type == "error"
