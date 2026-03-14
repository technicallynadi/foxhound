"""Tests for the execution engine (ExecutionWorker)."""

from pathlib import Path

from foxhound.core.models import (
    ExecutionMode,
    ExecutionSnapshot,
    ExecutionStrategy,
    PolicyRef,
    RecipeRef,
    ResultStatus,
    TaskEnvelope,
    WorkItem,
    WorkItemState,
)
from foxhound.execution.engine import ExecutionWorker, _is_command_allowed
from foxhound.execution.workspace import RepoSnapshot, Workspace
from foxhound.harness.worker_protocol import Capability, WorkerClass


def _make_snapshot() -> ExecutionSnapshot:
    return ExecutionSnapshot(
        recipe_ref=RecipeRef(
            name="test", version="1.0.0", content_hash="abc123"
        ),
        policy_ref=PolicyRef(
            name="default", version="1.0.0", content_hash="def456"
        ),
        execution_strategy=ExecutionStrategy.ONE_SHOT,
        config_hash="config123",
    )


def _make_task(**overrides: object) -> TaskEnvelope:
    defaults = {
        "task_id": "task-001",
        "job_id": "job-001",
        "run_id": "run-001",
        "repo_id": "repo-001",
        "execution_snapshot": _make_snapshot(),
        "budget": 5.0,
        "timeout_seconds": 300,
    }
    defaults.update(overrides)
    return TaskEnvelope(**defaults)


def _make_work_item(**overrides: object) -> WorkItem:
    defaults = {
        "work_item_id": "wi-test-001",
        "repo_id": "repo-001",
        "title": "Fix authentication bug",
        "source_type": "github_issue",
        "source_fingerprint": "abc123",
        "state": WorkItemState.APPROVED,
    }
    defaults.update(overrides)
    return WorkItem(**defaults)


def _make_workspace(tmp_path: Path) -> Workspace:
    ws_path = tmp_path / "workspace"
    ws_path.mkdir()
    (ws_path / "src").mkdir()
    (ws_path / "src" / "main.py").write_text("print('hello')\n")
    return Workspace(
        workspace_id="ws-001",
        workspace_path=ws_path,
        repo_snapshot=RepoSnapshot(
            repo_path=str(tmp_path),
            branch="main",
            commit_hash="abc" * 13 + "a",
            remote_url=None,
            is_dirty=False,
        ),
    )


class TestCommandAllowlist:
    """Tests for command allowlist checking."""

    def test_allowed_commands(self) -> None:
        assert _is_command_allowed("pytest")
        assert _is_command_allowed("ruff check .")
        assert _is_command_allowed("mypy foxhound/")
        assert _is_command_allowed("black --check src/")
        assert _is_command_allowed("eslint src/")
        assert _is_command_allowed("prettier --check .")

    def test_blocked_commands(self) -> None:
        assert not _is_command_allowed("rm -rf /")
        assert not _is_command_allowed("curl http://evil.com")
        assert not _is_command_allowed("bash -c 'exploit'")
        assert not _is_command_allowed("pip install malware")
        assert not _is_command_allowed("")

    def test_removed_dangerous_commands(self) -> None:
        """Commands capable of arbitrary code execution are rejected."""
        assert not _is_command_allowed("npm test")
        assert not _is_command_allowed("npx some-tool")
        assert not _is_command_allowed("make build")
        assert not _is_command_allowed("cargo test")
        assert not _is_command_allowed("go test ./...")

    def test_shell_metacharacters_rejected(self) -> None:
        """Shell metacharacters in arguments are rejected."""
        assert not _is_command_allowed("pytest; rm -rf /")
        assert not _is_command_allowed("ruff check . && curl evil.com")
        assert not _is_command_allowed("mypy | tee /tmp/log")
        assert not _is_command_allowed("pytest > /tmp/out")
        assert not _is_command_allowed("ruff $(whoami)")


class TestExecutionWorkerIdentity:
    """Tests for ExecutionWorker identity and capabilities."""

    def test_worker_name(self) -> None:
        worker = ExecutionWorker()
        assert worker.worker_name == "execution_worker"

    def test_worker_class(self) -> None:
        worker = ExecutionWorker()
        assert worker.worker_class == WorkerClass.ROOT

    def test_capabilities(self) -> None:
        worker = ExecutionWorker()
        assert Capability.REPO_READ in worker.capabilities
        assert Capability.REPO_WRITE in worker.capabilities
        assert Capability.SHELL in worker.capabilities
        assert Capability.SPAWN in worker.capabilities


