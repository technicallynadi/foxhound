"""Tests for the lock manager module."""

import time

import pytest

from foxhound.core.lock_manager import LockManager, LockType
from foxhound.storage.database import Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def locks(db: Database) -> LockManager:
    return LockManager(db)


class TestAcquire:
    def test_acquire_succeeds_on_free_resource(self, locks: LockManager) -> None:
        result = locks.acquire(LockType.REPO, "repo-1", "job-1")
        assert result.acquired is True
        assert result.lock_id is not None

    def test_acquire_fails_on_held_resource(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        result = locks.acquire(LockType.REPO, "repo-1", "job-2")
        assert result.acquired is False
        assert result.holder_job_id == "job-1"

    def test_acquire_different_resources_succeeds(self, locks: LockManager) -> None:
        r1 = locks.acquire(LockType.REPO, "repo-1", "job-1")
        r2 = locks.acquire(LockType.REPO, "repo-2", "job-2")
        assert r1.acquired is True
        assert r2.acquired is True

    def test_acquire_different_types_same_key(self, locks: LockManager) -> None:
        r1 = locks.acquire(LockType.REPO, "key-1", "job-1")
        r2 = locks.acquire(LockType.PROMOTION, "key-1", "job-2")
        assert r1.acquired is True
        assert r2.acquired is True

    def test_acquire_with_ttl(self, locks: LockManager) -> None:
        result = locks.acquire(LockType.REPO, "repo-1", "job-1", ttl_seconds=3600)
        assert result.acquired is True

    def test_all_lock_types(self, locks: LockManager) -> None:
        for lt in LockType:
            result = locks.acquire(lt, f"key-{lt.value}", "job-1")
            assert result.acquired is True


class TestRelease:
    def test_release_by_lock_id(self, locks: LockManager) -> None:
        result = locks.acquire(LockType.REPO, "repo-1", "job-1")
        assert locks.release(result.lock_id) is True  # type: ignore[arg-type]
        assert locks.is_locked(LockType.REPO, "repo-1") is False

    def test_release_nonexistent_returns_false(self, locks: LockManager) -> None:
        assert locks.release("nonexistent") is False

    def test_release_by_owner(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        locks.acquire(LockType.WORKSPACE, "ws-1", "job-1")

        released = locks.release_by_owner("job-1")
        assert released == 2
        assert locks.is_locked(LockType.REPO, "repo-1") is False
        assert locks.is_locked(LockType.WORKSPACE, "ws-1") is False

    def test_release_by_owner_does_not_affect_others(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        locks.acquire(LockType.REPO, "repo-2", "job-2")

        locks.release_by_owner("job-1")
        assert locks.is_locked(LockType.REPO, "repo-1") is False
        assert locks.is_locked(LockType.REPO, "repo-2") is True

    def test_reacquire_after_release(self, locks: LockManager) -> None:
        result = locks.acquire(LockType.REPO, "repo-1", "job-1")
        locks.release(result.lock_id)  # type: ignore[arg-type]

        result2 = locks.acquire(LockType.REPO, "repo-1", "job-2")
        assert result2.acquired is True


class TestExpiry:
    def test_expired_lock_is_cleaned_up(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1", ttl_seconds=1)
        time.sleep(1.1)

        assert locks.is_locked(LockType.REPO, "repo-1") is False

    def test_expired_lock_allows_reacquisition(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1", ttl_seconds=1)
        time.sleep(1.1)

        result = locks.acquire(LockType.REPO, "repo-1", "job-2")
        assert result.acquired is True


class TestQuery:
    def test_is_locked(self, locks: LockManager) -> None:
        assert locks.is_locked(LockType.REPO, "repo-1") is False
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        assert locks.is_locked(LockType.REPO, "repo-1") is True

    def test_get_holder(self, locks: LockManager) -> None:
        assert locks.get_holder(LockType.REPO, "repo-1") is None
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        assert locks.get_holder(LockType.REPO, "repo-1") == "job-1"

    def test_list_locks_all(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        locks.acquire(LockType.PROMOTION, "repo-2", "job-2")

        all_locks = locks.list_locks()
        assert len(all_locks) == 2

    def test_list_locks_by_owner(self, locks: LockManager) -> None:
        locks.acquire(LockType.REPO, "repo-1", "job-1")
        locks.acquire(LockType.WORKSPACE, "ws-1", "job-1")
        locks.acquire(LockType.PROMOTION, "repo-2", "job-2")

        job1_locks = locks.list_locks(owner_job_id="job-1")
        assert len(job1_locks) == 2
        assert all(lk["owner_job_id"] == "job-1" for lk in job1_locks)


class TestPromotionLocking:
    def test_promotion_lock_serializes_repo_access(self, locks: LockManager) -> None:
        r1 = locks.acquire(LockType.PROMOTION, "repo-1/main", "job-1")
        assert r1.acquired is True

        r2 = locks.acquire(LockType.PROMOTION, "repo-1/main", "job-2")
        assert r2.acquired is False
        assert r2.holder_job_id == "job-1"

    def test_different_repo_promotions_independent(self, locks: LockManager) -> None:
        r1 = locks.acquire(LockType.PROMOTION, "repo-1/main", "job-1")
        r2 = locks.acquire(LockType.PROMOTION, "repo-2/main", "job-2")
        assert r1.acquired is True
        assert r2.acquired is True
