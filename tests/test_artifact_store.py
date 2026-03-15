"""Tests for the ArtifactStore database operations."""

from datetime import UTC, datetime, timedelta

import pytest

from foxhound.storage.database import ArtifactStore, Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def store(db: Database) -> ArtifactStore:
    return ArtifactStore(db)


class TestArtifactStoreCRUD:
    def test_save_and_get(self, store: ArtifactStore) -> None:
        store.save("art_001", "run_001", "manifest", "/tmp/m.json",
                    size_bytes=500, retention_class="A")
        result = store.get("art_001")
        assert result is not None
        assert result["artifact_id"] == "art_001"
        assert result["run_id"] == "run_001"
        assert result["artifact_type"] == "manifest"
        assert result["path"] == "/tmp/m.json"
        assert result["size_bytes"] == 500
        assert result["retention_class"] == "A"
        assert result["pinned"] == 0

    def test_get_nonexistent(self, store: ArtifactStore) -> None:
        assert store.get("nonexistent") is None

    def test_save_with_pinned(self, store: ArtifactStore) -> None:
        store.save("art_p", "run_001", "log", "/tmp/l.log", pinned=True)
        result = store.get("art_p")
        assert result is not None
        assert result["pinned"] == 1

    def test_delete(self, store: ArtifactStore) -> None:
        store.save("art_del", "run_001", "log", "/tmp/d.log")
        assert store.delete("art_del") is True
        assert store.get("art_del") is None

    def test_delete_nonexistent(self, store: ArtifactStore) -> None:
        assert store.delete("nonexistent") is False


class TestArtifactStoreQueries:
    def test_list_by_run(self, store: ArtifactStore) -> None:
        store.save("art_1", "run_001", "manifest", "/tmp/m.json")
        store.save("art_2", "run_001", "log", "/tmp/l.log")
        store.save("art_3", "run_002", "manifest", "/tmp/m2.json")

        artifacts = store.list_by_run("run_001")
        assert len(artifacts) == 2

    def test_list_by_retention_class(self, store: ArtifactStore) -> None:
        store.save("art_a1", "run_001", "manifest", "/tmp/a1.json", retention_class="A")
        store.save("art_a2", "run_002", "summary", "/tmp/a2.json", retention_class="A")
        store.save("art_b1", "run_001", "context", "/tmp/b1.json", retention_class="B")

        class_a = store.list_by_retention_class("A")
        assert len(class_a) == 2
        class_b = store.list_by_retention_class("B")
        assert len(class_b) == 1

    def test_list_unpinned_before(self, store: ArtifactStore, db: Database) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        recent_date = datetime.now(UTC).isoformat()

        with db.connection() as conn:
            conn.execute(
                """INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("art_old", "run_old", "m", "/tmp/old", 100, "A", 0, old_date),
            )
            conn.execute(
                """INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("art_new", "run_new", "m", "/tmp/new", 100, "A", 0, recent_date),
            )
            conn.execute(
                """INSERT INTO artifacts (artifact_id, run_id, artifact_type, path,
                    size_bytes, retention_class, pinned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("art_pinned", "run_old", "m", "/tmp/pinned", 100, "A", 1, old_date),
            )
            conn.commit()

        cutoff = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        expired = store.list_unpinned_before("A", cutoff)
        assert len(expired) == 1
        assert expired[0]["artifact_id"] == "art_old"


class TestArtifactStoreAggregates:
    def test_count_by_class(self, store: ArtifactStore) -> None:
        store.save("a1", "r1", "m", "/tmp/1", retention_class="A")
        store.save("a2", "r1", "m", "/tmp/2", retention_class="A")
        store.save("b1", "r1", "c", "/tmp/3", retention_class="B")
        store.save("c1", "r1", "l", "/tmp/4", retention_class="C")

        counts = store.count_by_class()
        assert counts["A"] == 2
        assert counts["B"] == 1
        assert counts["C"] == 1

    def test_total_size_by_class(self, store: ArtifactStore) -> None:
        store.save("a1", "r1", "m", "/tmp/1", size_bytes=100, retention_class="A")
        store.save("a2", "r1", "m", "/tmp/2", size_bytes=200, retention_class="A")
        store.save("b1", "r1", "c", "/tmp/3", size_bytes=500, retention_class="B")

        sizes = store.total_size_by_class()
        assert sizes["A"] == 300
        assert sizes["B"] == 500

    def test_set_pinned(self, store: ArtifactStore) -> None:
        store.save("art_pin", "r1", "m", "/tmp/m", pinned=False)
        assert store.set_pinned("art_pin", True) is True
        art = store.get("art_pin")
        assert art is not None
        assert art["pinned"] == 1

        assert store.set_pinned("art_pin", False) is True
        art = store.get("art_pin")
        assert art is not None
        assert art["pinned"] == 0

    def test_empty_aggregates(self, store: ArtifactStore) -> None:
        assert store.count_by_class() == {}
        assert store.total_size_by_class() == {}
