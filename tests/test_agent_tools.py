"""Tests for FoxhoundAgent tool handlers."""

import json
import pytest
from app.services.agent.registry import discover_tools, execute_tool


@pytest.fixture(autouse=True)
def _discover():
    discover_tools()


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_profile(db, sample_profile):
    result = await execute_tool(db, sample_profile.user_id, "get_profile", {})
    assert result["name"] == "Test User"
    assert "Python" in result["skills"]
    assert result["tier"] == "pro"


@pytest.mark.asyncio
async def test_get_profile_missing(db):
    result = await execute_tool(db, "nonexistent", "get_profile", {})
    assert "error" in result


# ---------------------------------------------------------------------------
# search_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_jobs(db, user_id, sample_jobs):
    result = await execute_tool(db, user_id, "search_jobs", {"query": "engineer"})
    assert len(result["jobs"]) >= 1


@pytest.mark.asyncio
async def test_search_jobs_no_results(db, user_id, sample_jobs):
    result = await execute_tool(db, user_id, "search_jobs", {"query": "underwater basket weaving"})
    assert result["jobs"] == []


# ---------------------------------------------------------------------------
# get_matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_matches(db, user_id, sample_matches):
    result = await execute_tool(db, user_id, "get_matches", {"min_score": 80})
    assert len(result["matches"]) == 2  # 92 and 85


@pytest.mark.asyncio
async def test_get_matches_high_threshold(db, user_id, sample_matches):
    result = await execute_tool(db, user_id, "get_matches", {"min_score": 95})
    assert result["matches"] == []


@pytest.mark.asyncio
async def test_get_matches_no_user(db):
    result = await execute_tool(db, "nobody", "get_matches", {})
    assert result["matches"] == []


# ---------------------------------------------------------------------------
# get_applications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_applications_empty(db, user_id):
    result = await execute_tool(db, user_id, "get_applications", {})
    assert result["applications"] == []


# ---------------------------------------------------------------------------
# update_preferences
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_preferences(db, sample_profile):
    result = await execute_tool(db, sample_profile.user_id, "update_preferences", {
        "remote_preference": "remote",
        "salary_floor": 200000,
    })
    assert len(result["changes"]) == 2
    assert any("remote" in c for c in result["changes"])
    assert any("200,000" in c for c in result["changes"])


@pytest.mark.asyncio
async def test_update_preferences_empty(db, sample_profile):
    result = await execute_tool(db, sample_profile.user_id, "update_preferences", {})
    assert "No changes" in result["message"]


@pytest.mark.asyncio
async def test_update_preferences_no_profile(db):
    result = await execute_tool(db, "nobody", "update_preferences", {"remote_preference": "remote"})
    assert "error" in result


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool(db, user_id):
    result = await execute_tool(db, user_id, "nonexistent_tool", {})
    assert result["error"] == "unknown_tool"
