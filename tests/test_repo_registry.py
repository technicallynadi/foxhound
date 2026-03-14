"""Tests for the repository registry."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from foxhound.core.repo_registry import (
    RepoInfo,
    RepoRegistry,
    RepoStore,
    _detect_languages,
    _generate_repo_hash,
    _generate_repo_id,
    get_git_root,
    is_git_repo,
)
from foxhound.storage.database import Database


@pytest.fixture()
def db() -> Database:
    return Database(":memory:")


class TestRepoInfo:
    """Test RepoInfo model."""

    def test_create_repo_info(self) -> None:
        repo = RepoInfo(
            repo_id="abc123",
            name="my-repo",
            path="/tmp/my-repo",
        )
        assert repo.repo_id == "abc123"
        assert repo.name == "my-repo"
        assert repo.default_branch == "main"
        assert repo.language_meta == {}

    def test_repo_info_roundtrip(self) -> None:
        repo = RepoInfo(
            repo_id="abc123",
            name="test",
            path="/tmp/test",
            language_meta={"primary": "Python", "files": {"Python": 10}},
        )
        data = repo.model_dump()
        restored = RepoInfo(**data)
        assert restored.repo_id == repo.repo_id
        assert restored.language_meta == repo.language_meta


class TestHelpers:
    """Test helper functions."""

    def test_generate_repo_id_deterministic(self, tmp_path: Path) -> None:
        h1 = _generate_repo_id(tmp_path)
        h2 = _generate_repo_id(tmp_path)
        assert h1 == h2
        assert len(h1) == 16

    def test_generate_repo_hash(self, tmp_path: Path) -> None:
        h = _generate_repo_hash(tmp_path)
        assert len(h) == 12

    def test_detect_languages(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "util.py").write_text("pass")
        (tmp_path / "app.js").write_text("console.log('hi')")

        result = _detect_languages(tmp_path)
        assert result["primary"] == "Python"
        assert result["files"]["Python"] == 2
        assert result["files"]["JavaScript"] == 1

    def test_detect_languages_empty(self, tmp_path: Path) -> None:
        result = _detect_languages(tmp_path)
        assert result["primary"] == "unknown"

    def test_is_git_repo_true(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        assert is_git_repo(tmp_path)

    def test_is_git_repo_false(self, tmp_path: Path) -> None:
        assert not is_git_repo(tmp_path)

    def test_get_git_root(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subdir = tmp_path / "src"
        subdir.mkdir()
        root = get_git_root(subdir)
        assert root == tmp_path

    def test_get_git_root_non_git(self, tmp_path: Path) -> None:
        assert get_git_root(tmp_path) is None


class TestRepoStore:
    """Test repo storage operations."""

    def test_save_and_get(self, db: Database) -> None:
        store = RepoStore(db)
        repo = RepoInfo(
            repo_id="r1",
            name="test-repo",
            path="/tmp/test-repo",
            repo_hash="abc123",
            language_meta={"primary": "Python"},
        )
        store.save(repo)
        result = store.get("r1")
        assert result is not None
        assert result.name == "test-repo"
        assert result.language_meta["primary"] == "Python"

    def test_get_nonexistent(self, db: Database) -> None:
        store = RepoStore(db)
        assert store.get("nope") is None

    def test_get_by_path(self, db: Database) -> None:
        store = RepoStore(db)
        repo = RepoInfo(repo_id="r1", name="test", path="/tmp/test")
        store.save(repo)
        result = store.get_by_path("/tmp/test")
        assert result is not None
        assert result.repo_id == "r1"

    def test_list_all(self, db: Database) -> None:
        store = RepoStore(db)
        store.save(RepoInfo(repo_id="r1", name="alpha", path="/tmp/alpha"))
        store.save(RepoInfo(repo_id="r2", name="beta", path="/tmp/beta"))
        repos = store.list_all()
        assert len(repos) == 2
        assert repos[0].name == "alpha"  # sorted by name

    def test_delete(self, db: Database) -> None:
        store = RepoStore(db)
        store.save(RepoInfo(repo_id="r1", name="test", path="/tmp/test"))
        assert store.delete("r1")
        assert store.get("r1") is None

    def test_delete_nonexistent(self, db: Database) -> None:
        store = RepoStore(db)
        assert not store.delete("nope")


class TestRepoRegistry:
    """Test repo registry operations."""

    def test_register_directory(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        repo = registry.register(tmp_path)
        assert repo.name == tmp_path.name
        assert repo.path == str(tmp_path.resolve())

    def test_register_nonexistent_raises(self, db: Database) -> None:
        registry = RepoRegistry(db)
        with pytest.raises(ValueError, match="not a directory"):
            registry.register(Path("/nonexistent/path"))

    def test_register_idempotent(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        r1 = registry.register(tmp_path)
        r2 = registry.register(tmp_path)
        assert r1.repo_id == r2.repo_id

    def test_list_repos(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        d1 = tmp_path / "repo1"
        d2 = tmp_path / "repo2"
        d1.mkdir()
        d2.mkdir()
        registry.register(d1)
        registry.register(d2)
        repos = registry.list_repos()
        assert len(repos) == 2

    def test_set_active(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        repo = registry.register(tmp_path)
        assert registry.set_active(repo.repo_id)
        assert registry.active_repo_id == repo.repo_id
        assert registry.active_repo is not None
        assert registry.active_repo.name == tmp_path.name

    def test_set_active_nonexistent(self, db: Database) -> None:
        registry = RepoRegistry(db)
        assert not registry.set_active("nope")

    def test_active_repo_initially_none(self, db: Database) -> None:
        registry = RepoRegistry(db)
        assert registry.active_repo_id is None
        assert registry.active_repo is None

    def test_remove(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        repo = registry.register(tmp_path)
        registry.set_active(repo.repo_id)
        assert registry.remove(repo.repo_id)
        assert registry.active_repo_id is None
        assert registry.get(repo.repo_id) is None

    def test_auto_detect_in_git_repo(self, tmp_path: Path, db: Database) -> None:
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        registry = RepoRegistry(db)
        with patch("foxhound.core.repo_registry.Path.cwd", return_value=tmp_path):
            repo = registry.auto_detect()
        assert repo is not None
        assert registry.active_repo_id == repo.repo_id

    def test_auto_detect_not_git(self, tmp_path: Path, db: Database) -> None:
        registry = RepoRegistry(db)
        with patch("foxhound.core.repo_registry.Path.cwd", return_value=tmp_path):
            repo = registry.auto_detect()
        assert repo is None
