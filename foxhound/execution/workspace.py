"""Workspace manager for isolated execution environments.

Creates and destroys temporary workspaces by cloning the target repo.
Execution never happens in the live repo — only in isolated clones
that can be promoted back after validation.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from foxhound.core.lock_manager import LockManager, LockType


@dataclass(frozen=True)
class RepoSnapshot:
    """Captured metadata about the source repo at workspace creation time."""

    repo_path: str
    branch: str
    commit_hash: str
    remote_url: str | None
    is_dirty: bool


@dataclass
class Workspace:
    """An isolated temporary workspace for execution."""

    workspace_id: str
    workspace_path: Path
    repo_snapshot: RepoSnapshot
    created: bool = True

    def exists(self) -> bool:
        """Check if the workspace directory still exists."""
        return self.workspace_path.exists()


@dataclass
class PromotionResult:
    """Result of promoting workspace changes to the canonical repo."""

    success: bool
    branch_name: str | None = None
    commit_hash: str | None = None
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None


class WorkspaceError(Exception):
    """Raised when workspace operations fail."""


class WorkspaceManager:
    """Creates and destroys isolated temp workspaces for execution.

    Manages the lifecycle: Create -> Execute -> Validate -> Promote or Destroy.
    Workspaces are cloned copies of the target repo in temp directories.
    """

    def __init__(
        self,
        lock_manager: LockManager | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._lock_manager = lock_manager
        self._base_dir = base_dir or Path(tempfile.gettempdir()) / "foxhound-workspaces"
        self._active: dict[str, Workspace] = {}

    def _run_git(
        self, args: list[str], cwd: Path, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command in a directory."""
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
            timeout=120,
        )

    def _snapshot_repo(self, repo_path: Path) -> RepoSnapshot:
        """Capture metadata about the source repo."""
        branch_result = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path
        )
        branch = branch_result.stdout.strip()

        commit_result = self._run_git(
            ["rev-parse", "HEAD"], cwd=repo_path
        )
        commit_hash = commit_result.stdout.strip()

        remote_result = self._run_git(
            ["remote", "get-url", "origin"], cwd=repo_path, check=False
        )
        remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None

        status_result = self._run_git(
            ["status", "--porcelain"], cwd=repo_path
        )
        is_dirty = bool(status_result.stdout.strip())

        return RepoSnapshot(
            repo_path=str(repo_path),
            branch=branch,
            commit_hash=commit_hash,
            remote_url=remote_url,
            is_dirty=is_dirty,
        )

    def create(
        self, repo_path: Path, job_id: str | None = None
    ) -> Workspace:
        """Create an isolated workspace by cloning the repo.

        Args:
            repo_path: Path to the source repository.
            job_id: Optional job ID for lock acquisition.

        Returns:
            A Workspace with the cloned repo ready for execution.

        Raises:
            WorkspaceError: If cloning fails or lock cannot be acquired.
        """
        if not repo_path.exists():
            raise WorkspaceError(f"Source repo not found: {repo_path}")

        workspace_id = str(uuid4())

        if self._lock_manager and job_id:
            lock_result = self._lock_manager.acquire(
                resource_type=LockType.WORKSPACE,
                resource_key=workspace_id,
                owner_job_id=job_id,
                ttl_seconds=3600,
            )
            if not lock_result.acquired:
                raise WorkspaceError(
                    f"Failed to acquire workspace lock for {workspace_id}"
                )

        snapshot = self._snapshot_repo(repo_path)

        self._base_dir.mkdir(parents=True, exist_ok=True)
        workspace_path = self._base_dir / workspace_id

        try:
            self._run_git(
                ["clone", "--local", "--no-hardlinks", str(repo_path), str(workspace_path)],
                cwd=repo_path.parent,
            )
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError(
                f"Failed to clone repo: {exc.stderr}"
            ) from exc

        workspace = Workspace(
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            repo_snapshot=snapshot,
        )
        self._active[workspace_id] = workspace
        return workspace

    def destroy(self, workspace_id: str) -> bool:
        """Destroy a workspace and release its lock.

        Args:
            workspace_id: The workspace to destroy.

        Returns:
            True if the workspace was destroyed.
        """
        workspace = self._active.pop(workspace_id, None)
        if workspace is None:
            return False

        if workspace.workspace_path.exists():
            shutil.rmtree(workspace.workspace_path, ignore_errors=True)

        if self._lock_manager:
            self._lock_manager.release_by_owner(workspace_id)

        return True

    def promote(
        self,
        workspace_id: str,
        branch_name: str,
        commit_message: str,
        job_id: str | None = None,
    ) -> PromotionResult:
        """Promote validated workspace changes to the canonical repo.

        Creates a branch on the source repo with the workspace changes.

        Args:
            workspace_id: The workspace to promote.
            branch_name: Branch name to create on the source repo.
            commit_message: Commit message for the promoted changes.
            job_id: Optional job ID for promotion lock.

        Returns:
            PromotionResult with branch and commit details.
        """
        workspace = self._active.get(workspace_id)
        if workspace is None:
            return PromotionResult(
                success=False, error=f"Workspace {workspace_id} not found"
            )

        repo_path = Path(workspace.repo_snapshot.repo_path)

        if self._lock_manager and job_id:
            lock_result = self._lock_manager.acquire(
                resource_type=LockType.PROMOTION,
                resource_key=str(repo_path),
                owner_job_id=job_id,
                ttl_seconds=600,
            )
            if not lock_result.acquired:
                return PromotionResult(
                    success=False,
                    error=f"Cannot acquire promotion lock for {repo_path}",
                )

        try:
            diff_result = self._run_git(
                ["diff", "--name-only", "HEAD"],
                cwd=workspace.workspace_path,
            )
            staged_result = self._run_git(
                ["diff", "--name-only", "--cached"],
                cwd=workspace.workspace_path,
            )
            untracked_result = self._run_git(
                ["ls-files", "--others", "--exclude-standard"],
                cwd=workspace.workspace_path,
            )

            all_changed = set()
            for output in [diff_result.stdout, staged_result.stdout, untracked_result.stdout]:
                for line in output.strip().splitlines():
                    if line.strip():
                        all_changed.add(line.strip())

            if not all_changed:
                return PromotionResult(
                    success=False,
                    error="No changes to promote",
                )

            files_changed = sorted(all_changed)

            self._run_git(["add", "-A"], cwd=workspace.workspace_path)
            self._run_git(
                ["commit", "-m", commit_message],
                cwd=workspace.workspace_path,
            )

            self._run_git(
                ["checkout", "-b", branch_name],
                cwd=repo_path,
            )

            self._run_git(
                ["fetch", str(workspace.workspace_path), f"HEAD:{branch_name}"],
                cwd=repo_path,
            )
            self._run_git(
                ["checkout", branch_name],
                cwd=repo_path,
            )

            final_commit_result = self._run_git(
                ["rev-parse", "HEAD"],
                cwd=repo_path,
            )
            final_commit = final_commit_result.stdout.strip()

            self._run_git(
                ["checkout", workspace.repo_snapshot.branch],
                cwd=repo_path,
            )

            return PromotionResult(
                success=True,
                branch_name=branch_name,
                commit_hash=final_commit,
                files_changed=files_changed,
            )

        except subprocess.CalledProcessError as exc:
            self._run_git(
                ["checkout", workspace.repo_snapshot.branch],
                cwd=repo_path,
                check=False,
            )
            return PromotionResult(
                success=False,
                error=f"Promotion failed: {exc.stderr}",
            )
        finally:
            if self._lock_manager and job_id:
                self._lock_manager.release_by_owner(job_id)

    def get(self, workspace_id: str) -> Workspace | None:
        """Get an active workspace by ID."""
        return self._active.get(workspace_id)

    def list_active(self) -> list[Workspace]:
        """List all active workspaces."""
        return list(self._active.values())

    def cleanup_all(self) -> int:
        """Destroy all active workspaces. Returns count destroyed."""
        ids = list(self._active.keys())
        count = 0
        for wid in ids:
            if self.destroy(wid):
                count += 1
        return count
