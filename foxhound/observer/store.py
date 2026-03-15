"""Observer store for persisting events, manifests, and artifact references.

Subscribes to the event bus and stores all events. Provides manifest recording
and artifact indexing with retention classification.
"""

import json
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

from foxhound.core.event_bus import EventBus
from foxhound.core.models import EventEnvelope, Manifest
from foxhound.storage.database import ArtifactStore, Database, EventStore


class RetentionClass(StrEnum):
    """Artifact retention classification."""

    A = "A"
    B = "B"
    C = "C"


# Default retention class by artifact type
ARTIFACT_RETENTION_DEFAULTS: dict[str, RetentionClass] = {
    "manifest": RetentionClass.A,
    "run_summary": RetentionClass.A,
    "work_item_record": RetentionClass.A,
    "analyzer_report": RetentionClass.B,
    "context_pack": RetentionClass.B,
    "raw_log": RetentionClass.C,
    "stdout_dump": RetentionClass.C,
    "patch_intermediate": RetentionClass.C,
}


class ObserverStore:
    """Central sink for all system events and artifact tracking.

    Subscribes to the event bus to automatically persist every event.
    Provides methods to record manifests and index artifacts with
    retention classification.
    """

    def __init__(
        self,
        db: Database,
        event_bus: EventBus | None = None,
        artifacts_dir: Path | None = None,
    ) -> None:
        self._db = db
        self._event_store = EventStore(db)
        self._artifact_store = ArtifactStore(db)
        self._artifacts_dir = artifacts_dir
        self._event_count = 0
        self._unsubscribe: Any = None

        if event_bus is not None:
            self.subscribe(event_bus)

    def subscribe(self, event_bus: EventBus) -> None:
        """Subscribe to all events on the bus for persistence."""
        self._unsubscribe = event_bus.subscribe_all(self._on_event)

    def unsubscribe(self) -> None:
        """Remove the event bus subscription."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @property
    def event_count(self) -> int:
        """Number of events persisted since creation."""
        return self._event_count

    def _on_event(self, event: EventEnvelope) -> None:
        """Handle incoming event by persisting it."""
        self._event_store.save(event)
        self._event_count += 1

    def get_events_by_run(self, run_id: str, limit: int = 100) -> list[EventEnvelope]:
        """Get events for a specific run."""
        return self._event_store.list_by_run(run_id, limit=limit)

    def get_recent_events(
        self,
        event_type: Any = None,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        """Get recent events with optional type filter."""
        return self._event_store.list_recent(event_type=event_type, limit=limit)

    def record_manifest(
        self,
        manifest: Manifest,
        run_id: str | None = None,
    ) -> str:
        """Record a manifest as a JSON artifact.

        Writes manifest JSON to the artifacts directory and indexes it
        as a Class A artifact.

        Returns:
            The artifact ID for the recorded manifest.
        """
        effective_run_id = run_id or manifest.run_id
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        manifest_data = manifest.model_dump(mode="json")
        manifest_json = json.dumps(manifest_data, indent=2, default=str)

        # Write to filesystem if artifacts dir is configured
        manifest_path = ""
        if self._artifacts_dir is not None:
            manifest_dir = self._artifacts_dir / "manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_file = manifest_dir / f"{manifest.manifest_id}.json"
            manifest_file.write_text(manifest_json)
            manifest_path = str(manifest_file)

        self._artifact_store.save(
            artifact_id=artifact_id,
            run_id=effective_run_id,
            artifact_type="manifest",
            path=manifest_path,
            size_bytes=len(manifest_json.encode()),
            retention_class=RetentionClass.A,
        )

        return artifact_id

    def index_artifact(
        self,
        run_id: str,
        artifact_type: str,
        path: str,
        size_bytes: int = 0,
        retention_class: str | None = None,
        pinned: bool = False,
    ) -> str:
        """Index an artifact with retention classification.

        Returns:
            The generated artifact ID.
        """
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        effective_class = retention_class or ARTIFACT_RETENTION_DEFAULTS.get(
            artifact_type, RetentionClass.B
        )

        self._artifact_store.save(
            artifact_id=artifact_id,
            run_id=run_id,
            artifact_type=artifact_type,
            path=path,
            size_bytes=size_bytes,
            retention_class=effective_class,
            pinned=pinned,
        )

        return artifact_id

    def get_artifacts_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all artifacts for a run."""
        return self._artifact_store.list_by_run(run_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """Get an artifact by ID."""
        return self._artifact_store.get(artifact_id)

    def pin_artifact(self, artifact_id: str) -> bool:
        """Pin an artifact to exempt it from pruning."""
        return self._artifact_store.set_pinned(artifact_id, True)

    def unpin_artifact(self, artifact_id: str) -> bool:
        """Unpin an artifact."""
        return self._artifact_store.set_pinned(artifact_id, False)

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage usage statistics by retention class."""
        counts = self._artifact_store.count_by_class()
        sizes = self._artifact_store.total_size_by_class()
        return {
            "counts_by_class": counts,
            "sizes_by_class": sizes,
            "total_artifacts": sum(counts.values()),
            "total_size_bytes": sum(sizes.values()),
        }
