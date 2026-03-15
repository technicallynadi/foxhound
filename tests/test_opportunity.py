"""Tests for the opportunity state machine."""

import pytest

from foxhound.core.models import (
    OpportunityState,
    TrustLevel,
    WorkItemKind,
    WorkItemState,
)
from foxhound.scout.opportunity import (
    OPPORTUNITY_TRANSITIONS,
    OpportunityManager,
)
from foxhound.storage.database import Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def mgr(db: Database) -> OpportunityManager:
    return OpportunityManager(db)


class TestOpportunityCreation:
    def test_create_opportunity(self, mgr: OpportunityManager) -> None:
        item = mgr.create(
            title="Test Project",
            source_type="github_trending",
            source_url="https://github.com/test/project",
        )
        assert item.opportunity_id.startswith("opp_")
        assert item.state == OpportunityState.OBSERVED
        assert item.trust_level == TrustLevel.UNTRUSTED

    def test_create_with_evidence(self, mgr: OpportunityManager) -> None:
        item = mgr.create(
            title="Reddit find",
            source_type="reddit",
            evidence={"subreddit": "SideProject", "upvotes": 150},
            tags=["python", "cli"],
        )
        assert item.evidence["subreddit"] == "SideProject"
        assert "python" in item.tags

    def test_create_generates_fingerprint(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="FP test", source_type="github_trending")
        assert len(item.source_fingerprint) > 0


class TestStateTransitions:
    def test_full_lifecycle(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Lifecycle", source_type="test")
        assert item.state == OpportunityState.OBSERVED

        item = mgr.sanitize(item.opportunity_id)
        assert item.state == OpportunityState.SANITIZED

        item = mgr.evaluate(item.opportunity_id, credibility=0.8, novelty=0.6)
        assert item.state == OpportunityState.EVALUATED
        assert item.credibility_score == 0.8

        item = mgr.suggest(item.opportunity_id)
        assert item.state == OpportunityState.SUGGESTED

        item = mgr.approve(item.opportunity_id)
        assert item.state == OpportunityState.APPROVED

    def test_rejection(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Reject me", source_type="test")
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(item.opportunity_id)
        mgr.suggest(item.opportunity_id)
        item = mgr.reject(item.opportunity_id)
        assert item.state == OpportunityState.REJECTED

    def test_invalid_transition_raises(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Skip ahead", source_type="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            mgr.approve(item.opportunity_id)

    def test_observed_to_evaluated_invalid(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Bad transition", source_type="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            mgr.evaluate(item.opportunity_id)

    def test_rejected_is_terminal(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Terminal", source_type="test")
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(item.opportunity_id)
        mgr.suggest(item.opportunity_id)
        mgr.reject(item.opportunity_id)

        with pytest.raises(ValueError, match="Invalid transition"):
            mgr.approve(item.opportunity_id)

    def test_not_found_raises(self, mgr: OpportunityManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            mgr.advance("nonexistent", OpportunityState.SANITIZED)


class TestConversion:
    def test_convert_to_work_item(self, mgr: OpportunityManager) -> None:
        item = mgr.create(
            title="Convert me",
            source_type="github_trending",
            source_url="https://github.com/test/repo",
            evidence={"stars": 500},
        )
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(
            item.opportunity_id,
            credibility=0.8, actionability=0.7,
        )
        mgr.suggest(item.opportunity_id)
        mgr.approve(item.opportunity_id)

        work_item = mgr.convert_to_work_item(item.opportunity_id, "repo_001")
        assert work_item.work_item_id.startswith("wi_")
        assert work_item.kind == WorkItemKind.OPPORTUNITY
        assert work_item.state == WorkItemState.DISCOVERED
        assert work_item.trust_level == TrustLevel.SEMI_TRUSTED
        assert work_item.source_type == "scout:github_trending"
        assert work_item.evidence["opportunity_id"] == item.opportunity_id
        assert work_item.confidence == 0.7

    def test_convert_not_approved_raises(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Not approved", source_type="test")
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(item.opportunity_id)
        mgr.suggest(item.opportunity_id)

        with pytest.raises(ValueError, match="approved"):
            mgr.convert_to_work_item(item.opportunity_id, "repo_001")

    def test_conversion_marks_converted(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="To convert", source_type="test")
        mgr.sanitize(item.opportunity_id)
        mgr.evaluate(item.opportunity_id)
        mgr.suggest(item.opportunity_id)
        mgr.approve(item.opportunity_id)
        mgr.convert_to_work_item(item.opportunity_id, "repo_001")

        updated = mgr.get(item.opportunity_id)
        assert updated is not None
        assert updated.state == OpportunityState.CONVERTED_TO_PROJECT


class TestDedup:
    def test_find_by_fingerprint(self, mgr: OpportunityManager) -> None:
        item = mgr.create(title="Unique", source_type="test")
        found = mgr.find_by_fingerprint(item.source_fingerprint)
        assert found is not None
        assert found.opportunity_id == item.opportunity_id

    def test_find_by_fingerprint_not_found(self, mgr: OpportunityManager) -> None:
        found = mgr.find_by_fingerprint("nonexistent")
        assert found is None


class TestListByState:
    def test_list_by_state(self, mgr: OpportunityManager) -> None:
        mgr.create(title="A", source_type="test")
        mgr.create(title="B", source_type="test")

        observed = mgr.list_by_state(OpportunityState.OBSERVED)
        assert len(observed) == 2

    def test_list_empty_state(self, mgr: OpportunityManager) -> None:
        assert mgr.list_by_state(OpportunityState.APPROVED) == []


class TestTransitionTable:
    def test_all_states_covered(self) -> None:
        actionable = {
            OpportunityState.OBSERVED,
            OpportunityState.SANITIZED,
            OpportunityState.EVALUATED,
            OpportunityState.SUGGESTED,
            OpportunityState.APPROVED,
        }
        for state in actionable:
            assert state in OPPORTUNITY_TRANSITIONS

    def test_terminal_states_not_in_transitions(self) -> None:
        assert OpportunityState.REJECTED not in OPPORTUNITY_TRANSITIONS
        assert OpportunityState.CONVERTED_TO_PROJECT not in OPPORTUNITY_TRANSITIONS
