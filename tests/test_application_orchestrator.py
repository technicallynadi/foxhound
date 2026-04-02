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
    with pytest.raises(ValueError, match="(Browse tier cannot apply|can.t apply)"):
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
# CDP filler result mapping (tests the new Phase 2 approach)
# ---------------------------------------------------------------------------

def test_playwright_filler_field_result_types():
    """FieldFillResult captures per-field status."""
    from app.services.apply.playwright_filler import FieldFillResult
    r = FieldFillResult(label="Email", status="filled", value_used="a@b.com")
    assert r.status == "filled"
    assert r.value_used == "a@b.com"

def test_playwright_filler_fill_result():
    """FillResult captures overall status + per-field results."""
    from app.services.apply.playwright_filler import FillResult, FieldFillResult
    result = FillResult(
        status="submitted",
        fields=[
            FieldFillResult(label="Name", status="filled", value_used="Jane"),
            FieldFillResult(label="Resume", status="filled", value_used="resume.pdf"),
        ],
        fields_filled_count=2,
        confirmation_text="Thank you for applying",
        duration_ms=5000,
    )
    assert result.status == "submitted"
    assert len(result.fields) == 2
    assert result.fields_filled_count == 2

def test_playwright_filler_profile_data():
    """_build_profile_data extracts flat dict from profile."""
    from app.services.apply.playwright_filler import _build_profile_data
    profile = type("P", (), {
        "first_name": "Jane", "last_name": "Doe",
        "email": "j@j.com", "phone": "+1234",
        "linkedin_url": "https://li.com/jane",
        "portfolio_url": "https://jane.dev",
        "location": "SF",
        "experience_json": '[]', "years_experience": 5,
        "visa_status": "citizen",
    })()
    data = _build_profile_data(profile)
    assert data["full_name"] == "Jane Doe"
    assert data["email"] == "j@j.com"
    assert data["visa_status"] == "citizen"

def test_playwright_filler_resolve_value():
    """_resolve_field_value picks custom answers over profile data."""
    from app.services.apply.playwright_filler import _resolve_field_value
    from app.services.apply.form_scanner import FormField
    field = FormField(label="Email", field_type="email", required=True)
    # Custom answer takes priority
    val = _resolve_field_value(field, {"email": "profile@x.com"}, {"Email": "custom@x.com"})
    assert val == "custom@x.com"
    # Falls back to profile
    val2 = _resolve_field_value(field, {"email": "profile@x.com"}, {})
    assert val2 == "profile@x.com"

def test_fuzzy_match_option():
    """_fuzzy_match_option handles case-insensitive matching."""
    from app.services.apply.playwright_filler import _fuzzy_match_option
    assert _fuzzy_match_option("United States", ["Canada", "United States of America"]) == "United States of America"
    assert _fuzzy_match_option("decline", ["Yes", "No", "Decline to self identify"]) == "Decline to self identify"
    assert _fuzzy_match_option("xyz", ["A", "B"]) is None


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
