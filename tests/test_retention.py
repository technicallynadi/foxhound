"""Tests for the retention policy module."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from foxhound.observer.retention import (
    RetentionConfig,
    RetentionPolicy,
)
from foxhound.storage.database import ArtifactStore, Database, EventStore


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def policy(db: Database) -> RetentionPolicy:
    return RetentionPolicy(db)


@pytest.fixture
def artifact_store(db: Database) -> ArtifactStore:
    return ArtifactStore(db)


@pytest.fixture
def event_store(db: Database) -> EventStore:
    return EventStore(db)


class TestRetentionConfig:
    def test_default_values(self) -> None:
        config = RetentionConfig()
        assert config.class_a_days == 180
        assert config.class_b_days == 30
        assert config.class_c_success_days == 21
        assert config.class_c_failure_days == 45

    def test_custom_values(self) -> None:
        config = RetentionConfig(class_a_days=365, class_b_days=60)
        assert config.class_a_days == 365
        assert config.class_b_days == 60


class TestRetentionCutoffs:
    def test_class_a_cutoff(self, policy: RetentionPolicy) -> None:
        now = datetime(2026, 3, 14, tzinfo=UTC)
        cutoff = policy.get_cutoff("A", now=now)
        expected = now - timedelta(days=180)
        assert cutoff == expected

    def test_class_b_cutoff(self, policy: RetentionPolicy) -> None:
        now = datetime(2026, 3, 14, tzinfo=UTC)
        cutoff = policy.get_cutoff("B", now=now)
        expected = now - timedelta(days=30)
        assert cutoff == expected

    def test_class_c_cutoff(self, policy: RetentionPolicy) -> None:
        now = datetime(2026, 3, 14, tzinfo=UTC)
        cutoff = policy.get_cutoff("C", now=now)
        expected = now - timedelta(days=21)
        assert cutoff == expected

    def test_custom_config_cutoff(self, db: Database) -> None:
        config = RetentionConfig(class_a_days=365)
        policy = RetentionPolicy(db, config=config)
        now = datetime(2026, 3, 14, tzinfo=UTC)
        cutoff = policy.get_cutoff("A", now=now)
        expected = now - timedelta(days=365)
        assert cutoff == expected


class TestRetentionStatus:
    def test_empty_status(self, policy: RetentionPolicy) -> None:
        status = policy.get_status()
        assert status["total"]["count"] == 0
        assert status["total"]["size_bytes"] == 0

    def test_status_with_artifacts(
        self, policy: RetentionPolicy, artifact_store: ArtifactStore
    ) -> None:
        artifact_store.save("art_001", "run_001", "manifest", "/tmp/m.json",
                            size_bytes=500, retention_class="A")
        artifact_store.save("art_002", "run_001", "raw_log", "/tmp/l.log",
                            size_bytes=2000, retention_class="C")

        status = policy.get_status()
        assert status["A"]["count"] == 1
        assert status["A"]["size_bytes"] == 500
        assert status["C"]["count"] == 1
        assert status["C"]["size_bytes"] == 2000
        assert status["total"]["count"] == 2


class TestFindExpired:
    def test_finds_old_artifacts(
        self, policy: RetentionPolicy, db: Database
    ) -> None:
        # Insert an artifact with old timestamp directly
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("art_old", "run_old", "manifest", "/tmp/old.json",
                 100, "A", 0, old_date),
            )
            conn.commit()

        expired = policy.find_expired("A")
        assert len(expired) == 1
        assert expired[0]["artifact_id"] == "art_old"

    def test_skips_recent_artifacts(
        self, policy: RetentionPolicy, artifact_store: ArtifactStore
    ) -> None:
        artifact_store.save("art_new", "run_new", "manifest", "/tmp/new.json",
                            retention_class="A")
        expired = policy.find_expired("A")
        assert len(expired) == 0

    def test_skips_pinned_artifacts(
        self, policy: RetentionPolicy, db: Database
    ) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("art_pinned", "run_old", "manifest", "/tmp/pinned.json",
                 100, "A", 1, old_date),
            )
            conn.commit()

        expired = policy.find_expired("A")
        assert len(expired) == 0


class TestPruning:
    def test_prune_removes_expired(
        self, policy: RetentionPolicy, db: Database
    ) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("art_expired", "run_old", "manifest", "/tmp/nonexistent.json",
                 500, "A", 0, old_date),
            )
            conn.commit()

        result = policy.prune()
        assert result.artifacts_removed == 1
        assert result.bytes_freed == 500

    def test_prune_deletes_filesystem_files(
        self, policy: RetentionPolicy, db: Database, tmp_path: Path
    ) -> None:
        # Create actual file
        test_file = tmp_path / "to_delete.json"
        test_file.write_text("{}")
        assert test_file.exists()

        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("art_file", "run_old", "manifest", str(test_file),
                 100, "A", 0, old_date),
            )
            conn.commit()

        result = policy.prune()
        assert result.files_deleted == 1
        assert not test_file.exists()

    def test_prune_empty_returns_zero(self, policy: RetentionPolicy) -> None:
        result = policy.prune()
        assert result.artifacts_removed == 0
        assert result.bytes_freed == 0

    def test_prune_preserves_pinned(
        self, policy: RetentionPolicy, db: Database
    ) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("art_pinned", "run_old", "manifest", "/tmp/pinned.json",
                 100, "A", 1, old_date),
            )
            conn.commit()

        result = policy.prune()
        assert result.artifacts_removed == 0


class TestCompaction:
    def test_compact_removes_old_detail_events(
        self, policy: RetentionPolicy, db: Database
    ) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        with db.connection() as conn:
            # Old detail event (should be compacted)
            conn.execute(
                """
                INSERT INTO events (event_id, event_type, severity, payload_json, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("evt_old_detail", "EvaluationStarted", "info", "{}", old_date),
            )
            # Old summary event (should be kept)
            conn.execute(
                """
                INSERT INTO events (event_id, event_type, severity, payload_json, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("evt_old_summary", "RunCompleted", "info", "{}", old_date),
            )
            # Recent detail event (should be kept)
            conn.execute(
                """
                INSERT INTO events (event_id, event_type, severity, payload_json, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("evt_recent", "EvaluationStarted", "info", "{}",
                 datetime.now(UTC).isoformat()),
            )
            conn.commit()

        result = policy.compact_events(older_than_days=30)
        assert result.events_compacted == 1

        # Verify kept events
        with db.connection() as conn:
            remaining = conn.execute("SELECT event_id FROM events").fetchall()
        remaining_ids = {r["event_id"] for r in remaining}
        assert "evt_old_summary" in remaining_ids
        assert "evt_recent" in remaining_ids
        assert "evt_old_detail" not in remaining_ids


class TestPinUnpin:
    def test_pin_artifact(
        self, policy: RetentionPolicy, artifact_store: ArtifactStore
    ) -> None:
        artifact_store.save("art_001", "run_001", "log", "/tmp/l.log")
        assert policy.pin_artifact("art_001") is True

        art = artifact_store.get("art_001")
        assert art is not None
        assert art["pinned"] == 1

    def test_unpin_artifact(
        self, policy: RetentionPolicy, artifact_store: ArtifactStore
    ) -> None:
        artifact_store.save("art_001", "run_001", "log", "/tmp/l.log", pinned=True)
        assert policy.unpin_artifact("art_001") is True

        art = artifact_store.get("art_001")
        assert art is not None
        assert art["pinned"] == 0
