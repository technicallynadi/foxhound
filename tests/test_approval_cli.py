"""Tests for CLI approval flow and work item state machine integration."""

import pytest

from foxhound.core.coordinator import WORK_ITEM_TRANSITIONS, Coordinator
from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventType,
    RiskLevel,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)
from foxhound.storage.database import Database, WorkItemStore


@pytest.fixture()
def db():
    """Create an in-memory database."""
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture()
def store(db):
    """Create a WorkItemStore."""
    return WorkItemStore(db)


@pytest.fixture()
def coordinator(db):
    """Create a coordinator."""
    return Coordinator(db)


def _make_item(
    work_item_id: str = "wi_001",
    repo_id: str = "repo_1",
    state: WorkItemState = WorkItemState.DISCOVERED,
    title: str = "Test item",
    source_type: str = "todo_todo",
    risk: RiskLevel = RiskLevel.LOW,
    confidence: float = 0.7,
    source_fingerprint: str | None = None,
) -> WorkItem:
    """Create a test work item."""
    return WorkItem(
        work_item_id=work_item_id,
        repo_id=repo_id,
        kind=WorkItemKind.EXECUTION,
        title=title,
        description="A test work item",
        source_type=source_type,
        source_fingerprint=source_fingerprint or ("fp_" + work_item_id),
        trust_level=TrustLevel.SEMI_TRUSTED,
        state=state,
        confidence=confidence,
        risk=risk,
        evidence={"tag": "todo", "message": "fix this"},
        likely_files=["src/main.py"],
    )


# ============================================================================
# Work Item State Transitions
# ============================================================================


class TestWorkItemStateTransitions:
    """Tests for every valid and invalid state transition."""

    def test_discovered_to_suggested(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        item = store.get("wi_001")
        assert item is not None
        assert item.state == WorkItemState.SUGGESTED

    def test_suggested_to_approved(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.SUGGESTED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.APPROVED)

    def test_suggested_to_rejected(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.SUGGESTED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.REJECTED)

    def test_suggested_to_edited(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.SUGGESTED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.EDITED)

    def test_suggested_to_blocked(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.SUGGESTED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.BLOCKED)

    def test_approved_to_executing(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.APPROVED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_edited_to_executing(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.EDITED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_executing_to_completed(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.EXECUTING))
        assert coordinator.advance_work_item("wi_001", WorkItemState.COMPLETED)

    def test_executing_to_failed(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.EXECUTING))
        assert coordinator.advance_work_item("wi_001", WorkItemState.FAILED)

    def test_blocked_to_suggested(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.BLOCKED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)

    def test_blocked_to_rejected(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.BLOCKED))
        assert coordinator.advance_work_item("wi_001", WorkItemState.REJECTED)

    # --- Invalid transitions ---

    def test_discovered_to_approved_invalid(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.APPROVED)

    def test_discovered_to_executing_invalid(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_suggested_to_executing_invalid(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.SUGGESTED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_approved_to_completed_invalid(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.APPROVED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.COMPLETED)

    # --- Terminal states ---

    def test_completed_is_terminal(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.COMPLETED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_failed_is_terminal(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.FAILED))
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)

    def test_rejected_is_terminal(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.REJECTED))
        with pytest.raises(ValueError):
            coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)

    def test_nonexistent_item_raises(self, coordinator):
        with pytest.raises(ValueError, match="not found"):
            coordinator.advance_work_item("nonexistent", WorkItemState.SUGGESTED)

    # --- Transition map completeness ---

    def test_all_transitions_in_map(self):
        assert WorkItemState.SUGGESTED in WORK_ITEM_TRANSITIONS[WorkItemState.DISCOVERED]
        targets = WORK_ITEM_TRANSITIONS[WorkItemState.SUGGESTED]
        assert WorkItemState.APPROVED in targets
        assert WorkItemState.EDITED in targets
        assert WorkItemState.REJECTED in targets
        assert WorkItemState.BLOCKED in targets
        assert WorkItemState.EXECUTING in WORK_ITEM_TRANSITIONS[WorkItemState.APPROVED]
        assert WorkItemState.EXECUTING in WORK_ITEM_TRANSITIONS[WorkItemState.EDITED]
        assert WorkItemState.COMPLETED in WORK_ITEM_TRANSITIONS[WorkItemState.EXECUTING]
        assert WorkItemState.FAILED in WORK_ITEM_TRANSITIONS[WorkItemState.EXECUTING]
        assert WorkItemState.SUGGESTED in WORK_ITEM_TRANSITIONS[WorkItemState.BLOCKED]
        assert WorkItemState.REJECTED in WORK_ITEM_TRANSITIONS[WorkItemState.BLOCKED]

    def test_terminal_states_not_in_map(self):
        assert WorkItemState.COMPLETED not in WORK_ITEM_TRANSITIONS
        assert WorkItemState.FAILED not in WORK_ITEM_TRANSITIONS
        assert WorkItemState.REJECTED not in WORK_ITEM_TRANSITIONS


