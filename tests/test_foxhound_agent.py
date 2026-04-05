"""Tests for the unified FoxhoundAgent: tools, guards, budget, agent loop, user isolation."""

import json
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///file:test_fha?mode=memory&cache=shared&uri=true")

from app.services.agent.budget import RequestBudget
from app.services.agent.utils.question_classifier import classify_question
from app.services.agent.utils.url_validator import validate_apply_url

# ---------------------------------------------------------------------------
# Question classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("First Name", "auto"),
    ("Email", "auto"),
    ("Phone number", "auto"),
    ("LinkedIn URL", "auto"),
    ("Years of experience", "auto"),
    ("Work authorization", "auto"),
])
def test_classify_auto(label, expected):
    assert classify_question(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Why do you want to work here?", "draft_and_approve"),
    ("Describe your experience", "draft_and_approve"),
    ("Cover letter", "draft_and_approve"),
])
def test_classify_draft(label, expected):
    assert classify_question(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Salary expectations", "ask_directly"),
    ("Start date", "ask_directly"),
    ("Criminal background", "ask_directly"),
    ("Gender", "ask_directly"),
])
def test_classify_ask(label, expected):
    assert classify_question(label) == expected


def test_classify_unknown():
    assert classify_question("Favorite programming language") == "unknown"
    assert classify_question("How many monitors do you prefer?") == "unknown"


# ---------------------------------------------------------------------------
# URL validator
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/anthropic/jobs/123", True),
    ("https://jobs.lever.co/stripe/abc", True),
    ("https://jobs.ashbyhq.com/openai/xyz", True),
    ("https://abc.myworkdayjobs.com/en-US/jobs", True),
    ("http://boards.greenhouse.io/test", False),  # no HTTPS
    ("https://evil.com/phishing", False),
    ("https://169.254.169.254/metadata", False),  # private IP
    ("https://localhost/admin", False),
    ("", False),
])
def test_validate_apply_url(url, expected):
    assert validate_apply_url(url) == expected


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

def test_budget_tracks_usage():
    b = RequestBudget()
    assert b.can_continue()
    b.record_api_call(1000, 500)
    assert b.total_tokens == 1500
    assert b.estimated_cost > 0
    assert b.iterations == 1


def test_budget_exhausts_iterations():
    b = RequestBudget(max_iterations=2)
    b.record_api_call(100, 50)
    b.record_api_call(100, 50)
    assert not b.can_continue()


def test_budget_exhausts_tokens():
    b = RequestBudget(max_tokens=1000)
    b.record_api_call(600, 500)
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
# Profile filler
# ---------------------------------------------------------------------------

class FakeProfile:
    first_name = "Test"
    last_name = "User"
    email = "test@test.com"
    phone = "+1234"
    linkedin_url = "https://li.com/test"
    portfolio_url = "https://gh.com/test"
    location = "SF"
    visa_status = "US Citizen"
    years_experience = 5
    education_json = json.dumps([{"degree": "BS CS", "school": "MIT"}])
    answer_bank_json = "{}"


def test_profile_filler_basic():
    from app.services.agent.utils.profile_filler import extract_profile_value
    p = FakeProfile()
    assert extract_profile_value(p, "Email") == "test@test.com"
    assert extract_profile_value(p, "Full Name") == "Test User"
    assert extract_profile_value(p, "Phone") == "+1234"
    assert extract_profile_value(p, "Location") == "SF"


def test_profile_filler_education():
    from app.services.agent.utils.profile_filler import extract_profile_value
    p = FakeProfile()
    v = extract_profile_value(p, "Highest degree")
    assert "BS CS" in v
    assert "MIT" in v


def test_profile_filler_missing():
    from app.services.agent.utils.profile_filler import extract_profile_value
    p = FakeProfile()
    assert extract_profile_value(p, "Favorite color") is None


def test_profile_filler_null_field():
    from app.services.agent.utils.profile_filler import extract_profile_value
    p = FakeProfile()
    p.phone = None
    assert extract_profile_value(p, "Phone") is None


# ---------------------------------------------------------------------------
# Answer bank
# ---------------------------------------------------------------------------

def test_answer_bank_update():
    from app.services.agent.utils.profile_filler import check_answer_bank, update_answer_bank
    p = FakeProfile()
    update_answer_bank(p, "Salary expectations", "180-210k")
    assert "salary" in p.answer_bank_json
    assert check_answer_bank(p, "What is your salary expectation?") == "180-210k"


def test_answer_bank_no_match():
    from app.services.agent.utils.profile_filler import check_answer_bank
    p = FakeProfile()
    assert check_answer_bank(p, "Favorite color") is None
