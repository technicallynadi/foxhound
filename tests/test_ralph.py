"""Tests for Ralph iterative execution strategy."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventType,
    ExecutionStrategy,
    WorkItem,
    WorkItemState,
)
from foxhound.execution.ralph import (
    PROGRESS_FILENAME,
    RALPH_DEFAULT_MAX_ITERATIONS,
    RALPH_DEFAULT_THRESHOLD,
    RALPH_HARD_GLOBAL_MAX_ITERATIONS,
    TASK_STATUS_FILENAME,
    CompletionStatus,
    RalphExecutionStrategy,
    RalphProgress,
    RalphRunResult,
    RalphTask,
    RalphTaskStatus,
    build_iteration_context,
    build_ralph_manifest_fields,
    check_budget_sufficient,
    commit_iteration,
    detect_quality_degradation,
    evaluate_completion,
    load_progress,
    load_task_status,
    save_progress,
    save_task_status,
    select_execution_strategy,
)
from foxhound.recipes.loader import Recipe


def _make_work_item(**overrides: object) -> WorkItem:
    defaults = {
        "work_item_id": "wi-ralph-001",
        "repo_id": "repo-001",
        "title": "Test work item for Ralph",
        "source_type": "ci_failure",
        "source_fingerprint": "fp-ralph-001",
        "state": WorkItemState.APPROVED,
    }
    defaults.update(overrides)
    return WorkItem(**defaults)


def _make_recipe(**overrides: object) -> Recipe:
    defaults = {
        "name": "test_recipe",
        "version": "1.0.0",
        "description": "Test recipe",
        "execution_strategy": "one_shot",
    }
    defaults.update(overrides)
    return Recipe(**defaults)


def _make_tasks(count: int = 3) -> list[RalphTask]:
    return [
        RalphTask(
            task_id=f"task-{i+1:03d}",
            title=f"Task {i+1}",
            description=f"Description for task {i+1}",
        )
        for i in range(count)
    ]


def _make_git_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=workspace, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=workspace, capture_output=True, check=True,
    )
    (workspace / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=workspace, capture_output=True, check=True,
    )
    return workspace


def _make_ralph_run_result(**overrides: object) -> RalphRunResult:
    defaults = {
        "completion_status": CompletionStatus.COMPLETE,
        "iteration_count": 2,
        "max_iterations": 10,
        "total_cost": 1.0,
        "per_iteration_costs": [0.5, 0.5],
        "per_iteration_tasks_completed": [1, 1],
        "commit_refs": ["abc", "def"],
        "progress_file_path": "/tmp/progress.json",
        "tasks_completed": 2,
        "tasks_total": 2,
    }
    defaults.update(overrides)
    return RalphRunResult(**defaults)


def _pre_pass(tasks: list[RalphTask]) -> list[RalphTask]:
    for t in tasks:
        t.status = RalphTaskStatus.PASSED
    return tasks


# =========================================================================
# Ralph Execution Strategy
# =========================================================================


class TestRalphExecutionStrategy:

    def test_ralph_loop_completes_all_tasks(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=5,
            budget=10.0,
        )
        result = strategy.run(_pre_pass(_make_tasks(2)))
        assert result.completion_status == CompletionStatus.COMPLETE

    @pytest.mark.parametrize(
        "budget,max_iter,patch_budget,check_field,check_val",
        [
            (0.0, 10, True, "completion_status", CompletionStatus.PARTIAL),
            (100.0, 2, False, "max_iterations", 2),
        ],
        ids=["budget_exhausted", "max_iterations"],
    )
    def test_ralph_loop_exits_on_limit(
        self, tmp_path: Path, budget: float, max_iter: int,
        patch_budget: bool, check_field: str, check_val: object,
    ) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=max_iter,
            budget=budget,
        )
        ctx = (
            patch("foxhound.execution.ralph.check_budget_sufficient", return_value=False)
            if patch_budget
            else patch("builtins.id", side_effect=lambda x: id(x))
        )
        with ctx:
            result = strategy.run(_make_tasks(3))
        if check_field == "completion_status":
            assert result.completion_status == check_val
        else:
            assert result.iteration_count <= check_val
            assert result.max_iterations == check_val

    def test_hard_global_cap_enforced(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=100,
            budget=100.0,
        )
        assert strategy.max_iterations == RALPH_HARD_GLOBAL_MAX_ITERATIONS

    def test_default_max_iterations(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace, work_item=_make_work_item(),
        )
        assert strategy.max_iterations == RALPH_DEFAULT_MAX_ITERATIONS

    def test_no_conversation_history_between_iterations(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        work_item = _make_work_item()
        build_iteration_context(
            workspace_path=workspace, work_item=work_item,
            recipe=None, progress=None, iteration=1,
        )
        progress = RalphProgress(
            iteration=1, tasks=_make_tasks(2),
            accomplishments=["Iteration 1: completed scaffolding"],
            remaining_work=["Task 2"],
        )
        pack2 = build_iteration_context(
            workspace_path=workspace, work_item=work_item,
            recipe=None, progress=progress, iteration=2,
        )
        assert "progress_notes" in pack2.trust_labels
        assert "conversation_history" not in pack2.evidence

    def test_run_result_fields(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=3,
            budget=5.0,
        )
        result = strategy.run(_pre_pass(_make_tasks(2)))
        assert isinstance(result, RalphRunResult)
        assert result.completion_status in list(CompletionStatus)
        assert result.max_iterations == 3
        assert result.total_cost >= 0
        assert result.duration_seconds >= 0
        assert isinstance(result.per_iteration_costs, list)
        assert isinstance(result.per_iteration_tasks_completed, list)
        assert isinstance(result.commit_refs, list)

    def test_strategy_records_in_execution_snapshot(self) -> None:
        from foxhound.core.models import ExecutionSnapshot, PolicyRef, RecipeRef
        snapshot = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="default", version="1.0.0", content_hash="def"),
            execution_strategy=ExecutionStrategy.RALPH_LOOP,
            config_hash="hash123",
        )
        assert snapshot.execution_strategy == ExecutionStrategy.RALPH_LOOP
        assert snapshot.model_dump()["execution_strategy"] == "ralph_loop"


# =========================================================================
# Progress Persistence
# =========================================================================


class TestProgressPersistence:

    def test_progress_round_trip(self, tmp_path: Path) -> None:
        progress = RalphProgress(
            iteration=1, tasks=_make_tasks(2),
            accomplishments=["Scaffolded project"],
        )
        path = save_progress(progress, tmp_path)
        assert path.exists() and path.name == PROGRESS_FILENAME

        progress.iteration = 2
        progress.accomplishments.append("Completed task 1")
        save_progress(progress, tmp_path)

        loaded = load_progress(tmp_path)
        assert loaded is not None
        assert loaded.iteration == 2
        assert "Completed task 1" in loaded.accomplishments[-1]

    def test_task_status_round_trip(self, tmp_path: Path) -> None:
        tasks = _make_tasks(3)
        tasks[0].status = RalphTaskStatus.PASSED
        tasks[1].status = RalphTaskStatus.FAILED
        tasks[2].status = RalphTaskStatus.PENDING
        save_task_status(tasks, tmp_path)
        loaded = load_task_status(tmp_path)
        assert loaded is not None and len(loaded) == 3
        assert loaded[0].status == RalphTaskStatus.PASSED
        assert loaded[1].status == RalphTaskStatus.FAILED
        assert loaded[2].status == RalphTaskStatus.PENDING

    @pytest.mark.parametrize(
        "loader,filename,content",
        [
            (load_progress, PROGRESS_FILENAME, "{{not valid json"),
            (load_task_status, TASK_STATUS_FILENAME, "not json at all"),
            (load_progress, "nonexistent", None),
        ],
        ids=["corrupted_progress", "corrupted_task_status", "missing_file"],
    )
    def test_corrupted_or_missing_returns_none(
        self, tmp_path: Path, loader: object, filename: str, content: str | None,
    ) -> None:
        if content is not None:
            (tmp_path / filename).write_text(content, encoding="utf-8")
        assert loader(tmp_path) is None

    def test_git_commit_created_after_iteration(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        (workspace / "new_file.py").write_text("# new\n")
        save_progress(RalphProgress(iteration=1, tasks=_make_tasks(1)), workspace)
        sha = commit_iteration(workspace, 1)
        assert sha is not None and len(sha) == 40
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=workspace, capture_output=True, text=True, check=True,
        )
        assert "Ralph iteration 1" in result.stdout

    def test_commit_with_no_changes_returns_none(self, tmp_path: Path) -> None:
        assert commit_iteration(_make_git_workspace(tmp_path), 1) is None

    def test_progress_and_task_status_in_commit(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        save_progress(RalphProgress(iteration=1), workspace)
        save_task_status(_make_tasks(2), workspace)
        sha = commit_iteration(workspace, 1)
        assert sha is not None
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            cwd=workspace, capture_output=True, text=True, check=True,
        )
        files = result.stdout.strip().split("\n")
        assert PROGRESS_FILENAME in files
        assert TASK_STATUS_FILENAME in files

    def test_progress_file_excludes_secrets(self, tmp_path: Path) -> None:
        tasks = [RalphTask(
            task_id="t1",
            title="Task with sk-abcdef12345678901234567890",
            description="Uses AKIA1234567890ABCDEF key",
        )]
        save_progress(RalphProgress(iteration=1, tasks=tasks), tmp_path)
        content = (tmp_path / PROGRESS_FILENAME).read_text()
        assert "sk-abcdef1234" not in content
        assert "AKIA1234567890ABCDEF" not in content


# =========================================================================
# Completion Evaluation
# =========================================================================


class TestCompletionEvaluation:

    @pytest.mark.parametrize(
        "passed_indices,expected_done,expected_completed,expected_remaining",
        [([0, 1, 2], True, 3, 0), ([0], False, 1, 2), ([], False, 0, 3)],
        ids=["all_passed", "one_passed", "none_passed"],
    )
    def test_evaluate_completion(
        self, passed_indices: list[int],
        expected_done: bool, expected_completed: int, expected_remaining: int,
    ) -> None:
        tasks = _make_tasks(3)
        for i in passed_indices:
            tasks[i].status = RalphTaskStatus.PASSED
        all_done, completed, remaining = evaluate_completion(tasks)
        assert (all_done, completed, remaining) == (
            expected_done, expected_completed, expected_remaining,
        )

    @pytest.mark.parametrize(
        "budget,history,expected",
        [
            (0.0, [1.0, 1.0], False),
            (0.5, [1.0, 1.0], False),
            (2.0, [1.0, 1.0], True),
            (1.0, [0.5, 0.5], True),
            (1.0, [], True),
            (0.0, [], False),
        ],
        ids=["zero", "insufficient", "sufficient_2x", "sufficient_1x", "no_hist_pos", "no_hist_zero"],
    )
    def test_check_budget_sufficient(
        self, budget: float, history: list[float], expected: bool,
    ) -> None:
        assert check_budget_sufficient(budget, history) is expected

    @pytest.mark.parametrize(
        "previous,current,expect_degraded",
        [
            (
                [{"command": "pytest", "passed": True}, {"command": "ruff check .", "passed": True}],
                [{"command": "pytest", "passed": False}, {"command": "ruff check .", "passed": True}],
                True,
            ),
            (
                [{"command": "pytest", "passed": False}, {"command": "ruff check .", "passed": True}],
                [{"command": "pytest", "passed": False}, {"command": "ruff check .", "passed": False}],
                True,
            ),
            (
                [{"command": "pytest", "passed": False}, {"command": "ruff", "passed": False}],
                [{"command": "pytest", "passed": True}, {"command": "ruff", "passed": False}],
                False,
            ),
            ([], [{"command": "pytest", "passed": False}], False),
        ],
        ids=["regression", "increasing_failures", "improving", "first_iteration"],
    )
    def test_detect_quality_degradation(
        self, previous: list[dict], current: list[dict], expect_degraded: bool,
    ) -> None:
        degraded, reason = detect_quality_degradation(current, previous)
        assert degraded is expect_degraded
        if expect_degraded:
            assert reason is not None
        else:
            assert reason is None or reason == ""

    def test_completion_status_failed_on_degradation(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        tasks = _make_tasks(2)
        tasks[0].validation_commands = ["pytest"]
        tasks[1].validation_commands = ["mypy"]

        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            recipe=_make_recipe(
                validation={"commands": ["pytest", "mypy"], "require_all_pass": True},
            ),
            max_iterations=5, budget=10.0,
        )
        iteration = 0

        def mock_run_validation(cmd: str, cwd: Path) -> dict:
            nonlocal iteration
            if cmd == "pytest":
                return {"command": cmd, "passed": iteration == 0}
            if cmd == "mypy":
                iteration += 1
                return {"command": cmd, "passed": False}
            return {"command": cmd, "passed": False}

        with patch(
            "foxhound.execution.ralph._run_validation_command",
            side_effect=mock_run_validation,
        ):
            result = strategy.run(tasks)

        assert result.completion_status == CompletionStatus.FAILED
        assert result.degradation_detected is True
        assert result.degradation_reason is not None


# =========================================================================
# Strategy Selection
# =========================================================================


class TestStrategySelection:

    @pytest.mark.parametrize(
        "strategy_str,task_count,kwargs,expected",
        [
            ("one_shot", 5, {}, ExecutionStrategy.RALPH_LOOP),
            ("one_shot", 2, {}, ExecutionStrategy.BOUNDED_RETRY),
            ("one_shot", 1, {}, ExecutionStrategy.ONE_SHOT),
            ("ralph_loop", 1, {}, ExecutionStrategy.RALPH_LOOP),
            ("bounded_retry", 10, {}, ExecutionStrategy.BOUNDED_RETRY),
            ("one_shot", 5, {"ralph_threshold": 10}, ExecutionStrategy.BOUNDED_RETRY),
        ],
        ids=[
            "above_threshold_ralph",
            "below_threshold_bounded",
            "single_one_shot",
            "explicit_ralph",
            "explicit_bounded",
            "custom_threshold",
        ],
    )
    def test_strategy_selection(
        self, strategy_str: str, task_count: int,
        kwargs: dict, expected: ExecutionStrategy,
    ) -> None:
        recipe = _make_recipe(execution_strategy=strategy_str, **kwargs)
        result = select_execution_strategy(
            recipe=recipe, task_count=task_count, budget=10.0, is_isolated=True,
        )
        assert result == expected

    def test_global_ralph_threshold_override(self) -> None:
        recipe = _make_recipe(execution_strategy="one_shot", ralph_threshold=3)
        strategy = select_execution_strategy(
            recipe=recipe, task_count=5, budget=10.0,
            is_isolated=True, global_ralph_threshold=10,
        )
        assert strategy == ExecutionStrategy.BOUNDED_RETRY

    def test_ralph_loop_fails_without_isolation(self) -> None:
        recipe = _make_recipe(execution_strategy="ralph_loop")
        with pytest.raises(ValueError, match="isolated workspace"):
            select_execution_strategy(
                recipe=recipe, task_count=5, budget=10.0, is_isolated=False,
            )

    def test_default_ralph_threshold_is_3(self) -> None:
        assert RALPH_DEFAULT_THRESHOLD == 3
        assert _make_recipe().ralph_threshold == 3


# =========================================================================
# Workspace Isolation
# =========================================================================


class TestRalphWorkspaceIsolation:

    def test_ralph_uses_isolated_workspace(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=3,
        )
        result = strategy.run(_pre_pass(_make_tasks(2)))
        assert result.progress_file_path is not None
        assert str(workspace) in result.progress_file_path
        assert PROGRESS_FILENAME in result.progress_file_path

    def test_main_repo_unmodified(self, tmp_path: Path) -> None:
        main_repo = tmp_path / "main_repo"
        main_repo.mkdir()
        for cmd in [
            ["git", "init"],
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test"],
        ]:
            subprocess.run(cmd, cwd=main_repo, capture_output=True, check=True)
        (main_repo / "README.md").write_text("# Main\n")
        subprocess.run(["git", "add", "-A"], cwd=main_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=main_repo, capture_output=True, check=True)
        original = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=main_repo, capture_output=True, text=True, check=True,
        ).stdout.strip()

        workspace = _make_git_workspace(tmp_path)
        strategy = RalphExecutionStrategy(
            workspace_path=workspace,
            work_item=_make_work_item(),
            max_iterations=2, budget=10.0,
        )
        strategy.run(_make_tasks(1))

        current = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=main_repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert current == original

    def test_ralph_commits_in_isolated_workspace(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        (workspace / "task1.py").write_text("# task 1\n")
        sha = commit_iteration(workspace, 1, "Ralph iteration 1")
        assert sha is not None
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace, capture_output=True, text=True, check=True,
        )
        assert "Ralph iteration 1" in result.stdout


# =========================================================================
# Manifest Extensions
# =========================================================================


class TestRalphManifestExtensions:

    def test_manifest_includes_all_ralph_fields(self) -> None:
        result = _make_ralph_run_result(
            iteration_count=3,
            per_iteration_costs=[0.5, 0.5, 0.5],
            per_iteration_tasks_completed=[1, 1, 1],
            commit_refs=["abc123", "def456", "ghi789"],
            progress_file_path="/tmp/test/progress.json",
            tasks_completed=3, tasks_total=3, total_cost=1.5,
        )
        fields = build_ralph_manifest_fields(result)
        assert fields["execution_strategy"] == "ralph_loop"
        assert fields["iteration_count"] == 3
        assert fields["max_iterations"] == 10
        assert fields["per_iteration_costs"] == [0.5, 0.5, 0.5]
        assert fields["per_iteration_tasks_completed"] == [1, 1, 1]
        assert fields["commit_refs"] == ["abc123", "def456", "ghi789"]
        assert fields["completion_status"] == "complete"

    @pytest.mark.parametrize("field", ["per_iteration_costs", "per_iteration_tasks_completed"])
    def test_per_iteration_arrays_match_count(self, field: str) -> None:
        result = _make_ralph_run_result(
            iteration_count=4,
            per_iteration_costs=[0.5, 0.5, 0.5, 0.5],
            per_iteration_tasks_completed=[1, 0, 1, 1],
            total_cost=2.0,
        )
        fields = build_ralph_manifest_fields(result)
        assert len(fields[field]) == fields["iteration_count"]

    @pytest.mark.parametrize(
        "status,expected",
        [(CompletionStatus.COMPLETE, "complete"), (CompletionStatus.PARTIAL, "partial"),
         (CompletionStatus.FAILED, "failed")],
    )
    def test_completion_status_in_manifest(self, status: CompletionStatus, expected: str) -> None:
        fields = build_ralph_manifest_fields(_make_ralph_run_result(completion_status=status))
        assert fields["completion_status"] == expected

    def test_iteration_event_emitted(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        events: list[dict] = []
        event_bus = EventBus(source_module="ralph_execution_strategy")
        event_bus.subscribe(EventType.RALPH_ITERATION_COMPLETED, lambda e: events.append(e.payload))
        strategy = RalphExecutionStrategy(
            workspace_path=workspace, work_item=_make_work_item(),
            recipe=_make_recipe(validation={"commands": ["echo test"], "require_all_pass": True}),
            event_bus=event_bus, run_id="run-001", repo_id="repo-001",
            max_iterations=2, budget=10.0,
        )
        with patch(
            "foxhound.execution.ralph._run_validation_command",
            return_value={"command": "echo test", "passed": True},
        ):
            strategy.run(_make_tasks(1))
        for event in events:
            for key in ("iteration", "tasks_completed", "tasks_remaining", "iteration_cost", "cumulative_cost"):
                assert key in event

    def test_event_cumulative_cost_consistent(self, tmp_path: Path) -> None:
        workspace = _make_git_workspace(tmp_path)
        events: list[dict] = []
        event_bus = EventBus(source_module="ralph_execution_strategy")
        event_bus.subscribe(EventType.RALPH_ITERATION_COMPLETED, lambda e: events.append(e.payload))
        strategy = RalphExecutionStrategy(
            workspace_path=workspace, work_item=_make_work_item(),
            event_bus=event_bus, run_id="run-001", repo_id="repo-001",
            max_iterations=3, budget=10.0,
        )
        strategy.run(_pre_pass(_make_tasks(1)))
        running_total = 0.0
        for event in events:
            running_total += event["iteration_cost"]
            assert abs(event["cumulative_cost"] - running_total) < 0.001

    def test_manifest_fields_valid_json(self) -> None:
        fields = build_ralph_manifest_fields(_make_ralph_run_result())
        deserialized = json.loads(json.dumps(fields))
        assert deserialized["iteration_count"] == 2

    def test_manifest_model_accepts_ralph_fields(self) -> None:
        from foxhound.core.models import Manifest, PolicyRef, RecipeRef
        manifest = Manifest(
            manifest_id="m-001", run_id="r-001", work_item_id="wi-001",
            repo_id="repo-001",
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="default", version="1.0.0", content_hash="def"),
            context_pack_hash="ctx123",
            execution_environment_fingerprint="env123",
            execution_strategy=ExecutionStrategy.RALPH_LOOP,
            model_provider="anthropic", model_tier="balanced",
            workspace_id="ws-001",
            iteration_count=3, max_iterations=10,
            per_iteration_costs=[0.5, 0.5, 0.5],
            per_iteration_tasks_completed=[1, 1, 1],
            commit_refs=["abc", "def", "ghi"],
            progress_file_path="/tmp/progress.json",
            completion_status="complete",
        )
        assert manifest.iteration_count == 3
        assert manifest.completion_status == "complete"
        assert len(manifest.per_iteration_costs) == 3


# =========================================================================
# Recipe Model Extensions
# =========================================================================


class TestRecipeRalphFields:

    @pytest.mark.parametrize(
        "field,default_val,custom_val",
        [("ralph_threshold", 3, 5), ("max_iterations", 10, 20)],
    )
    def test_recipe_ralph_field_defaults_and_custom(
        self, field: str, default_val: int, custom_val: int,
    ) -> None:
        assert getattr(_make_recipe(), field) == default_val
        assert getattr(_make_recipe(**{field: custom_val}), field) == custom_val

    def test_ralph_loop_strategy_in_recipe(self) -> None:
        recipe = _make_recipe(execution_strategy="ralph_loop")
        assert recipe.execution_strategy == ExecutionStrategy.RALPH_LOOP


# =========================================================================
# RalphTask and RalphProgress Models
# =========================================================================


class TestRalphModels:

    def test_ralph_task_default_status(self) -> None:
        assert RalphTask(task_id="t1", title="Test").status == RalphTaskStatus.PENDING

    def test_ralph_task_statuses(self) -> None:
        assert set(RalphTaskStatus) == {
            RalphTaskStatus.PENDING, RalphTaskStatus.IN_PROGRESS,
            RalphTaskStatus.PASSED, RalphTaskStatus.FAILED,
        }

    def test_completion_status_values(self) -> None:
        assert set(CompletionStatus) == {
            CompletionStatus.COMPLETE, CompletionStatus.PARTIAL, CompletionStatus.FAILED,
        }

    def test_ralph_progress_serialization(self) -> None:
        progress = RalphProgress(
            iteration=3, tasks=_make_tasks(2),
            accomplishments=["Done stuff"],
            per_iteration_costs=[0.5, 0.5, 0.5],
        )
        loaded = RalphProgress.model_validate_json(progress.model_dump_json())
        assert loaded.iteration == 3
        assert len(loaded.tasks) == 2
        assert len(loaded.per_iteration_costs) == 3
