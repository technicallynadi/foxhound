"""Tests for the coordinator module."""

import pytest

from foxhound.core.coordinator import (
    Coordinator,
    SpawnRequest,
)
from foxhound.core.event_bus import EventBus
from foxhound.core.lock_manager import LockType
from foxhound.core.models import (
    EventEnvelope,
    EventType,
    JobStatus,
    JobType,
    PolicyRef,
    RecipeRef,
    RunState,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)
from foxhound.core.queue import MAX_SPAWN_DEPTH
from foxhound.storage.database import Database, WorkItemStore


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(source_module="test")


@pytest.fixture
def coordinator(db: Database, event_bus: EventBus) -> Coordinator:
    return Coordinator(db, event_bus=event_bus)


def _recipe_ref() -> RecipeRef:
    return RecipeRef(name="test_recipe", version="1.0.0", content_hash="abc123")


def _policy_ref() -> PolicyRef:
    return PolicyRef(name="test_policy", version="1.0.0", content_hash="def456")


def _create_work_item(
    db: Database,
    work_item_id: str = "wi-1",
    state: WorkItemState = WorkItemState.DISCOVERED,
) -> WorkItem:
    store = WorkItemStore(db)
    item = WorkItem(
        work_item_id=work_item_id,
        repo_id="repo-1",
        kind=WorkItemKind.EXECUTION,
        title="Test work item",
        source_type="test",
        source_fingerprint="fp-123",
        state=state,
    )
    store.save(item)
    return item


def _enqueue_job(coordinator: Coordinator, **kwargs) -> None:
    defaults = {
        "work_item_id": "wi-1",
        "repo_id": "repo-1",
        "job_type": JobType.EXECUTION,
        "recipe_ref": _recipe_ref(),
        "policy_ref": _policy_ref(),
        "config_hash": "cfg-hash",
    }
    defaults.update(kwargs)
    coordinator.queue.enqueue(**defaults)