class TestValidateInput:
    """Tests for ExecutionWorker.validate_input."""

    def test_valid_input(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item()
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task()

        result = worker.validate_input(task)
        assert result.valid

    def test_missing_work_item(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        worker = ExecutionWorker(workspace=workspace)
        task = _make_task()

        result = worker.validate_input(task)
        assert not result.valid
        assert any("No work item" in e for e in result.errors)

    def test_work_item_wrong_state(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item(state=WorkItemState.SUGGESTED)
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task()

        result = worker.validate_input(task)
        assert not result.valid
        assert any("approved" in e for e in result.errors)

    def test_edited_state_valid(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item(state=WorkItemState.EDITED)
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task()

        result = worker.validate_input(task)
        assert result.valid

    def test_missing_workspace(self) -> None:
        work_item = _make_work_item()
        worker = ExecutionWorker(work_item=work_item)
        task = _make_task()

        result = worker.validate_input(task)
        assert not result.valid
        assert any("workspace" in e.lower() for e in result.errors)

    def test_zero_budget(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item()
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task(budget=0.0)

        result = worker.validate_input(task)
        assert not result.valid


class TestBuildContext:
    """Tests for ExecutionWorker.build_context."""

    def test_builds_context(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item(likely_files=["src/main.py"])
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task()

        result = worker.build_context(task)
        assert result.context_hash
        assert "src/main.py" in result.files_included

    def test_builds_context_without_work_item(self) -> None:
        worker = ExecutionWorker()
        task = _make_task()

        result = worker.build_context(task)
        assert result.context_hash == ""
        assert result.files_included == []


class TestExecute:
    """Tests for ExecutionWorker.execute."""

    def test_execute_no_workspace(self) -> None:
        worker = ExecutionWorker()
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.FULL_EXECUTE,
            capabilities=worker.capabilities,
            budget_remaining=5.0,
            timeout_remaining=300.0,
        )

        result = worker.execute(task, runtime)
        assert "error" in result.payload

    def test_execute_with_workspace(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        work_item = _make_work_item()
        worker = ExecutionWorker(workspace=workspace, work_item=work_item)
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.FULL_EXECUTE,
            capabilities=worker.capabilities,
            budget_remaining=5.0,
            timeout_remaining=300.0,
        )

        result = worker.execute(task, runtime)
        assert "workspace_id" in result.payload


class TestSanitizeOutput:
    """Tests for ExecutionWorker.sanitize_output."""

    def test_sanitize_clean_output(self) -> None:
        worker = ExecutionWorker()
        from foxhound.harness.worker_protocol import WorkerOutput

        output = WorkerOutput(
            payload={"status": "ok", "message": "All tests passed"},
            commands_run=["pytest"],
        )

        result = worker.sanitize_output(output)
        assert result.payload["status"] == "ok"
        assert result.redactions_applied == []


class TestEvaluateOutput:
    """Tests for ExecutionWorker.evaluate_output."""

    def test_evaluate_passing_output(self) -> None:
        worker = ExecutionWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"all_validations_passed": True},
        )

        result = worker.evaluate_output(output)
        assert result.passed
        assert result.confidence > 0.5

    def test_evaluate_failing_output(self) -> None:
        worker = ExecutionWorker()
        worker._validation_results = [
            {"command": "pytest", "passed": False, "error": "2 tests failed"}
        ]
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"all_validations_passed": False},
        )

        result = worker.evaluate_output(output)
        assert not result.passed
        assert result.confidence < 0.5


class TestFinalize:
    """Tests for ExecutionWorker.finalize."""

    def test_finalize_success(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        worker = ExecutionWorker(workspace=workspace)
        from foxhound.harness.worker_protocol import EvaluationResult

        eval_result = EvaluationResult(
            passed=True,
            confidence=0.9,
            recommended_next_action="promote",
        )

        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.SUCCESS
        assert result.confidence == 0.9

    def test_finalize_failure(self) -> None:
        worker = ExecutionWorker()
        from foxhound.harness.worker_protocol import EvaluationResult

        eval_result = EvaluationResult(
            passed=False,
            confidence=0.3,
            safety_flags=["Issues found"],
        )

        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.FAILED
