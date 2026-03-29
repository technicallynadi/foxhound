"""Shared test fixtures for Foxhound tests.

Uses SQLite in-memory for fast, isolated tests.
Mocks all external services (TinyFish, Anthropic, Supabase Storage).
"""

import asyncio
import json
import os

import pytest

# Force SQLite for tests — set BOTH keys before any app imports.
# FOXHOUND_DATABASE_URL is what pydantic-settings reads (env_prefix="FOXHOUND_").
# DATABASE_URL is what the default fallback reads via os.environ.get().
# Also set DOTENV_OVERRIDE to prevent load_dotenv from clobbering these.
_TEST_DB = "sqlite+aiosqlite:///file:test?mode=memory&cache=shared&uri=true"
os.environ["DATABASE_URL"] = _TEST_DB
os.environ["FOXHOUND_DATABASE_URL"] = _TEST_DB

# Prevent load_dotenv from overriding test DB URL with production Postgres URL.
# Patch dotenv BEFORE any app module imports config.py.
import unittest.mock as _mock
_mock.patch("dotenv.load_dotenv", lambda **kw: None).start()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def _init_db(event_loop):
    from app.db.session import init_db
    event_loop.run_until_complete(init_db())

    # Discover agent tools so ToolGuard can resolve tool specs
    from app.services.agent.registry import discover_tools
    discover_tools()

    # Override auth dependency so API tests don't need real tokens.
    # Individual tests can set _test_user_id to control which user_id is returned.
    from app.main import app as fastapi_app
    from app.services.auth_service import get_current_user

    async def _fake_current_user():
        return {"user_id": _fake_current_user._test_user_id, "email": "test@foxhound.com", "role": "authenticated"}
    _fake_current_user._test_user_id = ""

    fastapi_app.dependency_overrides[get_current_user] = _fake_current_user


@pytest.fixture
async def db():
    """Provide a fresh async DB session for each test."""
    from app.db.session import async_session
    async with async_session() as session:
        yield session


@pytest.fixture
def user_id():
    from uuid import uuid4
    uid = str(uuid4())
    # Set on the auth mock so API tests use this user_id
    from app.services.auth_service import get_current_user
    from app.main import app as fastapi_app
    override_fn = fastapi_app.dependency_overrides.get(get_current_user)
    if override_fn:
        override_fn._test_user_id = uid
    yield uid
    if override_fn:
        override_fn._test_user_id = ""


@pytest.fixture
async def sample_profile(db, user_id):
    """Create a sample user profile."""
    from uuid import uuid4
    from app.db.models.user_profile import UserProfile

    profile = UserProfile(
        id=str(uuid4()),
        user_id=user_id,
        email="test@foxhound.com",
        first_name="Test",
        last_name="User",
        phone="+14155551234",
        linkedin_url="https://linkedin.com/in/test",
        location="San Francisco, CA",
        summary="Senior engineer with 5 years in Python and React.",
        skills_json=json.dumps(["Python", "React", "FastAPI", "PostgreSQL"]),
        experience_json=json.dumps([
            {"title": "Senior Engineer", "company": "Stripe", "years": "2022-2025"},
        ]),
        education_json=json.dumps([{"degree": "BS CS", "school": "UC Berkeley"}]),
        target_titles_json=json.dumps(["Senior Engineer", "Staff Engineer"]),
        years_experience=5,
        tier="pro",
        monthly_apply_limit=50,
        salary_floor=180000,
    )
    db.add(profile)
    await db.commit()
    return profile


@pytest.fixture
async def sample_jobs(db):
    """Create sample job listings."""
    from uuid import uuid4
    from app.db.models.job_listing import JobListing

    jobs = []
    for title, company, sal_min, sal_max in [
        ("Senior Engineer", "Anthropic", 200000, 350000),
        ("ML Engineer", "OpenAI", 250000, 400000),
        ("Backend Engineer", "Stripe", 190000, 300000),
    ]:
        job = JobListing(
            id=str(uuid4()), title=title, company=company,
            description=f"{title} role at {company}",
            apply_url=f"https://{company.lower()}.com/jobs",
            source="test", source_url=f"https://{company.lower()}.com",
            location="San Francisco, CA", salary_min=sal_min, salary_max=sal_max,
            ats_type="greenhouse",
        )
        jobs.append(job)
        db.add(job)
    await db.commit()
    return jobs


@pytest.fixture
async def sample_matches(db, user_id, sample_jobs):
    """Create sample job matches."""
    from uuid import uuid4
    from app.db.models.job_match import JobMatch

    matches = []
    for job, score in zip(sample_jobs, [92, 85, 78]):
        match = JobMatch(
            id=str(uuid4()), user_id=user_id, job_id=job.id,
            match_score=score, title_score=0.3, skills_score=0.25,
            experience_score=0.15, location_score=0.15,
            salary_score=0.10, recency_score=0.05,
        )
        matches.append(match)
        db.add(match)
    await db.commit()
    return matches
