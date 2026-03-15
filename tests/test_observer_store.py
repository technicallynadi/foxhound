"""Tests for the observer store module."""

import json
import uuid
from pathlib import Path

import pytest

from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventType,
    ExecutionStrategy,
    Manifest,
    ModelTier,
    PolicyRef,
    RecipeRef,
)
from foxhound.observer.store import (
    ARTIFACT_RETENTION_DEFAULTS,
    ObserverStore,
    RetentionClass,
)
from foxhound.storage.database import Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(source_module="test")


@pytest.fixture
def artifacts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir()
    return d


@pytest.fixture
def observer(db: Database, event_bus: EventBus, artifacts_dir: Path) -> ObserverStore:
    return ObserverStore(db=db, event_bus=event_bus, artifacts_dir=artifacts_dir)


@pytest.fixture
def sample_manifest() -> Manifest:
    return Manifest(
        manifest_id=f"mfst_{uuid.uuid4().hex[:12]}",
        run_id="run_001",
        work_item_id="wi_001",
        repo_id="repo_001",
        recipe_ref=RecipeRef(
            name="test_recipe", version="1.0.0", content_hash="abc123"
        ),
        policy_ref=PolicyRef(
            name="test_policy", version="1.0.0", content_hash="def456"
        ),
        context_pack_hash="ctx_hash_001",
        execution_environment_fingerprint="env_fp_001",
        execution_strategy=ExecutionStrategy.ONE_SHOT,
        model_provider="anthropic",
        model_tier=ModelTier.BALANCED,
        workspace_id="ws_001",
    )


class TestObserverStoreInit:
    def test_creates_with_db_only(self, db: Database) -> None:
        store = ObserverStore(db=db)
        assert store.event_count == 0

    def test_creates_with_event_bus(self, db: Database, event_bus: EventBus) -> None:
        store = ObserverStore(db=db, event_bus=event_bus)
        assert store.event_count == 0

    def test_creates_with_artifacts_dir(self, db: Database, artifacts_dir: Path) -> None:
        store = ObserverStore(db=db, artifacts_dir=artifacts_dir)
        assert store.event_count == 0


