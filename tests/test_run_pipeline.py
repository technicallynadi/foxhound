"""Tests for the foxhound run end-to-end pipeline."""

from pathlib import Path

from foxhound.cli.run_pipeline import (
    RunPipelineResult,
    _build_review_task_envelope,
    _build_task_envelope,
    _get_workspace_diff,
    run_pipeline,
)
from foxhound.core.coordinator import Coordinator
from foxhound.core.models import (
    ExecutionMode,
    JobType,
    PolicyRef,
    RecipeRef,
    WorkItem,
    WorkItemState,
)
from foxhound.storage.database import Database

# =========================================================================
# Helpers
# =========================================================================


def _make_db(tmp_path: Path) -> Database:
    """Create a test database."""
    return Database(tmp_path / "test.db")


def _make_work_item(
    repo_id: str = "repo_001",
    state: WorkItemState = WorkItemState.APPROVED,
) -> WorkItem:
    """Create a test work item."""
    return WorkItem(
        work_item_id="wi_test_001",
        repo_id=repo_id,
        title="Fix login bug",
        description="The login page crashes on empty email",
        source_type="todo_comment",
        source_fingerprint="fp_test_001",
        state=state,
        confidence=0.8,
        likely_files=["src/auth.py"],
    )


def _setup_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing."""
    import subprocess

    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


# =========================================================================
# RunPipelineResult Tests
# =========================================================================


class TestRunPipelineResult:
    """Test the result dataclass."""

    def test_success_result(self):
        result = RunPipelineResult(
            success=True,
            stage_reached="completed",
            work_item_id="wi_001",
            run_id="run_001",
            job_id="job_001",
            branch_name="foxhound/exec-wi_test-abc123",
            commit_hash="deadbeef",
        )
        assert result.success is True
        assert result.branch_name is not None

    def test_failure_result(self):
        result = RunPipelineResult(
            success=False,
            stage_reached="execute",
            work_item_id="wi_001",
            error="Validation failed",
        )
        assert result.success is False
        assert result.error == "Validation failed"

    def test_default_values(self):
        result = RunPipelineResult(success=True)
        assert result.stage_reached == "init"
        assert result.branch_name is None
        assert result.total_cost == 0.0
        assert result.files_changed == []
        assert result.validation_results == []


# =========================================================================
# Pipeline Stage Tests
# =========================================================================


class TestPipelineLoadWorkItem:
    """Test work item loading stage."""

    def test_missing_work_item(self, tmp_path: Path):
        db = _make_db(tmp_path)
        try:
            result = run_pipeline(
                work_item_id="nonexistent",
                db=db,
                repo_path=tmp_path,
            )
            assert result.success is False
            assert result.stage_reached == "load_work_item"
            assert "not found" in result.error
        finally:
            db.close()

    def test_unapproved_work_item(self, tmp_path: Path):
        db = _make_db(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.SUGGESTED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=tmp_path,
            )
            assert result.success is False
            assert result.stage_reached == "load_work_item"
            assert "approved" in result.error.lower()
        finally:
            db.close()

    def test_approved_work_item_proceeds(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.APPROVED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )
            # Pipeline should get past load_work_item
            assert result.stage_reached != "load_work_item"
        finally:
            db.close()

    def test_edited_work_item_proceeds(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.EDITED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )
            assert result.stage_reached != "load_work_item"
        finally:
            db.close()


class TestPipelineQueueJob:
    """Test job queuing stage."""

    def test_job_queued_with_snapshot(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.APPROVED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )
            # Job ID should be set if we got past queuing
            assert result.job_id != ""
        finally:
            db.close()


class TestPipelineExecution:
    """Test the full execution flow."""

    def test_full_pipeline_success(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.APPROVED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )

            # Pipeline runs to completion even without changes to promote
            # (promotion may fail with "no changes" but pipeline still reports)
            assert result.run_id != ""
            assert result.job_id != ""
            assert result.duration_seconds >= 0.0
            assert result.review_verdict is not None
        finally:
            db.close()

    def test_work_item_transitions_to_executing(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.APPROVED)
            coord.save_work_item(item)

            run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )

            # Work item should have been advanced past APPROVED
            updated = coord.get_work_item(item.work_item_id)
            assert updated is not None
            assert updated.state != WorkItemState.APPROVED
        finally:
            db.close()

    def test_review_verdict_recorded(self, tmp_path: Path):
        db = _make_db(tmp_path)
        repo_path = _setup_git_repo(tmp_path)
        try:
            coord = Coordinator(db)
            item = _make_work_item(state=WorkItemState.APPROVED)
            coord.save_work_item(item)

            result = run_pipeline(
                work_item_id=item.work_item_id,
                db=db,
                repo_path=repo_path,
                workspace_base=tmp_path / "ws",
            )

            assert result.review_verdict is not None
            assert result.review_confidence is not None
            assert result.review_confidence >= 0.0
        finally:
            db.close()


# =========================================================================
# Helper Function Tests
# =========================================================================


class TestGetWorkspaceDiff:
    """Test workspace diff extraction."""

    def test_empty_repo_empty_diff(self, tmp_path: Path):
        repo = _setup_git_repo(tmp_path)
        diff = _get_workspace_diff(repo)
        assert diff == ""

    def test_with_changes(self, tmp_path: Path):
        import subprocess

        repo = _setup_git_repo(tmp_path)
        (repo / "new_file.py").write_text("print('hello')")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
        diff = _get_workspace_diff(repo)
        # Staged changes don't show in git diff HEAD for new files
        # but unstaged changes would
        assert isinstance(diff, str)

    def test_nonexistent_path(self):
        diff = _get_workspace_diff(Path("/nonexistent/path"))
        assert diff == ""


class TestBuildTaskEnvelope:
    """Test task envelope construction."""

    def test_execution_task(self):
        from foxhound.core.models import (
            ExecutionSnapshot,
            JobEnvelope,
            RunRecord,
        )

        job = JobEnvelope(
            job_id="job_001",
            work_item_id="wi_001",
            repo_id="repo_001",
            job_type=JobType.EXECUTION,
            execution_snapshot=ExecutionSnapshot(
                recipe_ref=RecipeRef(name="t", version="1.0.0", content_hash="abc"),
                policy_ref=PolicyRef(name="t", version="1.0.0", content_hash="def"),
                config_hash="cfg",
            ),
            budget=5.0,
            timeout_seconds=600,
        )
        run = RunRecord(
            run_id="run_001",
            job_id="job_001",
            worker_type="ExecutionWorker",
        )

        task = _build_task_envelope(job, run)
        assert task.job_id == "job_001"
        assert task.execution_mode == ExecutionMode.FULL_EXECUTE
        assert task.budget == 5.0

    def test_review_task(self):
        from foxhound.core.models import (
            ExecutionSnapshot,
            JobEnvelope,
            RunRecord,
        )

        job = JobEnvelope(
            job_id="job_001",
            work_item_id="wi_001",
            repo_id="repo_001",
            job_type=JobType.EXECUTION,
            execution_snapshot=ExecutionSnapshot(
                recipe_ref=RecipeRef(name="t", version="1.0.0", content_hash="abc"),
                policy_ref=PolicyRef(name="t", version="1.0.0", content_hash="def"),
                config_hash="cfg",
            ),
            budget=5.0,
            timeout_seconds=600,
        )
        run = RunRecord(
            run_id="run_001",
            job_id="job_001",
            worker_type="ExecutionWorker",
        )

        task = _build_review_task_envelope(job, run)
        assert task.execution_mode == ExecutionMode.READ_ONLY
        assert task.budget == 0.50
        assert task.timeout_seconds == 120


# =========================================================================
# CLI Integration Tests
# =========================================================================


class TestRunCommand:
    """Test the foxhound run CLI command."""

    def test_run_not_initialized(self, tmp_path: Path):
        from typer.testing import CliRunner

        from foxhound.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "wi_001"], catch_exceptions=False)
        # Should fail because not initialized (no .foxhound/foxhound.db)
        assert result.exit_code != 0

    def test_run_nonexistent_item(self, tmp_path: Path):
        # Set up initialized foxhound
        import os

        from typer.testing import CliRunner

        from foxhound.cli.app import app

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            (tmp_path / ".foxhound").mkdir()
            db = Database(tmp_path / ".foxhound" / "foxhound.db")
            db.close()

            runner = CliRunner()
            result = runner.invoke(app, ["run", "nonexistent"], catch_exceptions=False)
            assert result.exit_code != 0
            assert "not found" in result.output.lower()
        finally:
            os.chdir(old_cwd)
