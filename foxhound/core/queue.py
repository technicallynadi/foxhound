"""Durable job queue with immutable execution snapshots.

Provides enqueue, dequeue, and poll operations backed by SQLite via the
storage layer. Jobs are frozen at queue time with an ExecutionSnapshot
that cannot be changed after submission.
"""

from datetime import UTC, datetime
from uuid import uuid4

from foxhound.core.models import (
    ExecutionSnapshot,
    ExecutionStrategy,
    JobEnvelope,
    JobPriority,
    JobStatus,
    JobType,
    PolicyRef,
    RecipeRef,
)
from foxhound.storage.database import Database, JobStore

MAX_SPAWN_DEPTH = 2


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class JobQueue:
    """SQLite-backed durable job queue.

    Enforces immutable execution snapshots, spawn depth limits, and
    priority-ordered dequeue.
    """

    def __init__(self, db: Database) -> None:
        self._store = JobStore(db)

    def enqueue(
        self,
        *,
        work_item_id: str,
        repo_id: str,
        job_type: JobType,
        recipe_ref: RecipeRef,
        policy_ref: PolicyRef,
        config_hash: str,
        execution_strategy: ExecutionStrategy = ExecutionStrategy.ONE_SHOT,
        model_tier: str = "balanced",
        priority: JobPriority = JobPriority.NORMAL,
        budget: float = 1.0,
        timeout_seconds: int = 300,
        parent_job_id: str | None = None,
        spawn_depth: int = 0,
    ) -> JobEnvelope:
        """Enqueue a new job with a frozen execution snapshot.

        Args:
            work_item_id: Originating work item ID.
            repo_id: Target repository ID.
            job_type: Type of job to queue.
            recipe_ref: Recipe reference to freeze.
            policy_ref: Policy reference to freeze.
            config_hash: Hash of combined configuration.
            execution_strategy: Strategy for execution.
            model_tier: Model tier to use.
            priority: Job priority level.
            budget: Allocated budget.
            timeout_seconds: Hard timeout.
            parent_job_id: Parent job ID for spawned jobs.
            spawn_depth: Current spawn depth (0 for root jobs).

        Returns:
            The queued JobEnvelope with frozen snapshot.

        Raises:
            ValueError: If spawn depth exceeds maximum.
        """
        if spawn_depth > MAX_SPAWN_DEPTH:
            raise ValueError(
                f"Spawn depth {spawn_depth} exceeds maximum of {MAX_SPAWN_DEPTH}"
            )

        snapshot = ExecutionSnapshot(
            recipe_ref=recipe_ref,
            policy_ref=policy_ref,
            execution_strategy=execution_strategy,
            model_tier=model_tier,
            config_hash=config_hash,
        )

        job = JobEnvelope(
            job_id=str(uuid4()),
            work_item_id=work_item_id,
            repo_id=repo_id,
            job_type=job_type,
            priority=priority,
            status=JobStatus.QUEUED,
            execution_snapshot=snapshot,
            budget=budget,
            timeout_seconds=timeout_seconds,
            spawn_depth=spawn_depth,
            parent_job_id=parent_job_id,
            queued_at=_utc_now(),
        )

        self._store.save(job)
        return job

    def enqueue_spawned(
        self,
        *,
        parent_job: JobEnvelope,
        work_item_id: str,
        job_type: JobType,
        budget: float | None = None,
        timeout_seconds: int | None = None,
        priority: JobPriority | None = None,
    ) -> JobEnvelope:
        """Enqueue a spawned child job inheriting the parent's snapshot.

        The child inherits the parent's execution snapshot (immutable),
        repo_id, and increments spawn_depth by 1.

        Args:
            parent_job: The parent job to inherit from.
            work_item_id: Work item for the child job.
            job_type: Type of child job.
            budget: Override budget (defaults to parent's remaining budget).
            timeout_seconds: Override timeout (defaults to parent's).
            priority: Override priority (defaults to parent's).

        Returns:
            The queued child JobEnvelope.

        Raises:
            ValueError: If child would exceed max spawn depth.
        """
        child_depth = parent_job.spawn_depth + 1
        if child_depth > MAX_SPAWN_DEPTH:
            raise ValueError(
                f"Spawn depth {child_depth} exceeds maximum of {MAX_SPAWN_DEPTH}"
            )

        job = JobEnvelope(
            job_id=str(uuid4()),
            work_item_id=work_item_id,
            repo_id=parent_job.repo_id,
            job_type=job_type,
            priority=priority or parent_job.priority,
            status=JobStatus.QUEUED,
            execution_snapshot=parent_job.execution_snapshot,
            budget=budget if budget is not None else parent_job.budget,
            timeout_seconds=timeout_seconds or parent_job.timeout_seconds,
            spawn_depth=child_depth,
            parent_job_id=parent_job.job_id,
            queued_at=_utc_now(),
        )

        self._store.save(job)
        return job

    def dequeue(self, job_type: JobType | None = None) -> JobEnvelope | None:
        """Dequeue the highest-priority queued job.

        Atomically transitions the job from QUEUED to RUNNING.

        Args:
            job_type: Optional filter by job type.

        Returns:
            The dequeued job, or None if the queue is empty.
        """
        queued = self._store.list_by_status(JobStatus.QUEUED)

        if job_type is not None:
            queued = [j for j in queued if j.job_type == job_type]

        if not queued:
            return None

        job = queued[0]
        now = _utc_now()
        self._store.update_status(job.job_id, JobStatus.RUNNING, started_at=now)

        return JobEnvelope(
            job_id=job.job_id,
            work_item_id=job.work_item_id,
            repo_id=job.repo_id,
            job_type=job.job_type,
            priority=job.priority,
            status=JobStatus.RUNNING,
            execution_snapshot=job.execution_snapshot,
            budget=job.budget,
            timeout_seconds=job.timeout_seconds,
            spawn_depth=job.spawn_depth,
            parent_job_id=job.parent_job_id,
            queued_at=job.queued_at,
            started_at=now,
        )

    def complete(self, job_id: str) -> bool:
        """Mark a job as completed.

        Args:
            job_id: The job to complete.

        Returns:
            True if the job was updated.
        """
        return self._store.update_status(
            job_id, JobStatus.COMPLETED, finished_at=_utc_now()
        )

    def fail(self, job_id: str) -> bool:
        """Mark a job as failed.

        Args:
            job_id: The job to fail.

        Returns:
            True if the job was updated.
        """
        return self._store.update_status(
            job_id, JobStatus.FAILED, finished_at=_utc_now()
        )

    def cancel(self, job_id: str) -> bool:
        """Mark a job as cancelled.

        Args:
            job_id: The job to cancel.

        Returns:
            True if the job was updated.
        """
        return self._store.update_status(
            job_id, JobStatus.CANCELLED, finished_at=_utc_now()
        )

    def poll(
        self,
        status: JobStatus = JobStatus.QUEUED,
        limit: int = 100,
    ) -> list[JobEnvelope]:
        """Poll jobs by status, ordered by priority then queue time.

        Args:
            status: Job status to filter by.
            limit: Maximum number of jobs to return.

        Returns:
            List of matching jobs ordered by priority and queue time.
        """
        return self._store.list_by_status(status, limit=limit)

    def get(self, job_id: str) -> JobEnvelope | None:
        """Get a job by ID.

        Args:
            job_id: The job ID to look up.

        Returns:
            The job envelope, or None if not found.
        """
        return self._store.get(job_id)

    def count_by_status(self, status: JobStatus) -> int:
        """Count jobs with a given status.

        Args:
            status: The status to count.

        Returns:
            Number of jobs with that status.
        """
        return len(self._store.list_by_status(status, limit=10000))
