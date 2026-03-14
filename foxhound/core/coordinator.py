"""Central coordinator that orchestrates the Foxhound system.

The coordinator assigns job envelopes, advances state machines, routes
events, acquires locks, and authorizes spawned helper jobs. It connects
the queue, lock manager, event bus, and storage layer into a unified
scheduling loop.
"""

from datetime import UTC, datetime
from uuid import uuid4

from foxhound.core.event_bus import EventBus
from foxhound.core.lock_manager import LockManager, LockType
from foxhound.core.models import (
    EventType,
    JobEnvelope,
    JobPriority,
    JobStatus,
    JobType,
    RunRecord,
    RunState,
    WorkItem,
    WorkItemState,
)
from foxhound.core.queue import MAX_SPAWN_DEPTH, JobQueue
from foxhound.storage.database import Database, RunStore, WorkItemStore


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


# Valid work item state transitions
WORK_ITEM_TRANSITIONS: dict[WorkItemState, set[WorkItemState]] = {
    WorkItemState.DISCOVERED: {WorkItemState.SUGGESTED},
    WorkItemState.SUGGESTED: {
        WorkItemState.APPROVED,
        WorkItemState.EDITED,
        WorkItemState.REJECTED,
        WorkItemState.BLOCKED,
    },
    WorkItemState.APPROVED: {WorkItemState.EXECUTING},
    WorkItemState.EDITED: {WorkItemState.EXECUTING},
    WorkItemState.BLOCKED: {WorkItemState.SUGGESTED, WorkItemState.REJECTED},
    WorkItemState.EXECUTING: {WorkItemState.COMPLETED, WorkItemState.FAILED},
}

# Valid run state transitions
RUN_STATE_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.QUEUED: {RunState.PREPARING, RunState.CANCELLED},
    RunState.PREPARING: {RunState.CONTEXT_BUILT, RunState.FAILED},
    RunState.CONTEXT_BUILT: {RunState.EXECUTING, RunState.FAILED},
    RunState.EXECUTING: {RunState.VALIDATING, RunState.FAILED},
    RunState.VALIDATING: {RunState.SECURITY_REVIEW, RunState.FAILED},
    RunState.SECURITY_REVIEW: {RunState.BRANCH_READY, RunState.FAILED},
    RunState.BRANCH_READY: {RunState.PR_DRAFT_READY, RunState.COMPLETED, RunState.FAILED},
    RunState.PR_DRAFT_READY: {RunState.COMPLETED, RunState.FAILED},
}


class SpawnRequest:
    """A request from a worker to spawn a child job."""

    def __init__(
        self,
        parent_job: JobEnvelope,
        work_item_id: str,
        job_type: JobType,
        budget: float | None = None,
        timeout_seconds: int | None = None,
        priority: JobPriority | None = None,
    ) -> None:
        self.parent_job = parent_job
        self.work_item_id = work_item_id
        self.job_type = job_type
        self.budget = budget
        self.timeout_seconds = timeout_seconds
        self.priority = priority


class SpawnDecision:
    """Result of a spawn authorization decision."""

    def __init__(
        self,
        approved: bool,
        job: JobEnvelope | None = None,
        reason: str = "",
    ) -> None:
        self.approved = approved
        self.job = job
        self.reason = reason