class TestWorkItemStateMachine:
    def test_valid_transition_discovered_to_suggested(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.DISCOVERED)
        assert coordinator.advance_work_item("wi-1", WorkItemState.SUGGESTED)

    def test_valid_transition_suggested_to_approved(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.SUGGESTED)
        assert coordinator.advance_work_item("wi-1", WorkItemState.APPROVED)

    def test_valid_transition_approved_to_executing(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.APPROVED)
        assert coordinator.advance_work_item("wi-1", WorkItemState.EXECUTING)

    def test_valid_transition_executing_to_completed(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.EXECUTING)
        assert coordinator.advance_work_item("wi-1", WorkItemState.COMPLETED)

    def test_valid_transition_executing_to_failed(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.EXECUTING)
        assert coordinator.advance_work_item("wi-1", WorkItemState.FAILED)

    def test_invalid_transition_raises(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.DISCOVERED)
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi-1", WorkItemState.COMPLETED)

    def test_nonexistent_work_item_raises(self, coordinator: Coordinator) -> None:
        with pytest.raises(ValueError, match="not found"):
            coordinator.advance_work_item("nonexistent", WorkItemState.SUGGESTED)

    def test_rejected_is_terminal(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _create_work_item(db, state=WorkItemState.REJECTED)
        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_work_item("wi-1", WorkItemState.APPROVED)


class TestRunStateMachine:
    def test_valid_run_lifecycle(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        assert job is not None

        run = coordinator.create_run(job, "ExecutionWorker")
        assert run.state == RunState.QUEUED

        assert coordinator.advance_run(run.run_id, RunState.PREPARING)
        assert coordinator.advance_run(run.run_id, RunState.CONTEXT_BUILT)
        assert coordinator.advance_run(run.run_id, RunState.EXECUTING)
        assert coordinator.advance_run(run.run_id, RunState.VALIDATING)
        assert coordinator.advance_run(run.run_id, RunState.SECURITY_REVIEW)
        assert coordinator.advance_run(run.run_id, RunState.BRANCH_READY)
        assert coordinator.advance_run(run.run_id, RunState.COMPLETED)

    def test_invalid_run_transition_raises(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        run = coordinator.create_run(job, "ExecutionWorker")

        with pytest.raises(ValueError, match="Invalid transition"):
            coordinator.advance_run(run.run_id, RunState.COMPLETED)

    def test_run_can_fail_from_any_active_state(
        self, db: Database, coordinator: Coordinator
    ) -> None:
        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        run = coordinator.create_run(job, "ExecutionWorker")

        coordinator.advance_run(run.run_id, RunState.PREPARING)
        assert coordinator.advance_run(run.run_id, RunState.FAILED)

    def test_nonexistent_run_raises(self, coordinator: Coordinator) -> None:
        with pytest.raises(ValueError, match="not found"):
            coordinator.advance_run("nonexistent", RunState.PREPARING)


class TestDispatch:
    def test_dispatch_next_dequeues_and_emits_event(
        self, coordinator: Coordinator, event_bus: EventBus
    ) -> None:
        events: list[EventEnvelope] = []
        event_bus.subscribe(EventType.RUN_QUEUED, events.append)

        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()

        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert len(events) == 1
        assert events[0].event_type == EventType.RUN_QUEUED

    def test_dispatch_returns_none_when_empty(
        self, coordinator: Coordinator
    ) -> None:
        assert coordinator.dispatch_next() is None

    def test_dispatch_by_job_type(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator, job_type=JobType.EXECUTION, work_item_id="wi-exec")
        _enqueue_job(coordinator, job_type=JobType.DISCOVERY, work_item_id="wi-disc")

        job = coordinator.dispatch_next(job_type=JobType.DISCOVERY)
        assert job is not None
        assert job.job_type == JobType.DISCOVERY


class TestCreateRun:
    def test_create_run_emits_event(
        self, coordinator: Coordinator, event_bus: EventBus
    ) -> None:
        events: list[EventEnvelope] = []
        event_bus.subscribe(EventType.RUN_STARTED, events.append)

        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        run = coordinator.create_run(job, "ExecutionWorker")

        assert run.job_id == job.job_id
        assert run.worker_type == "ExecutionWorker"
        assert len(events) == 1


class TestCompleteAndFail:
    def test_complete_job_releases_locks(
        self, coordinator: Coordinator, event_bus: EventBus
    ) -> None:
        events: list[EventEnvelope] = []
        event_bus.subscribe(EventType.RUN_COMPLETED, events.append)

        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        coordinator.locks.acquire(LockType.REPO, "repo-1", job.job_id)

        coordinator.complete_job(job.job_id)

        completed = coordinator.queue.get(job.job_id)
        assert completed.status == JobStatus.COMPLETED
        assert not coordinator.locks.is_locked(LockType.REPO, "repo-1")
        assert len(events) == 1

    def test_fail_job_releases_locks(
        self, coordinator: Coordinator, event_bus: EventBus
    ) -> None:
        events: list[EventEnvelope] = []
        event_bus.subscribe(EventType.RUN_FAILED, events.append)

        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        coordinator.locks.acquire(LockType.WORKSPACE, "ws-1", job.job_id)

        coordinator.fail_job(job.job_id, "timeout")

        failed = coordinator.queue.get(job.job_id)
        assert failed.status == JobStatus.FAILED
        assert not coordinator.locks.is_locked(LockType.WORKSPACE, "ws-1")
        assert len(events) == 1
        assert events[0].payload["reason"] == "timeout"


class TestPromotionLock:
    def test_acquire_promotion_lock(self, coordinator: Coordinator) -> None:
        assert coordinator.acquire_promotion_lock("repo-1", "job-1")
        assert not coordinator.acquire_promotion_lock("repo-1", "job-2")

    def test_promotion_lock_released_on_complete(
        self, coordinator: Coordinator
    ) -> None:
        _enqueue_job(coordinator)
        job = coordinator.dispatch_next()
        coordinator.acquire_promotion_lock("repo-1", job.job_id)
        coordinator.complete_job(job.job_id)

        assert coordinator.acquire_promotion_lock("repo-1", "job-new")


class TestSpawnAuthorization:
    def test_approve_valid_spawn(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator)
        parent = coordinator.dispatch_next()

        request = SpawnRequest(
            parent_job=parent,
            work_item_id="wi-child",
            job_type=JobType.ANALYZER,
            budget=0.5,
        )
        decision = coordinator.authorize_spawn(request)

        assert decision.approved is True
        assert decision.job is not None
        assert decision.job.spawn_depth == 1
        assert decision.job.parent_job_id == parent.job_id

    def test_reject_spawn_exceeding_depth(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator, spawn_depth=MAX_SPAWN_DEPTH)
        parent = coordinator.dispatch_next()

        request = SpawnRequest(
            parent_job=parent,
            work_item_id="wi-child",
            job_type=JobType.ANALYZER,
        )
        decision = coordinator.authorize_spawn(request)

        assert decision.approved is False
        assert "exceeds maximum" in decision.reason

    def test_reject_spawn_with_zero_budget(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator, budget=1.0)
        parent = coordinator.dispatch_next()

        request = SpawnRequest(
            parent_job=parent,
            work_item_id="wi-child",
            job_type=JobType.ANALYZER,
            budget=0.0,
        )
        decision = coordinator.authorize_spawn(request)

        assert decision.approved is False
        assert "budget" in decision.reason.lower()

    def test_spawn_emits_events(
        self, coordinator: Coordinator, event_bus: EventBus
    ) -> None:
        approved_events: list[EventEnvelope] = []
        failed_events: list[EventEnvelope] = []
        event_bus.subscribe(EventType.WORKER_SPAWN_APPROVED, approved_events.append)
        event_bus.subscribe(EventType.WORKER_SPAWN_FAILED, failed_events.append)

        _enqueue_job(coordinator)
        parent = coordinator.dispatch_next()

        request = SpawnRequest(
            parent_job=parent,
            work_item_id="wi-child",
            job_type=JobType.ANALYZER,
        )
        coordinator.authorize_spawn(request)
        assert len(approved_events) == 1

    def test_spawn_chain_respects_depth(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator)
        parent = coordinator.dispatch_next()

        # Spawn depth 1
        request1 = SpawnRequest(
            parent_job=parent,
            work_item_id="wi-child-1",
            job_type=JobType.ANALYZER,
        )
        decision1 = coordinator.authorize_spawn(request1)
        assert decision1.approved is True
        assert decision1.job.spawn_depth == 1

        # Spawn depth 2 (from child)
        child1 = coordinator.queue.dequeue()
        request2 = SpawnRequest(
            parent_job=child1,
            work_item_id="wi-child-2",
            job_type=JobType.ANALYZER,
        )
        decision2 = coordinator.authorize_spawn(request2)
        assert decision2.approved is True
        assert decision2.job.spawn_depth == 2

        # Spawn depth 3 (exceeds max)
        child2 = coordinator.queue.dequeue()
        request3 = SpawnRequest(
            parent_job=child2,
            work_item_id="wi-child-3",
            job_type=JobType.ANALYZER,
        )
        decision3 = coordinator.authorize_spawn(request3)
        assert decision3.approved is False


class TestQueueStats:
    def test_get_queue_stats(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator, work_item_id="wi-1")
        _enqueue_job(coordinator, work_item_id="wi-2")
        coordinator.dispatch_next()  # moves one to running

        stats = coordinator.get_queue_stats()
        assert stats["queued"] == 1
        assert stats["running"] == 1
        assert stats["completed"] == 0


class TestConcurrency:
    def test_concurrent_discovery_allowed(self, coordinator: Coordinator) -> None:
        _enqueue_job(coordinator, work_item_id="wi-1", job_type=JobType.DISCOVERY)
        _enqueue_job(coordinator, work_item_id="wi-2", job_type=JobType.DISCOVERY)

        job1 = coordinator.dispatch_next(job_type=JobType.DISCOVERY)
        job2 = coordinator.dispatch_next(job_type=JobType.DISCOVERY)

        assert job1 is not None
        assert job2 is not None

    def test_promotion_serialized_per_repo(self, coordinator: Coordinator) -> None:
        assert coordinator.acquire_promotion_lock("repo-1", "job-1")
        assert not coordinator.acquire_promotion_lock("repo-1", "job-2")
        assert coordinator.acquire_promotion_lock("repo-2", "job-3")
