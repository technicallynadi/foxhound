"""Resource locking system for serialized access to critical resources.

Provides lease-based locking backed by SQLite to prevent concurrent
mutations on repos, workspaces, promotion paths, and config changes.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from foxhound.storage.database import Database


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class LockType(StrEnum):
    """Types of resources that can be locked."""

    REPO = "repo"
    WORKSPACE = "workspace"
    PROMOTION = "promotion"
    CONFIG_MUTATION = "config_mutation"


class LockResult:
    """Result of a lock acquisition attempt."""

    def __init__(
        self,
        acquired: bool,
        lock_id: str | None = None,
        holder_job_id: str | None = None,
    ) -> None:
        self.acquired = acquired
        self.lock_id = lock_id
        self.holder_job_id = holder_job_id

    def __bool__(self) -> bool:
        return self.acquired


class LockManager:
    """SQLite-backed resource lock manager with lease-based expiry.

    Prevents concurrent mutations by enforcing exclusive access to
    resources identified by (resource_type, resource_key) pairs.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def acquire(
        self,
        resource_type: LockType,
        resource_key: str,
        owner_job_id: str,
        ttl_seconds: int | None = None,
    ) -> LockResult:
        """Attempt to acquire a lock on a resource.

        Args:
            resource_type: Type of resource to lock.
            resource_key: Unique key identifying the resource instance.
            owner_job_id: Job ID that will own the lock.
            ttl_seconds: Optional time-to-live in seconds. If None, lock has no expiry.

        Returns:
            LockResult indicating success/failure and lock details.
        """
        self._cleanup_expired()

        with self._db.connection() as conn:
            existing = conn.execute(
                """
                SELECT lock_id, owner_job_id, expires_at
                FROM locks
                WHERE resource_type = ? AND resource_key = ?
                """,
                (resource_type.value, resource_key),
            ).fetchone()

            if existing is not None:
                return LockResult(
                    acquired=False,
                    lock_id=existing["lock_id"],
                    holder_job_id=existing["owner_job_id"],
                )

            lock_id = str(uuid4())
            now = _utc_now()
            expires_at = (
                (now + timedelta(seconds=ttl_seconds)).isoformat()
                if ttl_seconds
                else None
            )

            conn.execute(
                """
                INSERT INTO locks (lock_id, resource_type, resource_key,
                                   owner_job_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lock_id,
                    resource_type.value,
                    resource_key,
                    owner_job_id,
                    now.isoformat(),
                    expires_at,
                ),
            )
            conn.commit()

            return LockResult(acquired=True, lock_id=lock_id)

    def release(self, lock_id: str) -> bool:
        """Release a lock by ID.

        Args:
            lock_id: The lock to release.

        Returns:
            True if the lock was found and released.
        """
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM locks WHERE lock_id = ?", (lock_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def release_by_owner(self, owner_job_id: str) -> int:
        """Release all locks held by a specific job.

        Args:
            owner_job_id: The job whose locks should be released.

        Returns:
            Number of locks released.
        """
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM locks WHERE owner_job_id = ?", (owner_job_id,)
            )
            conn.commit()
            return cursor.rowcount

    def is_locked(self, resource_type: LockType, resource_key: str) -> bool:
        """Check if a resource is currently locked.

        Args:
            resource_type: Type of resource to check.
            resource_key: Unique key identifying the resource instance.

        Returns:
            True if the resource has an active (non-expired) lock.
        """
        self._cleanup_expired()

        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM locks
                WHERE resource_type = ? AND resource_key = ?
                """,
                (resource_type.value, resource_key),
            ).fetchone()
            return row is not None

    def get_holder(
        self, resource_type: LockType, resource_key: str
    ) -> str | None:
        """Get the job ID holding a lock on a resource.

        Args:
            resource_type: Type of resource to check.
            resource_key: Unique key identifying the resource instance.

        Returns:
            The owner job ID, or None if not locked.
        """
        self._cleanup_expired()

        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT owner_job_id FROM locks
                WHERE resource_type = ? AND resource_key = ?
                """,
                (resource_type.value, resource_key),
            ).fetchone()
            return row["owner_job_id"] if row else None

    def list_locks(self, owner_job_id: str | None = None) -> list[dict[str, str | None]]:
        """List active locks, optionally filtered by owner.

        Args:
            owner_job_id: Optional filter by owning job.

        Returns:
            List of lock info dicts.
        """
        self._cleanup_expired()

        with self._db.connection() as conn:
            if owner_job_id:
                rows = conn.execute(
                    "SELECT * FROM locks WHERE owner_job_id = ?",
                    (owner_job_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM locks").fetchall()

            return [
                {
                    "lock_id": row["lock_id"],
                    "resource_type": row["resource_type"],
                    "resource_key": row["resource_key"],
                    "owner_job_id": row["owner_job_id"],
                    "acquired_at": row["acquired_at"],
                    "expires_at": row["expires_at"],
                }
                for row in rows
            ]

    def _cleanup_expired(self) -> int:
        """Remove expired locks.

        Returns:
            Number of expired locks removed.
        """
        now = _utc_now().isoformat()
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM locks WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            conn.commit()
            return cursor.rowcount
