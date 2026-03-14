"""Tests for the workspace manager."""

import subprocess
from pathlib import Path

import pytest

from foxhound.execution.workspace import (
    RepoSnapshot,
    Workspace,
    WorkspaceError,
    WorkspaceManager,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_dir, capture_output=True, check=True,
    )

    (repo_dir / "README.md").write_text("# Test Repo\n")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    return repo_dir


@pytest.fixture
def workspace_manager(tmp_path: Path) -> WorkspaceManager:
    """Create a workspace manager with a test base directory."""
    return WorkspaceManager(base_dir=tmp_path / "workspaces")


class TestWorkspaceManager:
    """Tests for WorkspaceManager."""

    def test_create_workspace(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test creating an isolated workspace."""
        ws = workspace_manager.create(git_repo)

        assert ws.workspace_id
        assert ws.workspace_path.exists()
        assert ws.created
        assert ws.repo_snapshot.repo_path == str(git_repo)
        assert ws.repo_snapshot.commit_hash
        assert not ws.repo_snapshot.is_dirty

        assert (ws.workspace_path / "README.md").exists()
        assert (ws.workspace_path / "src" / "main.py").exists()

    def test_create_workspace_nonexistent_repo(
        self, workspace_manager: WorkspaceManager, tmp_path: Path
    ) -> None:
        """Test creating workspace from nonexistent repo raises error."""
        with pytest.raises(WorkspaceError, match="Source repo not found"):
            workspace_manager.create(tmp_path / "nonexistent")

    def test_destroy_workspace(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test destroying a workspace."""
        ws = workspace_manager.create(git_repo)
        ws_path = ws.workspace_path
        assert ws_path.exists()

        result = workspace_manager.destroy(ws.workspace_id)
        assert result is True
        assert not ws_path.exists()

    def test_destroy_nonexistent_workspace(
        self, workspace_manager: WorkspaceManager
    ) -> None:
        """Test destroying a nonexistent workspace returns False."""
        result = workspace_manager.destroy("nonexistent-id")
        assert result is False

    def test_get_workspace(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test getting an active workspace."""
        ws = workspace_manager.create(git_repo)
        retrieved = workspace_manager.get(ws.workspace_id)
        assert retrieved is not None
        assert retrieved.workspace_id == ws.workspace_id

    def test_get_nonexistent_workspace(
        self, workspace_manager: WorkspaceManager
    ) -> None:
        """Test getting a nonexistent workspace returns None."""
        assert workspace_manager.get("nonexistent") is None

    def test_list_active_workspaces(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test listing active workspaces."""
        assert len(workspace_manager.list_active()) == 0

        ws1 = workspace_manager.create(git_repo)
        ws2 = workspace_manager.create(git_repo)
        assert len(workspace_manager.list_active()) == 2

        workspace_manager.destroy(ws1.workspace_id)
        active = workspace_manager.list_active()
        assert len(active) == 1
        assert active[0].workspace_id == ws2.workspace_id

    def test_cleanup_all(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test cleaning up all workspaces."""
        workspace_manager.create(git_repo)
        workspace_manager.create(git_repo)
        assert len(workspace_manager.list_active()) == 2

        count = workspace_manager.cleanup_all()
        assert count == 2
        assert len(workspace_manager.list_active()) == 0

    def test_workspace_isolation(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test that workspace changes don't affect the source repo."""
        ws = workspace_manager.create(git_repo)

        new_file = ws.workspace_path / "new_file.py"
        new_file.write_text("# new content\n")

        assert not (git_repo / "new_file.py").exists()

    def test_repo_snapshot_captures_state(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test that repo snapshot captures current state."""
        ws = workspace_manager.create(git_repo)
        snapshot = ws.repo_snapshot

        assert snapshot.branch in ("main", "master")
        assert len(snapshot.commit_hash) == 40
        assert snapshot.is_dirty is False

    def test_dirty_repo_snapshot(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test that dirty state is captured in snapshot."""
        (git_repo / "uncommitted.txt").write_text("dirty\n")
        ws = workspace_manager.create(git_repo)
        assert ws.repo_snapshot.is_dirty is True

    def test_multiple_concurrent_workspaces(
        self, workspace_manager: WorkspaceManager, git_repo: Path
    ) -> None:
        """Test creating multiple workspaces from the same repo."""
        ws1 = workspace_manager.create(git_repo)
        ws2 = workspace_manager.create(git_repo)

        assert ws1.workspace_id != ws2.workspace_id
        assert ws1.workspace_path != ws2.workspace_path
        assert ws1.exists()
        assert ws2.exists()

        (ws1.workspace_path / "ws1_file.txt").write_text("ws1\n")
        assert not (ws2.workspace_path / "ws1_file.txt").exists()


class TestRepoSnapshot:
    """Tests for RepoSnapshot."""

    def test_snapshot_fields(self) -> None:
        """Test snapshot is a frozen dataclass."""
        snapshot = RepoSnapshot(
            repo_path="/test",
            branch="main",
            commit_hash="abc123",
            remote_url=None,
            is_dirty=False,
        )
        assert snapshot.repo_path == "/test"
        assert snapshot.branch == "main"
        assert snapshot.remote_url is None


class TestWorkspace:
    """Tests for Workspace."""

    def test_exists(self, tmp_path: Path) -> None:
        """Test workspace exists check."""
        ws = Workspace(
            workspace_id="test",
            workspace_path=tmp_path,
            repo_snapshot=RepoSnapshot(
                repo_path="/test", branch="main",
                commit_hash="abc", remote_url=None, is_dirty=False,
            ),
        )
        assert ws.exists()

    def test_not_exists(self) -> None:
        """Test workspace exists returns False for missing path."""
        ws = Workspace(
            workspace_id="test",
            workspace_path=Path("/nonexistent/path"),
            repo_snapshot=RepoSnapshot(
                repo_path="/test", branch="main",
                commit_hash="abc", remote_url=None, is_dirty=False,
            ),
        )
        assert not ws.exists()
