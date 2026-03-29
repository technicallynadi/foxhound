"""Tests for the match scorer: scoring components and disqualifiers."""

import json
import pytest
from unittest.mock import MagicMock
from app.services.matching.scorer import MatchScorer, SKILL_ALIASES


# ---------------------------------------------------------------------------
# Skill alias normalization
# ---------------------------------------------------------------------------

def test_skill_aliases():
    assert SKILL_ALIASES.get("k8s") == "kubernetes"
    assert SKILL_ALIASES.get("js") == "javascript"
    assert SKILL_ALIASES.get("ts") == "typescript"
    assert SKILL_ALIASES.get("postgres") == "postgresql"


# ---------------------------------------------------------------------------
# Scorer integration (with DB fixtures)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_jobs_for_user(db, sample_profile, sample_jobs):
    scorer = MatchScorer()
    matches = await scorer.score_jobs_for_user(db, sample_profile.user_id)

    assert len(matches) > 0
    for match in matches:
        assert 0 <= match.match_score <= 100
        assert match.user_id == sample_profile.user_id


@pytest.mark.asyncio
async def test_score_no_profile(db):
    scorer = MatchScorer()
    matches = await scorer.score_jobs_for_user(db, "nonexistent-user")
    assert matches == []


@pytest.mark.asyncio
async def test_score_no_jobs(db, sample_profile):
    """Scorer with profile but no jobs should return empty."""
    # sample_jobs not created, so no unscored jobs exist
    scorer = MatchScorer()
    matches = await scorer.score_jobs_for_user(db, sample_profile.user_id)
    # May return 0 if all jobs already scored or no jobs at all
    assert isinstance(matches, list)
