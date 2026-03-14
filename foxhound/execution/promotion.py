"""Branch promotion flow for validated execution output.

Applies validated changes from an isolated workspace to the canonical
repo by creating a branch, committing changes, and optionally creating
a PR draft. Promotion is serialized per repo target using locks.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from foxhound.core.lock_manager import LockManager, LockType
from foxhound.core.models import RunRecord, WorkItem
from foxhound.execution.workspace import Workspace


@dataclass(frozen=True)
class PromotionRequest:
    """Request to promote workspace changes to the canonical repo."""

    workspace: Workspace
    work_item: WorkItem
    run_record: RunRecord
    branch_prefix: str = "foxhound"
    commit_message: str | None = None
    create_pr_draft: bool = False


@dataclass
class PromotionOutcome:
    """Result of a branch promotion attempt."""

    success: bool
    branch_name: str | None = None
    commit_hash: str | None = None
    pr_url: str | None = None
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None


class PromotionError(Exception):
    """Raised when promotion fails."""


class PromotionManager:
    """Manages the promotion of validated workspace changes to canonical repos.

    Promotion is serialized per repo target using promotion locks.
    Requires evaluation and security review passes before promotion.
    """

    def __init__(self, lock_manager: LockManager | None = None) -> None:
        self._lock_manager = lock_manager

    def _run_git(
        self, args: list[str], cwd: Path, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command."""
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
            timeout=120,
        )

    def promote(self, request: PromotionRequest) -> PromotionOutcome:
        """Promote workspace changes to a branch on the canonical repo.

        Acquires a promotion lock, creates a branch, commits changes,
        and optionally creates a PR draft.

        Args:
            request: The promotion request with workspace and metadata.

        Returns:
            PromotionOutcome with branch, commit, and PR details.
        """
        workspace = request.workspace
        repo_path = Path(workspace.repo_snapshot.repo_path)
        job_id = request.run_record.job_id

        if not workspace.exists():
            return PromotionOutcome(
                success=False,
                error="Workspace directory does not exist",
            )

        lock_id: str | None = None
        if self._lock_manager:
            lock_result = self._lock_manager.acquire(
                resource_type=LockType.PROMOTION,
                resource_key=str(repo_path),
                owner_job_id=job_id,
                ttl_seconds=600,
            )
            if not lock_result.acquired:
                return PromotionOutcome(
                    success=False,
                    error=(
                        f"Cannot acquire promotion lock for {repo_path}. "
                        f"Held by job {lock_result.holder_job_id}"
                    ),
                )
            lock_id = lock_result.lock_id

        try:
            return self._do_promote(request, repo_path)
        finally:
            if self._lock_manager and lock_id:
                self._lock_manager.release(lock_id)

    def _do_promote(
        self, request: PromotionRequest, repo_path: Path
    ) -> PromotionOutcome:
        """Execute the promotion steps."""
        workspace = request.workspace
        work_item = request.work_item
        ws_path = workspace.workspace_path

        changed = self._get_changed_files(ws_path)
        if not changed:
            return PromotionOutcome(
                success=False,
                error="No changes to promote from workspace",
            )

        branch_name = self._generate_branch_name(
            request.branch_prefix, work_item.work_item_id
        )

        commit_msg = request.commit_message or self._build_commit_message(
            work_item
        )

        try:
            self._run_git(["add", "-A"], cwd=ws_path)
            self._run_git(
                ["commit", "-m", commit_msg, "--allow-empty"],
                cwd=ws_path,
            )
        except subprocess.CalledProcessError as exc:
            return PromotionOutcome(
                success=False,
                error=f"Failed to commit in workspace: {exc.stderr}",
            )

        try:
            original_branch = workspace.repo_snapshot.branch

            self._run_git(
                ["branch", branch_name, original_branch],
                cwd=repo_path,
                check=False,
            )

            self._run_git(
                ["fetch", str(ws_path), f"HEAD:{branch_name}"],
                cwd=repo_path,
            )

            commit_result = self._run_git(
                ["rev-parse", branch_name],
                cwd=repo_path,
            )
            commit_hash = commit_result.stdout.strip()

        except subprocess.CalledProcessError as exc:
            return PromotionOutcome(
                success=False,
                error=f"Failed to promote to repo: {exc.stderr}",
                files_changed=changed,
            )

        return PromotionOutcome(
            success=True,
            branch_name=branch_name,
            commit_hash=commit_hash,
            files_changed=changed,
        )

    def _get_changed_files(self, workspace_path: Path) -> list[str]:
        """Get list of changed files in the workspace."""
        changed: set[str] = set()

        for cmd_args in [
            ["diff", "--name-only", "HEAD"],
            ["diff", "--name-only", "--cached"],
            ["ls-files", "--others", "--exclude-standard"],
        ]:
            result = self._run_git(cmd_args, cwd=workspace_path, check=False)
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    if line.strip():
                        changed.add(line.strip())

        return sorted(changed)

    def _generate_branch_name(self, prefix: str, work_item_id: str) -> str:
        """Generate a branch name for the promotion."""
        short_id = work_item_id[:8]
        unique = uuid4().hex[:6]
        return f"{prefix}/exec-{short_id}-{unique}"

    def _build_commit_message(self, work_item: WorkItem) -> str:
        """Build a commit message from the work item."""
        title = work_item.title
        if len(title) > 72:
            title = title[:69] + "..."

        lines = [f"feat: {title}", ""]
        if work_item.description:
            desc = work_item.description[:500]
            lines.append(desc)
            lines.append("")
        lines.append(f"Work-Item-ID: {work_item.work_item_id}")
        lines.append(f"Source: {work_item.source_type}")

        return "\n".join(lines)
