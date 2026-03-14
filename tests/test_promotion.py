"""Tests for the branch promotion flow."""

import subprocess
from pathlib import Path

import pytest

from foxhound.core.models import (
    RunRecord,
    RunState,
    WorkItem,
    WorkItemState,
)
from foxhound.execution.promotion import (
    PromotionManager,
    PromotionRequest,
)
from foxhound.execution.workspace import RepoSnapshot, Workspace, WorkspaceManager


def _make_work_item(**overrides: object) -> WorkItem:
    defaults = {
        "work_item_id": "wi-promo-001",
        "repo_id": "repo-001",
        "title": "Add user authentication",
        "description": "Implement login and registration endpoints",
        "source_type": "github_issue",
        "source_fingerprint": "promo123",
        "state": WorkItemState.APPROVED,
    }
    defaults.update(overrides)
    return WorkItem(**defaults)


def _make_run_record(**overrides: object) -> RunRecord:
    defaults = {
        "run_id": "run-promo-001",
        "job_id": "job-promo-001",
        "worker_type": "ExecutionWorker",
        "state": RunState.BRANCH_READY,
    }
    defaults.update(overrides)
    return RunRecord(**defaults)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a git repository for promotion testing."""
    repo_dir = tmp_path / "canonical-repo"
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

    (repo_dir / "README.md").write_text("# Project\n")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "app.py").write_text("# app\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    return repo_dir


@pytest.fixture
def workspace_with_changes(
    git_repo: Path, tmp_path: Path
) -> Workspace:
    """Create a workspace with uncommitted changes."""
    ws_mgr = WorkspaceManager(base_dir=tmp_path / "workspaces")
    ws = ws_mgr.create(git_repo)

    (ws.workspace_path / "src" / "auth.py").write_text(
        "def login(user, password):\n    return True\n"
    )
    (ws.workspace_path / "src" / "app.py").write_text(
        "# app\nfrom src.auth import login\n"
    )

    return ws


class TestPromotionManager:
    """Tests for PromotionManager."""

    def test_promote_creates_branch(
        self, workspace_with_changes: Workspace, git_repo: Path
    ) -> None:
        """Test that promotion creates a branch on the canonical repo."""
        manager = PromotionManager()
        request = PromotionRequest(
            workspace=workspace_with_changes,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
        )

        outcome = manager.promote(request)

        assert outcome.success
        assert outcome.branch_name is not None
        assert outcome.commit_hash is not None
        assert len(outcome.files_changed) > 0
        assert "src/auth.py" in outcome.files_changed

        branches = subprocess.run(
            ["git", "branch", "--list"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        assert outcome.branch_name in branches.stdout

    def test_promote_no_changes(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """Test that promotion fails when there are no changes."""
        ws_mgr = WorkspaceManager(base_dir=tmp_path / "workspaces")
        ws = ws_mgr.create(git_repo)

        manager = PromotionManager()
        request = PromotionRequest(
            workspace=ws,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
        )

        outcome = manager.promote(request)
        assert not outcome.success
        assert "No changes" in (outcome.error or "")

    def test_promote_missing_workspace(self, tmp_path: Path) -> None:
        """Test promotion with a workspace that doesn't exist."""
        ws = Workspace(
            workspace_id="missing",
            workspace_path=tmp_path / "nonexistent",
            repo_snapshot=RepoSnapshot(
                repo_path=str(tmp_path),
                branch="main",
                commit_hash="abc" * 13 + "a",
                remote_url=None,
                is_dirty=False,
            ),
        )

        manager = PromotionManager()
        request = PromotionRequest(
            workspace=ws,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
        )

        outcome = manager.promote(request)
        assert not outcome.success
        assert "does not exist" in (outcome.error or "")

    def test_promote_custom_commit_message(
        self, workspace_with_changes: Workspace
    ) -> None:
        """Test promotion with a custom commit message."""
        manager = PromotionManager()
        request = PromotionRequest(
            workspace=workspace_with_changes,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
            commit_message="fix(auth): implement user login (#42)",
        )

        outcome = manager.promote(request)
        assert outcome.success

    def test_promote_custom_branch_prefix(
        self, workspace_with_changes: Workspace
    ) -> None:
        """Test promotion with a custom branch prefix."""
        manager = PromotionManager()
        request = PromotionRequest(
            workspace=workspace_with_changes,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
            branch_prefix="auto",
        )

        outcome = manager.promote(request)
        assert outcome.success
        assert outcome.branch_name is not None
        assert outcome.branch_name.startswith("auto/")

    def test_promote_records_files_changed(
        self, workspace_with_changes: Workspace
    ) -> None:
        """Test that promotion records which files were changed."""
        manager = PromotionManager()
        request = PromotionRequest(
            workspace=workspace_with_changes,
            work_item=_make_work_item(),
            run_record=_make_run_record(),
        )

        outcome = manager.promote(request)
        assert outcome.success
        assert "src/auth.py" in outcome.files_changed

    def test_commit_message_from_work_item(
        self, workspace_with_changes: Workspace, git_repo: Path
    ) -> None:
        """Test that auto-generated commit message uses work item title."""
        manager = PromotionManager()
        work_item = _make_work_item(title="Add user authentication")
        request = PromotionRequest(
            workspace=workspace_with_changes,
            work_item=work_item,
            run_record=_make_run_record(),
        )

        outcome = manager.promote(request)
        assert outcome.success

        log = subprocess.run(
            ["git", "log", outcome.branch_name, "-1", "--format=%s"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        assert "Add user authentication" in log.stdout
