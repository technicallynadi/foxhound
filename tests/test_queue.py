"""Tests for the job queue module."""

import pytest

from foxhound.core.models import (
    ExecutionStrategy,
    JobPriority,
    JobStatus,
    JobType,
    PolicyRef,
    RecipeRef,
)
from foxhound.core.queue import MAX_SPAWN_DEPTH, JobQueue
from foxhound.storage.database import Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def queue(db: Database) -> JobQueue:
    return JobQueue(db)


def _recipe_ref() -> RecipeRef:
    return RecipeRef(name="test_recipe", version="1.0.0", content_hash="abc123")


def _policy_ref() -> PolicyRef:
    return PolicyRef(name="test_policy", version="1.0.0", content_hash="def456")


class TestEnqueue:
    def test_enqueue_creates_job_with_frozen_snapshot(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        assert job.status == JobStatus.QUEUED
        assert job.work_item_id == "wi-1"
        assert job.repo_id == "repo-1"
        assert job.job_type == JobType.EXECUTION
        assert job.execution_snapshot.recipe_ref.name == "test_recipe"
        assert job.execution_snapshot.policy_ref.name == "test_policy"
        assert job.execution_snapshot.config_hash == "cfg-hash"
        assert job.spawn_depth == 0
        assert job.parent_job_id is None

    def test_enqueue_with_custom_priority_and_budget(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.DISCOVERY,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            priority=JobPriority.HIGH,
            budget=5.0,
            timeout_seconds=600,
        )

        assert job.priority == JobPriority.HIGH
        assert job.budget == 5.0
        assert job.timeout_seconds == 600

    def test_enqueue_with_execution_strategy(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            execution_strategy=ExecutionStrategy.RALPH_LOOP,
            model_tier="reasoning",
        )

        assert job.execution_snapshot.execution_strategy == ExecutionStrategy.RALPH_LOOP
        assert job.execution_snapshot.model_tier == "reasoning"

    def test_enqueue_rejects_excessive_spawn_depth(self, queue: JobQueue) -> None:
        with pytest.raises(ValueError, match="exceeds maximum"):
            queue.enqueue(
                work_item_id="wi-1",
                repo_id="repo-1",
                job_type=JobType.EXECUTION,
                recipe_ref=_recipe_ref(),
                policy_ref=_policy_ref(),
                config_hash="cfg-hash",
                spawn_depth=MAX_SPAWN_DEPTH + 1,
            )

    def test_enqueue_all_job_types(self, queue: JobQueue) -> None:
        for jt in JobType:
            job = queue.enqueue(
                work_item_id=f"wi-{jt.value}",
                repo_id="repo-1",
                job_type=jt,
                recipe_ref=_recipe_ref(),
                policy_ref=_policy_ref(),
                config_hash="cfg-hash",
            )
            assert job.job_type == jt

    def test_enqueue_persists_to_storage(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        retrieved = queue.get(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id
        assert retrieved.execution_snapshot.recipe_ref.name == "test_recipe"


class TestEnqueueSpawned:
    def test_spawned_job_inherits_parent_snapshot(self, queue: JobQueue) -> None:
        parent = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        child = queue.enqueue_spawned(
            parent_job=parent,
            work_item_id="wi-2",
            job_type=JobType.ANALYZER,
        )

        assert child.spawn_depth == 1
        assert child.parent_job_id == parent.job_id
        assert child.repo_id == parent.repo_id
        assert child.execution_snapshot.recipe_ref.name == "test_recipe"
        assert child.execution_snapshot.config_hash == "cfg-hash"

    def test_spawned_job_overrides(self, queue: JobQueue) -> None:
        parent = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            budget=10.0,
        )

        child = queue.enqueue_spawned(
            parent_job=parent,
            work_item_id="wi-2",
            job_type=JobType.ANALYZER,
            budget=2.0,
            timeout_seconds=120,
            priority=JobPriority.LOW,
        )

        assert child.budget == 2.0
        assert child.timeout_seconds == 120
        assert child.priority == JobPriority.LOW

    def test_spawned_rejects_depth_exceeding_max(self, queue: JobQueue) -> None:
        parent = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            spawn_depth=MAX_SPAWN_DEPTH,
        )

        with pytest.raises(ValueError, match="exceeds maximum"):
            queue.enqueue_spawned(
                parent_job=parent,
                work_item_id="wi-2",
                job_type=JobType.ANALYZER,
            )


class TestDequeue:
    def test_dequeue_returns_highest_priority_first(self, queue: JobQueue) -> None:
        queue.enqueue(
            work_item_id="wi-low",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            priority=JobPriority.LOW,
        )
        queue.enqueue(
            work_item_id="wi-high",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
            priority=JobPriority.HIGH,
        )

        job = queue.dequeue()
        assert job is not None
        assert job.work_item_id == "wi-high"
        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None

    def test_dequeue_empty_returns_none(self, queue: JobQueue) -> None:
        assert queue.dequeue() is None

    def test_dequeue_by_job_type(self, queue: JobQueue) -> None:
        queue.enqueue(
            work_item_id="wi-exec",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )
        queue.enqueue(
            work_item_id="wi-disc",
            repo_id="repo-1",
            job_type=JobType.DISCOVERY,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        job = queue.dequeue(job_type=JobType.DISCOVERY)
        assert job is not None
        assert job.job_type == JobType.DISCOVERY

    def test_dequeue_skips_running_jobs(self, queue: JobQueue) -> None:
        queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        first = queue.dequeue()
        assert first is not None

        second = queue.dequeue()
        assert second is None


class TestStatusTransitions:
    def test_complete_job(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        assert queue.complete(job.job_id)
        completed = queue.get(job.job_id)
        assert completed is not None
        assert completed.status == JobStatus.COMPLETED
        assert completed.finished_at is not None

    def test_fail_job(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        assert queue.fail(job.job_id)
        failed = queue.get(job.job_id)
        assert failed is not None
        assert failed.status == JobStatus.FAILED

    def test_cancel_job(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        assert queue.cancel(job.job_id)
        cancelled = queue.get(job.job_id)
        assert cancelled is not None
        assert cancelled.status == JobStatus.CANCELLED


class TestPollAndCount:
    def test_poll_by_status(self, queue: JobQueue) -> None:
        for i in range(3):
            queue.enqueue(
                work_item_id=f"wi-{i}",
                repo_id="repo-1",
                job_type=JobType.EXECUTION,
                recipe_ref=_recipe_ref(),
                policy_ref=_policy_ref(),
                config_hash="cfg-hash",
            )

        queued = queue.poll(status=JobStatus.QUEUED)
        assert len(queued) == 3

    def test_count_by_status(self, queue: JobQueue) -> None:
        for i in range(3):
            queue.enqueue(
                work_item_id=f"wi-{i}",
                repo_id="repo-1",
                job_type=JobType.EXECUTION,
                recipe_ref=_recipe_ref(),
                policy_ref=_policy_ref(),
                config_hash="cfg-hash",
            )

        assert queue.count_by_status(JobStatus.QUEUED) == 3
        assert queue.count_by_status(JobStatus.RUNNING) == 0

    def test_timestamps_recorded(self, queue: JobQueue) -> None:
        job = queue.enqueue(
            work_item_id="wi-1",
            repo_id="repo-1",
            job_type=JobType.EXECUTION,
            recipe_ref=_recipe_ref(),
            policy_ref=_policy_ref(),
            config_hash="cfg-hash",
        )

        assert job.queued_at is not None
        assert job.started_at is None
        assert job.finished_at is None