class TestEventPersistence:
    def test_persists_events_from_bus(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        event_bus.emit(
            EventType.RUN_STARTED,
            source_module="test",
            run_id="run_001",
            repo_id="repo_001",
        )
        assert observer.event_count == 1

    def test_persists_multiple_events(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        for i in range(5):
            event_bus.emit(
                EventType.RUN_STARTED,
                source_module="test",
                run_id=f"run_{i:03d}",
            )
        assert observer.event_count == 5

    def test_get_events_by_run(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        event_bus.emit(
            EventType.RUN_STARTED,
            source_module="test",
            run_id="run_001",
        )
        event_bus.emit(
            EventType.RUN_COMPLETED,
            source_module="test",
            run_id="run_001",
            payload={"duration_seconds": 10.0},
        )
        event_bus.emit(
            EventType.RUN_STARTED,
            source_module="test",
            run_id="run_002",
        )

        events = observer.get_events_by_run("run_001")
        assert len(events) == 2

    def test_get_recent_events(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        for i in range(3):
            event_bus.emit(
                EventType.RUN_STARTED,
                source_module="test",
                run_id=f"run_{i:03d}",
            )
        recent = observer.get_recent_events(limit=2)
        assert len(recent) == 2

    def test_get_recent_events_by_type(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        event_bus.emit(EventType.RUN_STARTED, source_module="test")
        event_bus.emit(EventType.RUN_COMPLETED, source_module="test",
                       payload={"duration_seconds": 1.0})
        event_bus.emit(EventType.RUN_STARTED, source_module="test")

        started = observer.get_recent_events(event_type=EventType.RUN_STARTED)
        assert len(started) == 2

    def test_unsubscribe_stops_persistence(
        self, observer: ObserverStore, event_bus: EventBus
    ) -> None:
        event_bus.emit(EventType.RUN_STARTED, source_module="test")
        assert observer.event_count == 1

        observer.unsubscribe()
        event_bus.emit(EventType.RUN_STARTED, source_module="test")
        assert observer.event_count == 1


class TestManifestRecording:
    def test_record_manifest(
        self, observer: ObserverStore, sample_manifest: Manifest
    ) -> None:
        artifact_id = observer.record_manifest(sample_manifest)
        assert artifact_id.startswith("art_")

    def test_manifest_written_to_filesystem(
        self,
        observer: ObserverStore,
        sample_manifest: Manifest,
        artifacts_dir: Path,
    ) -> None:
        observer.record_manifest(sample_manifest)
        manifest_dir = artifacts_dir / "manifests"
        assert manifest_dir.exists()
        files = list(manifest_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["run_id"] == "run_001"
        assert data["work_item_id"] == "wi_001"

    def test_manifest_indexed_as_class_a(
        self, observer: ObserverStore, sample_manifest: Manifest
    ) -> None:
        artifact_id = observer.record_manifest(sample_manifest)
        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["retention_class"] == "A"
        assert artifact["artifact_type"] == "manifest"

    def test_manifest_without_artifacts_dir(self, db: Database) -> None:
        store = ObserverStore(db=db)
        manifest = Manifest(
            manifest_id="mfst_test",
            run_id="run_001",
            work_item_id="wi_001",
            repo_id="repo_001",
            recipe_ref=RecipeRef(
                name="r", version="1.0.0", content_hash="abc"
            ),
            policy_ref=PolicyRef(
                name="p", version="1.0.0", content_hash="def"
            ),
            context_pack_hash="ctx",
            execution_environment_fingerprint="env",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_provider="test",
            model_tier=ModelTier.FAST,
            workspace_id="ws",
        )
        artifact_id = store.record_manifest(manifest)
        assert artifact_id.startswith("art_")


class TestArtifactIndexing:
    def test_index_artifact(self, observer: ObserverStore) -> None:
        artifact_id = observer.index_artifact(
            run_id="run_001",
            artifact_type="raw_log",
            path="/tmp/log.txt",
            size_bytes=1024,
        )
        assert artifact_id.startswith("art_")

    def test_default_retention_class(self, observer: ObserverStore) -> None:
        artifact_id = observer.index_artifact(
            run_id="run_001",
            artifact_type="raw_log",
            path="/tmp/log.txt",
        )
        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["retention_class"] == "C"

    def test_explicit_retention_class(self, observer: ObserverStore) -> None:
        artifact_id = observer.index_artifact(
            run_id="run_001",
            artifact_type="custom",
            path="/tmp/custom.txt",
            retention_class="A",
        )
        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["retention_class"] == "A"

    def test_pinned_artifact(self, observer: ObserverStore) -> None:
        artifact_id = observer.index_artifact(
            run_id="run_001",
            artifact_type="manifest",
            path="/tmp/m.json",
            pinned=True,
        )
        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["pinned"] == 1

    def test_get_artifacts_by_run(self, observer: ObserverStore) -> None:
        observer.index_artifact("run_001", "raw_log", "/tmp/1.log")
        observer.index_artifact("run_001", "context_pack", "/tmp/ctx.json")
        observer.index_artifact("run_002", "raw_log", "/tmp/2.log")

        artifacts = observer.get_artifacts_by_run("run_001")
        assert len(artifacts) == 2

    def test_pin_unpin(self, observer: ObserverStore) -> None:
        artifact_id = observer.index_artifact(
            "run_001", "raw_log", "/tmp/1.log"
        )
        assert observer.pin_artifact(artifact_id) is True

        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["pinned"] == 1

        assert observer.unpin_artifact(artifact_id) is True
        artifact = observer.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact["pinned"] == 0


class TestStorageStats:
    def test_empty_stats(self, observer: ObserverStore) -> None:
        stats = observer.get_storage_stats()
        assert stats["total_artifacts"] == 0
        assert stats["total_size_bytes"] == 0

    def test_stats_with_artifacts(self, observer: ObserverStore) -> None:
        observer.index_artifact("run_001", "manifest", "/tmp/m.json",
                                size_bytes=500, retention_class="A")
        observer.index_artifact("run_001", "raw_log", "/tmp/l.log",
                                size_bytes=2000, retention_class="C")
        observer.index_artifact("run_001", "context_pack", "/tmp/c.json",
                                size_bytes=1000, retention_class="B")

        stats = observer.get_storage_stats()
        assert stats["total_artifacts"] == 3
        assert stats["total_size_bytes"] == 3500
        assert stats["counts_by_class"]["A"] == 1
        assert stats["counts_by_class"]["C"] == 1
        assert stats["sizes_by_class"]["B"] == 1000


class TestRetentionClassDefaults:
    def test_manifest_is_class_a(self) -> None:
        assert ARTIFACT_RETENTION_DEFAULTS["manifest"] == RetentionClass.A

    def test_context_pack_is_class_b(self) -> None:
        assert ARTIFACT_RETENTION_DEFAULTS["context_pack"] == RetentionClass.B

    def test_raw_log_is_class_c(self) -> None:
        assert ARTIFACT_RETENTION_DEFAULTS["raw_log"] == RetentionClass.C

    def test_run_summary_is_class_a(self) -> None:
        assert ARTIFACT_RETENTION_DEFAULTS["run_summary"] == RetentionClass.A
