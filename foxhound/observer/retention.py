"""Retention policy and pruning for artifact lifecycle management.

Three retention classes control storage growth:
- Class A (long): manifests, run summaries — 180 days default
- Class B (medium): analyzer reports, context packs — 30 days default
- Class C (short): raw logs, stdout dumps — 21 days (success) / 45 days (failure)
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from foxhound.observer.store import RetentionClass
from foxhound.storage.database import ArtifactStore, Database, EventStore


class RetentionConfig(BaseModel):
    """Configurable retention periods per class."""

    class_a_days: int = Field(default=180, description="Class A retention in days")
    class_b_days: int = Field(default=30, description="Class B retention in days")
    class_c_success_days: int = Field(
        default=21, description="Class C retention for successful runs"
    )
    class_c_failure_days: int = Field(
        default=45, description="Class C retention for failed runs"
    )

    model_config = {"extra": "forbid"}


class PruneResult(BaseModel):
    """Result of a pruning operation."""

    artifacts_removed: int = Field(default=0, description="Number of artifacts removed")
    bytes_freed: int = Field(default=0, description="Bytes freed by pruning")
    files_deleted: int = Field(default=0, description="Filesystem files deleted")
    errors: list[str] = Field(default_factory=list, description="Errors encountered")

    model_config = {"extra": "forbid"}


class CompactResult(BaseModel):
    """Result of an event compaction operation."""

    events_compacted: int = Field(default=0, description="Events removed by compaction")
    runs_processed: int = Field(default=0, description="Runs whose events were compacted")

    model_config = {"extra": "forbid"}


class RetentionPolicy:
    """Manages artifact lifecycle and storage growth.

    Enforces retention periods, supports pinning to exempt artifacts
    from pruning, and provides compaction for event streams.
    """

    def __init__(
        self,
        db: Database,
        config: RetentionConfig | None = None,
    ) -> None:
        self._db = db
        self._config = config or RetentionConfig()
        self._artifact_store = ArtifactStore(db)
        self._event_store = EventStore(db)

    @property
    def config(self) -> RetentionConfig:
        """Current retention configuration."""
        return self._config

    def get_cutoff(self, retention_class: str, now: datetime | None = None) -> datetime:
        """Get the cutoff datetime for a retention class."""
        now = now or datetime.now(UTC)
        days_map: dict[str, int] = {
            RetentionClass.A: self._config.class_a_days,
            RetentionClass.B: self._config.class_b_days,
            RetentionClass.C: self._config.class_c_success_days,
        }
        days = days_map.get(retention_class, self._config.class_b_days)
        return now - timedelta(days=days)

    def get_status(self) -> dict[str, Any]:
        """Get retention status with counts and sizes by class."""
        counts = self._artifact_store.count_by_class()
        sizes = self._artifact_store.total_size_by_class()

        status: dict[str, Any] = {}
        for cls in [RetentionClass.A, RetentionClass.B, RetentionClass.C]:
            days_map = {
                RetentionClass.A: self._config.class_a_days,
                RetentionClass.B: self._config.class_b_days,
                RetentionClass.C: self._config.class_c_success_days,
            }
            status[cls] = {
                "count": counts.get(cls, 0),
                "size_bytes": sizes.get(cls, 0),
                "retention_days": days_map.get(cls, 30),
            }

        status["total"] = {
            "count": sum(counts.values()),
            "size_bytes": sum(sizes.values()),
        }
        return status

    def find_expired(
        self,
        retention_class: str,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Find expired, unpinned artifacts for a retention class."""
        cutoff = self.get_cutoff(retention_class, now)
        return self._artifact_store.list_unpinned_before(
            retention_class, cutoff.isoformat()
        )

    def prune(self, now: datetime | None = None) -> PruneResult:
        """Remove expired artifacts across all retention classes."""
        result = PruneResult()

        for cls in [RetentionClass.A, RetentionClass.B, RetentionClass.C]:
            expired = self.find_expired(cls, now)
            for artifact in expired:
                # Try to delete filesystem artifact
                artifact_path = artifact.get("path", "")
                if artifact_path:
                    try:
                        p = Path(artifact_path)
                        if p.exists() and p.is_file():
                            p.unlink()
                            result.files_deleted += 1
                    except OSError as e:
                        result.errors.append(
                            f"Failed to delete {artifact_path}: {e}"
                        )

                # Remove from index
                if self._artifact_store.delete(artifact["artifact_id"]):
                    result.artifacts_removed += 1
                    result.bytes_freed += artifact.get("size_bytes", 0)

        return result

    def compact_events(self, older_than_days: int = 30) -> CompactResult:
        """Compact old event streams by removing detail events.

        Keeps summary events (run started/completed/failed) and removes
        intermediate events older than the specified number of days.
        """
        result = CompactResult()
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        cutoff_iso = cutoff.isoformat()

        keep_event_types = {
            "RunQueued", "RunStarted", "RunCompleted", "RunFailed",
            "SecurityViolationDetected", "ApprovalGranted", "ApprovalRejected",
            "PromotionSucceeded", "PromotionFailed",
        }

        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM events
                WHERE occurred_at < ? AND event_type NOT IN ({})
                """.format(",".join("?" for _ in keep_event_types)),
                (cutoff_iso, *sorted(keep_event_types)),
            )
            result.events_compacted = cursor.rowcount
            conn.commit()

        return result

    def pin_artifact(self, artifact_id: str) -> bool:
        """Pin an artifact to exempt from automatic pruning."""
        return self._artifact_store.set_pinned(artifact_id, True)

    def unpin_artifact(self, artifact_id: str) -> bool:
        """Unpin an artifact."""
        return self._artifact_store.set_pinned(artifact_id, False)
