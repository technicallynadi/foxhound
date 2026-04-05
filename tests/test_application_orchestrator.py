"""Tests for application orchestrator: two-phase apply flow, error states."""

from unittest.mock import AsyncMock, patch

import pytest

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


@pytest.mark.asyncio
async def test_apply_blocks_unsafe_apply_url(db, sample_profile, sample_jobs):
    sample_jobs[0].apply_url = "https://evil.com/phishing"
    await db.commit()

    orch = ApplicationOrchestrator()
    with pytest.raises(ValueError, match="Unsafe apply URL"):
        await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)


# ---------------------------------------------------------------------------
# Auto-fill
# ---------------------------------------------------------------------------


def test_auto_fill_name():
    orch = ApplicationOrchestrator()
    profile = type(
        "P",
        (),
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "j@j.com",
            "phone": "+1234",
            "linkedin_url": "https://li.com/jane",
            "portfolio_url": "https://jane.dev",
            "location": "SF",
        },
    )()
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
    from app.services.apply.playwright_filler import FieldFillResult, FillResult

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

    profile = type(
        "P",
        (),
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "j@j.com",
            "phone": "+1234",
            "linkedin_url": "https://li.com/jane",
            "portfolio_url": "https://jane.dev",
            "location": "SF",
            "experience_json": "[]",
            "years_experience": 5,
            "visa_status": "citizen",
        },
    )()
    data = _build_profile_data(profile)
    assert data["full_name"] == "Jane Doe"
    assert data["email"] == "j@j.com"
    assert data["visa_status"] == "citizen"


def test_playwright_filler_resolve_value():
    """_resolve_field_value picks custom answers over profile data."""
    from app.services.apply.form_scanner import FormField
    from app.services.apply.playwright_filler import _resolve_field_value

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
            db,
            user_id=sample_profile.user_id,
            job_id=sample_jobs[0].id,
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
            db,
            user_id=sample_profile.user_id,
            job_id=sample_jobs[0].id,
        )

    assert app.status == "failed"
    assert app.error_type == "error"


# CDP disconnect recovery


@pytest.mark.asyncio
async def test_apply_cdp_disconnect_returns_error(db, sample_profile, sample_jobs):
    import httpx

    from app.services.apply.form_scanner import FormField, ScanResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable", fields=[FormField(label="Email", field_type="email", required=True)]
        )
        mf.side_effect = httpx.ConnectError("CDP connection refused")
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "failed"


@pytest.mark.asyncio
async def test_apply_cdp_disconnect_mid_fill_returns_error(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable", fields=[FormField(label="Email", field_type="email", required=True)]
        )
        mf.side_effect = Exception("Target closed")
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "failed"


@pytest.mark.asyncio
async def test_apply_fill_status_error_sets_failed(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult
    from app.services.apply.playwright_filler import FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable", fields=[FormField(label="Email", field_type="email", required=True)]
        )
        mf.return_value = FillResult(status="error", error="CDP failed 429", duration_ms=500)
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "failed"


@pytest.mark.asyncio
async def test_apply_fill_status_captcha_sets_needs_manual(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult
    from app.services.apply.playwright_filler import FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable", fields=[FormField(label="Email", field_type="email", required=True)]
        )
        mf.return_value = FillResult(status="captcha", error="CAPTCHA detected", duration_ms=3000)
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "needs_manual"
    assert app.error_type == "captcha"


@pytest.mark.asyncio
async def test_apply_fill_submitted_sets_submitted(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult
    from app.services.apply.playwright_filler import FieldFillResult, FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
        patch("app.services.apply.notifications.send_application_receipt", new_callable=AsyncMock),
        patch("app.services.storage.supabase_storage.upload_file", new_callable=AsyncMock),
        patch("app.services.events.emit", new_callable=AsyncMock),
    ):
        ms.return_value = ScanResult(
            status="scannable", fields=[FormField(label="Email", field_type="email", required=True)]
        )
        mf.return_value = FillResult(
            status="submitted",
            fields=[FieldFillResult(label="Email", status="filled", value_used="t@e.com")],
            fields_filled_count=1,
            confirmation_text="Thank you",
            duration_ms=4000,
        )
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "submitted"