class Coordinator:
    """Central scheduler that orchestrates the Foxhound system.

    Connects queue -> harness -> workers -> observer data flow. Manages
    state transitions, lock acquisition, and spawn authorization.
    """

    def __init__(
        self,
        db: Database,
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._queue = JobQueue(db)
        self._locks = LockManager(db)
        self._work_items = WorkItemStore(db)
        self._runs = RunStore(db)
        self._event_bus = event_bus or EventBus(source_module="coordinator")

    @property
    def queue(self) -> JobQueue:
        """Access the job queue."""
        return self._queue

    @property
    def locks(self) -> LockManager:
        """Access the lock manager."""
        return self._locks

    @property
    def event_bus(self) -> EventBus:
        """Access the event bus."""
        return self._event_bus

    def advance_work_item(
        self, work_item_id: str, new_state: WorkItemState
    ) -> bool:
        """Advance a work item through its state machine.

        Validates the transition is legal before applying it.

        Args:
            work_item_id: The work item to advance.
            new_state: The target state.

        Returns:
            True if the transition was applied.

        Raises:
            ValueError: If the transition is not valid.
        """
        item = self._work_items.get(work_item_id)
        if item is None:
            raise ValueError(f"Work item {work_item_id} not found")

        valid_targets = WORK_ITEM_TRANSITIONS.get(item.state, set())
        if new_state not in valid_targets:
            raise ValueError(
                f"Invalid transition: {item.state.value} -> {new_state.value}. "
                f"Valid targets: {[s.value for s in valid_targets]}"
            )

        return self._work_items.update_state(work_item_id, new_state)

    def advance_run(self, run_id: str, new_state: RunState) -> bool:
        """Advance a run through its state machine.

        Validates the transition is legal before applying it.

        Args:
            run_id: The run to advance.
            new_state: The target state.

        Returns:
            True if the transition was applied.

        Raises:
            ValueError: If the transition is not valid.
        """
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        valid_targets = RUN_STATE_TRANSITIONS.get(run.state, set())
        if new_state not in valid_targets:
            raise ValueError(
                f"Invalid transition: {run.state.value} -> {new_state.value}. "
                f"Valid targets: {[s.value for s in valid_targets]}"
            )

        return self._runs.update_state(run_id, new_state)

    def dispatch_next(
        self, job_type: JobType | None = None
    ) -> JobEnvelope | None:
        """Dequeue and dispatch the next available job.

        Emits a RUN_QUEUED event when a job is dispatched.

        Args:
            job_type: Optional filter by job type.

        Returns:
            The dispatched job, or None if queue is empty.
        """
        job = self._queue.dequeue(job_type=job_type)
        if job is None:
            return None

        self._event_bus.emit(
            event_type=EventType.RUN_QUEUED,
            source_module="coordinator",
            job_id=job.job_id,
            repo_id=job.repo_id,
            payload={
                "job_type": job.job_type.value,
                "priority": job.priority.value,
                "spawn_depth": job.spawn_depth,
            },
        )

        return job

    def create_run(
        self,
        job: JobEnvelope,
        worker_type: str,
    ) -> RunRecord:
        """Create a new run record for a dispatched job.

        Args:
            job: The job being executed.
            worker_type: The type of worker handling the job.

        Returns:
            The created RunRecord.
        """
        run = RunRecord(
            run_id=str(uuid4()),
            job_id=job.job_id,
            worker_type=worker_type,
            state=RunState.QUEUED,
        )
        self._runs.save(run)

        self._event_bus.emit(
            event_type=EventType.RUN_STARTED,
            source_module="coordinator",
            run_id=run.run_id,
            job_id=job.job_id,
            repo_id=job.repo_id,
            payload={"worker_type": worker_type},
        )

        return run

    def complete_job(self, job_id: str, run_id: str | None = None) -> None:
        """Mark a job as completed and emit events.

        Args:
            job_id: The job to complete.
            run_id: Optional associated run ID.
        """
        self._queue.complete(job_id)
        self._locks.release_by_owner(job_id)

        job = self._queue.get(job_id)
        self._event_bus.emit(
            event_type=EventType.RUN_COMPLETED,
            source_module="coordinator",
            job_id=job_id,
            run_id=run_id,
            repo_id=job.repo_id if job else None,
        )

    def fail_job(
        self, job_id: str, reason: str, run_id: str | None = None
    ) -> None:
        """Mark a job as failed and release its locks.

        Args:
            job_id: The job that failed.
            reason: Failure reason.
            run_id: Optional associated run ID.
        """
        self._queue.fail(job_id)
        self._locks.release_by_owner(job_id)

        job = self._queue.get(job_id)
        self._event_bus.emit(
            event_type=EventType.RUN_FAILED,
            source_module="coordinator",
            job_id=job_id,
            run_id=run_id,
            repo_id=job.repo_id if job else None,
            payload={"reason": reason},
        )

    def acquire_promotion_lock(
        self, repo_id: str, job_id: str, ttl_seconds: int = 600
    ) -> bool:
        """Acquire a promotion lock for a repo before branch/PR creation.

        Promotion locks are serialized per repo to prevent conflicts.

        Args:
            repo_id: The target repository.
            job_id: The job requesting promotion.
            ttl_seconds: Lock time-to-live.

        Returns:
            True if the lock was acquired.
        """
        result = self._locks.acquire(
            resource_type=LockType.PROMOTION,
            resource_key=repo_id,
            owner_job_id=job_id,
            ttl_seconds=ttl_seconds,
        )
        return result.acquired

    def authorize_spawn(self, request: SpawnRequest) -> SpawnDecision:
        """Authorize a worker spawn request.

        Validates spawn depth and budget before enqueuing the child job.

        Args:
            request: The spawn request to evaluate.

        Returns:
            SpawnDecision with approval status and optional child job.
        """
        child_depth = request.parent_job.spawn_depth + 1

        if child_depth > MAX_SPAWN_DEPTH:
            self._event_bus.emit(
                event_type=EventType.WORKER_SPAWN_FAILED,
                source_module="coordinator",
                job_id=request.parent_job.job_id,
                repo_id=request.parent_job.repo_id,
                payload={
                    "reason": f"Spawn depth {child_depth} exceeds max {MAX_SPAWN_DEPTH}",
                    "requested_type": request.job_type.value,
                },
            )
            return SpawnDecision(
                approved=False,
                reason=f"Spawn depth {child_depth} exceeds maximum of {MAX_SPAWN_DEPTH}",
            )

        budget = request.budget if request.budget is not None else request.parent_job.budget
        if budget <= 0:
            self._event_bus.emit(
                event_type=EventType.WORKER_SPAWN_FAILED,
                source_module="coordinator",
                job_id=request.parent_job.job_id,
                repo_id=request.parent_job.repo_id,
                payload={
                    "reason": "Insufficient budget",
                    "requested_type": request.job_type.value,
                },
            )
            return SpawnDecision(
                approved=False,
                reason="Insufficient budget for spawned job",
            )

        self._event_bus.emit(
            event_type=EventType.WORKER_SPAWN_APPROVED,
            source_module="coordinator",
            job_id=request.parent_job.job_id,
            repo_id=request.parent_job.repo_id,
            payload={
                "child_type": request.job_type.value,
                "child_depth": child_depth,
                "child_budget": budget,
            },
        )

        child_job = self._queue.enqueue_spawned(
            parent_job=request.parent_job,
            work_item_id=request.work_item_id,
            job_type=request.job_type,
            budget=request.budget,
            timeout_seconds=request.timeout_seconds,
            priority=request.priority,
        )

        return SpawnDecision(approved=True, job=child_job)

    def promote_discovered_to_suggested(self, repo_id: str) -> int:
        """Batch-promote all DISCOVERED work items to SUGGESTED for a repo.

        Returns:
            Number of items promoted.
        """
        items = self._work_items.list_by_repo(
            repo_id, state=WorkItemState.DISCOVERED
        )
        promoted = 0
        for item in items:
            if self._work_items.update_state(
                item.work_item_id, WorkItemState.SUGGESTED
            ):
                self._event_bus.emit(
                    event_type=EventType.APPROVAL_REQUESTED,
                    source_module="coordinator",
                    repo_id=repo_id,
                    payload={
                        "work_item_id": item.work_item_id,
                        "title": item.title,
                        "risk": item.risk.value,
                    },
                )
                promoted += 1
        return promoted

    def list_work_items(
        self,
        repo_id: str | None = None,
        state: WorkItemState | None = None,
    ) -> list[WorkItem]:
        """List work items with optional filters.

        Args:
            repo_id: Filter by repository.
            state: Filter by state.

        Returns:
            List of WorkItem objects.
        """
        if repo_id:
            return self._work_items.list_by_repo(repo_id, state=state)
        return self._work_items.list_all(state=state)

    def get_work_item(self, work_item_id: str) -> WorkItem | None:
        """Get a single work item by ID."""
        return self._work_items.get(work_item_id)

    def save_work_item(self, item: WorkItem) -> None:
        """Save a work item to storage."""
        self._work_items.save(item)

    def get_known_fingerprints(self, repo_id: str) -> set[str]:
        """Get known fingerprints for dedup during discovery."""
        return self._work_items.get_fingerprints(repo_id)

    def get_queue_stats(self) -> dict[str, int]:
        """Get counts of jobs in each status.

        Returns:
            Dict mapping status names to counts.
        """
        return {
            status.value: self._queue.count_by_status(status)
            for status in JobStatus
        }