# ============================================================================
# Full Lifecycle Integration
# ============================================================================


class TestFullLifecycle:
    """Tests for the complete work item lifecycle."""

    def test_discovered_through_completed(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        coordinator.advance_work_item("wi_001", WorkItemState.APPROVED)
        coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)
        coordinator.advance_work_item("wi_001", WorkItemState.COMPLETED)
        item = store.get("wi_001")
        assert item is not None
        assert item.state == WorkItemState.COMPLETED

    def test_discovered_through_edited_to_completed(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        coordinator.advance_work_item("wi_001", WorkItemState.EDITED)
        coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)
        coordinator.advance_work_item("wi_001", WorkItemState.COMPLETED)
        item = store.get("wi_001")
        assert item is not None
        assert item.state == WorkItemState.COMPLETED

    def test_blocked_then_unblocked(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        coordinator.advance_work_item("wi_001", WorkItemState.BLOCKED)
        coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        coordinator.advance_work_item("wi_001", WorkItemState.APPROVED)
        item = store.get("wi_001")
        assert item is not None
        assert item.state == WorkItemState.APPROVED

    def test_execution_failure_path(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        coordinator.advance_work_item("wi_001", WorkItemState.SUGGESTED)
        coordinator.advance_work_item("wi_001", WorkItemState.APPROVED)
        coordinator.advance_work_item("wi_001", WorkItemState.EXECUTING)
        coordinator.advance_work_item("wi_001", WorkItemState.FAILED)
        item = store.get("wi_001")
        assert item is not None
        assert item.state == WorkItemState.FAILED


# ============================================================================
# Batch Promotion
# ============================================================================


class TestBatchPromotion:
    def test_promote_discovered_to_suggested(self, coordinator, store):
        for i in range(5):
            store.save(_make_item(
                work_item_id=f"wi_{i:03d}",
                state=WorkItemState.DISCOVERED,
            ))
        promoted = coordinator.promote_discovered_to_suggested("repo_1")
        assert promoted == 5
        items = store.list_by_repo("repo_1", state=WorkItemState.SUGGESTED)
        assert len(items) == 5

    def test_promote_skips_non_discovered(self, coordinator, store):
        store.save(_make_item(
            work_item_id="wi_001",
            state=WorkItemState.DISCOVERED,
        ))
        store.save(_make_item(
            work_item_id="wi_002",
            state=WorkItemState.APPROVED,
        ))
        store.save(_make_item(
            work_item_id="wi_003",
            state=WorkItemState.SUGGESTED,
        ))
        promoted = coordinator.promote_discovered_to_suggested("repo_1")
        assert promoted == 1

    def test_promote_empty_repo(self, coordinator):
        assert coordinator.promote_discovered_to_suggested("nope") == 0

    def test_promote_emits_approval_requested_events(self, db):
        event_bus = EventBus(source_module="test")
        events: list[EventType] = []
        event_bus.subscribe(
            EventType.APPROVAL_REQUESTED,
            lambda e: events.append(e.event_type),
        )
        coord = Coordinator(db, event_bus=event_bus)
        store = WorkItemStore(db)

        for i in range(3):
            store.save(_make_item(
                work_item_id=f"wi_{i:03d}",
                state=WorkItemState.DISCOVERED,
            ))
        coord.promote_discovered_to_suggested("repo_1")
        assert len(events) == 3

    def test_promote_idempotent(self, coordinator, store):
        store.save(_make_item(state=WorkItemState.DISCOVERED))
        assert coordinator.promote_discovered_to_suggested("repo_1") == 1
        assert coordinator.promote_discovered_to_suggested("repo_1") == 0

    def test_promote_only_affects_target_repo(self, coordinator, store):
        store.save(_make_item(
            work_item_id="wi_001",
            repo_id="repo_1",
            state=WorkItemState.DISCOVERED,
        ))
        store.save(_make_item(
            work_item_id="wi_002",
            repo_id="repo_2",
            state=WorkItemState.DISCOVERED,
        ))
        promoted = coordinator.promote_discovered_to_suggested("repo_1")
        assert promoted == 1
        item2 = store.get("wi_002")
        assert item2 is not None
        assert item2.state == WorkItemState.DISCOVERED


# ============================================================================
# WorkItemStore Extensions
# ============================================================================


class TestWorkItemStoreExtensions:
    def test_find_by_fingerprint(self, store):
        store.save(_make_item())
        found = store.find_by_fingerprint("repo_1", "fp_wi_001")
        assert found is not None
        assert found.work_item_id == "wi_001"

    def test_find_by_fingerprint_not_found(self, store):
        assert store.find_by_fingerprint("repo_1", "nonexistent") is None

    def test_find_by_fingerprint_wrong_repo(self, store):
        store.save(_make_item(repo_id="repo_1"))
        assert store.find_by_fingerprint("repo_2", "fp_wi_001") is None

    def test_find_by_fingerprint_returns_correct_item(self, store):
        store.save(_make_item(work_item_id="wi_001"))
        store.save(_make_item(work_item_id="wi_002"))
        found = store.find_by_fingerprint("repo_1", "fp_wi_002")
        assert found is not None
        assert found.work_item_id == "wi_002"

    def test_get_fingerprints(self, store):
        for i in range(3):
            store.save(_make_item(work_item_id=f"wi_{i:03d}"))
        fps = store.get_fingerprints("repo_1")
        assert len(fps) == 3
        assert "fp_wi_000" in fps
        assert "fp_wi_001" in fps
        assert "fp_wi_002" in fps

    def test_get_fingerprints_empty(self, store):
        assert store.get_fingerprints("repo_1") == set()

    def test_get_fingerprints_returns_set(self, store):
        store.save(_make_item())
        fps = store.get_fingerprints("repo_1")
        assert isinstance(fps, set)

    def test_get_fingerprints_only_target_repo(self, store):
        store.save(_make_item(work_item_id="wi_001", repo_id="repo_1"))
        store.save(_make_item(work_item_id="wi_002", repo_id="repo_2"))
        fps = store.get_fingerprints("repo_1")
        assert len(fps) == 1

    def test_list_all(self, store):
        store.save(_make_item(work_item_id="wi_001", state=WorkItemState.DISCOVERED))
        store.save(_make_item(work_item_id="wi_002", state=WorkItemState.SUGGESTED))
        items = store.list_all()
        assert len(items) == 2

    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_list_all_with_state_filter(self, store):
        store.save(_make_item(work_item_id="wi_001", state=WorkItemState.DISCOVERED))
        store.save(_make_item(work_item_id="wi_002", state=WorkItemState.SUGGESTED))
        store.save(_make_item(work_item_id="wi_003", state=WorkItemState.SUGGESTED))
        items = store.list_all(state=WorkItemState.SUGGESTED)
        assert len(items) == 2
        assert all(i.state == WorkItemState.SUGGESTED for i in items)

    def test_list_all_with_limit(self, store):
        for i in range(10):
            store.save(_make_item(work_item_id=f"wi_{i:03d}"))
        items = store.list_all(limit=3)
        assert len(items) == 3

    def test_list_all_ordered_by_updated_at(self, store):
        store.save(_make_item(work_item_id="wi_001"))
        store.save(_make_item(work_item_id="wi_002"))
        items = store.list_all()
        assert len(items) == 2


# ============================================================================
# Coordinator Work Item Methods
# ============================================================================


class TestCoordinatorWorkItemMethods:
    def test_list_work_items_by_repo(self, coordinator, store):
        store.save(_make_item(work_item_id="wi_001", repo_id="repo_1"))
        store.save(_make_item(work_item_id="wi_002", repo_id="repo_2"))
        items = coordinator.list_work_items(repo_id="repo_1")
        assert len(items) == 1
        assert items[0].work_item_id == "wi_001"

    def test_list_work_items_all(self, coordinator, store):
        store.save(_make_item(work_item_id="wi_001", repo_id="repo_1"))
        store.save(_make_item(work_item_id="wi_002", repo_id="repo_2"))
        items = coordinator.list_work_items()
        assert len(items) == 2

    def test_list_work_items_with_state_filter(self, coordinator, store):
        store.save(_make_item(
            work_item_id="wi_001",
            state=WorkItemState.DISCOVERED,
        ))
        store.save(_make_item(
            work_item_id="wi_002",
            state=WorkItemState.SUGGESTED,
        ))
        items = coordinator.list_work_items(state=WorkItemState.SUGGESTED)
        assert len(items) == 1
        assert items[0].work_item_id == "wi_002"

    def test_list_work_items_by_repo_and_state(self, coordinator, store):
        store.save(_make_item(
            work_item_id="wi_001",
            repo_id="repo_1",
            state=WorkItemState.DISCOVERED,
        ))
        store.save(_make_item(
            work_item_id="wi_002",
            repo_id="repo_1",
            state=WorkItemState.SUGGESTED,
        ))
        store.save(_make_item(
            work_item_id="wi_003",
            repo_id="repo_2",
            state=WorkItemState.SUGGESTED,
        ))
        items = coordinator.list_work_items(
            repo_id="repo_1",
            state=WorkItemState.SUGGESTED,
        )
        assert len(items) == 1
        assert items[0].work_item_id == "wi_002"

    def test_list_work_items_empty(self, coordinator):
        assert coordinator.list_work_items() == []

    def test_get_work_item(self, coordinator, store):
        store.save(_make_item())
        item = coordinator.get_work_item("wi_001")
        assert item is not None
        assert item.title == "Test item"
        assert item.risk == RiskLevel.LOW

    def test_get_work_item_not_found(self, coordinator):
        assert coordinator.get_work_item("nonexistent") is None

    def test_save_work_item(self, coordinator):
        item = _make_item()
        coordinator.save_work_item(item)
        retrieved = coordinator.get_work_item("wi_001")
        assert retrieved is not None
        assert retrieved.title == "Test item"

    def test_save_work_item_overwrites(self, coordinator):
        coordinator.save_work_item(_make_item(title="Original"))
        coordinator.save_work_item(_make_item(title="Updated"))
        item = coordinator.get_work_item("wi_001")
        assert item is not None
        assert item.title == "Updated"

    def test_get_known_fingerprints(self, coordinator, store):
        store.save(_make_item(work_item_id="wi_001"))
        store.save(_make_item(work_item_id="wi_002"))
        fps = coordinator.get_known_fingerprints("repo_1")
        assert len(fps) == 2
        assert "fp_wi_001" in fps
        assert "fp_wi_002" in fps

    def test_get_known_fingerprints_empty(self, coordinator):
        fps = coordinator.get_known_fingerprints("repo_nonexistent")
        assert fps == set()