# Question review flow


@pytest.mark.asyncio
async def test_apply_waiting_user_input_when_sensitive_fields(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.notifications.send_conversation_question", new_callable=AsyncMock),
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable",
            fields=[
                FormField(label="Email", field_type="email", required=True),
                FormField(label="Expected salary", field_type="text", required=True),
            ],
        )
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "waiting_user_input"


@pytest.mark.asyncio
async def test_apply_question_records_created_for_sensitive_fields(db, sample_profile, sample_jobs):
    from sqlalchemy import select

    from app.db.models.application_question import ApplicationQuestion
    from app.services.apply.form_scanner import FormField, ScanResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.notifications.send_conversation_question", new_callable=AsyncMock),
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable",
            fields=[
                FormField(label="Email", field_type="email", required=True),
                FormField(label="Desired salary", field_type="text", required=True),
            ],
        )
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    from app.db.session import async_session

    async with async_session() as check_db:
        result = await check_db.execute(select(ApplicationQuestion).where(ApplicationQuestion.application_id == app.id))
        questions = result.scalars().all()
    assert len(questions) > 0
    assert all(q.status == "pending" for q in questions)


@pytest.mark.asyncio
async def test_apply_no_user_input_needed_proceeds_to_fill(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import FormField, ScanResult
    from app.services.apply.playwright_filler import FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.notifications.send_conversation_question", new_callable=AsyncMock) as mc,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable",
            fields=[
                FormField(label="Email", field_type="email", required=True),
                FormField(label="First name", field_type="text", required=True),
            ],
        )
        mf.return_value = FillResult(status="needs_manual", error="No submit", duration_ms=2000)
        await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    mc.assert_not_called()
    mf.assert_called_once()


# DB session resilience


@pytest.mark.asyncio
async def test_duplicate_application_rejected(db, sample_profile, sample_jobs):
    from app.services.apply.form_scanner import ScanResult
    from app.services.apply.playwright_filler import FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
        patch("app.services.apply.notifications.send_application_receipt", new_callable=AsyncMock),
        patch("app.services.storage.supabase_storage.upload_file", new_callable=AsyncMock),
        patch("app.services.events.emit", new_callable=AsyncMock),
    ):
        ms.return_value = ScanResult(status="scannable", fields=[])
        mf.return_value = FillResult(
            status="submitted", fields=[], fields_filled_count=0, confirmation_text="Thank you", duration_ms=1000
        )
        app1 = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
        assert app1.status == "submitted"
        with pytest.raises(ValueError, match="Already applied"):
            await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)


@pytest.mark.asyncio
async def test_apply_fill_needs_manual_preserves_fields_filled(db, sample_profile, sample_jobs):
    import json as _json

    from app.db.models.application import Application as AppModel
    from app.services.apply.form_scanner import FormField, ScanResult
    from app.services.apply.playwright_filler import FieldFillResult, FillResult

    orch = ApplicationOrchestrator()
    with (
        patch("app.services.apply.form_scanner.scan_form", new_callable=AsyncMock) as ms,
        patch("app.services.apply.agentql_filler.fill_from_profile", new_callable=AsyncMock) as mf,
        patch("app.services.apply.ats_url_parser.parse_ats_url", return_value=None),
    ):
        ms.return_value = ScanResult(
            status="scannable",
            fields=[
                FormField(label="Email", field_type="email", required=True),
                FormField(label="First name", field_type="text", required=True),
            ],
        )
        mf.return_value = FillResult(
            status="needs_manual",
            fields=[
                FieldFillResult(label="Email", status="filled", value_used="test@foxhound.com"),
                FieldFillResult(label="First name", status="filled", value_used="Test"),
            ],
            fields_filled_count=2,
            error="Submit button not found",
            duration_ms=2000,
        )
        app = await orch.apply(db, user_id=sample_profile.user_id, job_id=sample_jobs[0].id)
    assert app.status == "needs_manual"
    from app.db.session import async_session

    async with async_session() as check_db:
        stored = await check_db.get(AppModel, app.id)
        fields_filled = _json.loads(stored.fields_filled_json or "[]")
    assert "Email" in fields_filled
    assert "First name" in fields_filled
