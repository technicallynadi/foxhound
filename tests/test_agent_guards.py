"""Tests for FoxhoundAgent guards and budget."""

import json

import pytest

from app.services.agent.budget import RequestBudget
from app.services.agent.guards import ToolBlocked, ToolGuard
from app.services.agent.utils.profile_filler import check_answer_bank, extract_profile_value, update_answer_bank
from app.services.agent.utils.question_classifier import classify_question
from app.services.agent.utils.url_validator import validate_apply_url

# ---------------------------------------------------------------------------
# ToolGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_blocks_free_tier(db, sample_profile):
    from sqlalchemy import select

    from app.db.models.user_profile import UserProfile

    # Set to free tier
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == sample_profile.user_id))
    profile = result.scalar_one()
    profile.tier = "free"
    await db.commit()

    guard = ToolGuard()
    with pytest.raises(ToolBlocked) as exc:
        await guard.check(db, sample_profile.user_id, "apply_to_job", {})
    assert exc.value.code == "browse_tier"


@pytest.mark.asyncio
async def test_guard_allows_pro_tier(db, sample_profile):
    guard = ToolGuard()
    # Should not raise
    await guard.check(db, sample_profile.user_id, "apply_to_job", {})


@pytest.mark.asyncio
async def test_guard_blocks_monthly_limit(db, sample_profile):
    from sqlalchemy import select

    from app.db.models.user_profile import UserProfile

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == sample_profile.user_id))
    profile = result.scalar_one()
    profile.applications_this_month = 50  # At limit
    await db.commit()

    guard = ToolGuard()
    with pytest.raises(ToolBlocked) as exc:
        await guard.check(db, sample_profile.user_id, "apply_to_job", {})
    assert exc.value.code == "monthly_limit"


@pytest.mark.asyncio
async def test_guard_blocks_blacklisted_company(db, sample_profile, sample_jobs):
    from sqlalchemy import select

    from app.db.models.user_profile import UserProfile

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == sample_profile.user_id))
    profile = result.scalar_one()
    profile.blacklisted_companies_json = json.dumps(["Anthropic"])
    await db.commit()

    guard = ToolGuard()
    with pytest.raises(ToolBlocked) as exc:
        await guard.check(
            db,
            sample_profile.user_id,
            "apply_to_job",
            {
                "job_id": sample_jobs[0].id,
            },
        )
    assert exc.value.code == "blacklisted_company"


@pytest.mark.asyncio
async def test_guard_skips_read_tools(db, user_id):
    """Read-only tools should not be guarded."""
    guard = ToolGuard()
    # Should not raise
    await guard.check(db, user_id, "search_jobs", {"query": "test"})
    await guard.check(db, user_id, "get_profile", {})
    await guard.check(db, user_id, "get_applications", {})


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_tracks():
    b = RequestBudget()
    assert b.can_continue()
    b.record_api_call(1000, 500)
    assert b.total_tokens == 1500
    assert b.iterations == 1
    assert b.estimated_cost > 0


def test_budget_exhausts_iterations():
    b = RequestBudget(max_iterations=2)
    b.record_api_call(100, 50)
    b.record_api_call(100, 50)
    assert not b.can_continue()


def test_budget_exhausts_tokens():
    b = RequestBudget(max_tokens=500)
    b.record_api_call(300, 300)
    assert not b.can_continue()


def test_budget_summary():
    b = RequestBudget()
    b.record_api_call(1000, 500)
    b.record_tool_call("search_jobs", 150)
    s = b.summary()
    assert s["iterations"] == 1
    assert s["total_tokens"] == 1500
    assert s["tool_calls"] == 1


# ---------------------------------------------------------------------------
# URL Validator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://boards.greenhouse.io/anthropic/jobs/123", True),
        ("https://jobs.lever.co/stripe/abc", True),
        ("https://jobs.ashbyhq.com/openai/xyz", True),
        ("https://abc.myworkdayjobs.com/en-US/jobs", True),
        ("http://boards.greenhouse.io/test", False),
        ("https://evil.com/phishing", False),
        ("https://169.254.169.254/metadata", False),
        ("https://localhost/admin", False),
        ("", False),
    ],
)
def test_url_validator(url, expected):
    assert validate_apply_url(url) == expected


def test_url_validator_blocks_dns_rebinding(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.utils.url_validator._resolve_host_ips",
        lambda host: {"10.1.2.3"},
    )
    assert validate_apply_url("https://jobs.lever.co/stripe/abc123") is False


def test_url_validator_blocks_ipv6_rebinding(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.utils.url_validator._resolve_host_ips",
        lambda host: {"::1"},
    )
    assert validate_apply_url("https://boards.greenhouse.io/acme/jobs/123") is False


# ---------------------------------------------------------------------------
# Question Classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("First Name", "auto"),
        ("Email", "auto"),
        ("Why do you want to work here?", "draft_and_approve"),
        ("Salary expectations", "ask_directly"),
        ("Favorite color", "unknown"),
    ],
)
def test_question_classifier(label, expected):
    assert classify_question(label) == expected


# ---------------------------------------------------------------------------
# Profile Filler + Answer Bank
# ---------------------------------------------------------------------------


def test_profile_filler():
    profile = type(
        "P",
        (),
        {
            "first_name": "Test",
            "last_name": "User",
            "email": "t@t.com",
            "phone": "+1234",
            "linkedin_url": "https://li.com/t",
            "portfolio_url": "https://gh.com/t",
            "location": "SF",
            "visa_status": "US Citizen",
            "years_experience": 5,
            "education_json": json.dumps([{"degree": "BS", "school": "MIT"}]),
        },
    )()
    assert extract_profile_value(profile, "Email") == "t@t.com"
    assert extract_profile_value(profile, "Full Name") == "Test User"
    assert extract_profile_value(profile, "Favorite color") is None


def test_answer_bank():
    profile = type("P", (), {"answer_bank_json": "{}"})()
    update_answer_bank(profile, "Salary expectations", "180-210k")
    assert check_answer_bank(profile, "What is your salary expectation?") == "180-210k"
    assert check_answer_bank(profile, "Favorite color") is None
