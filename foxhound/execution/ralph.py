"""Ralph iterative execution strategy.

Ralph is an iterative agent loop where each iteration runs with fresh context
while persisting state through git history and progress files. This avoids
the context bloat that degrades LLM performance over long sessions.

Ralph operates exclusively inside the Execution Plane as one of several
pluggable execution backends. It never decides what to build or whether to
build it — that's the coordinator's job.
"""

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.event_bus import EventBus
from foxhound.core.models import ExecutionStrategy, TrustLevel, WorkItem
from foxhound.execution.context import ContextAssembler, ContextPack
from foxhound.execution.engine import _SHELL_METACHARACTERS, COMMAND_ALLOWLIST
from foxhound.recipes.loader import Recipe
from foxhound.sanitization.pipeline import redact_secrets

RALPH_HARD_GLOBAL_MAX_ITERATIONS = 25
RALPH_DEFAULT_MAX_ITERATIONS = 10
RALPH_DEFAULT_THRESHOLD = 3

PROGRESS_FILENAME = ".foxhound_ralph_progress.json"
TASK_STATUS_FILENAME = ".foxhound_ralph_tasks.json"


class CompletionStatus(StrEnum):
    """Ralph run completion status."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class RalphTaskStatus(StrEnum):
    """Status of a single task within a Ralph run."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"


class RalphTask(BaseModel):
    """A single task within a Ralph execution scope."""

    task_id: str = Field(..., description="Unique task identifier")
    title: str = Field(..., description="Task title")
    description: str = Field(default="", description="Task description")
    status: RalphTaskStatus = Field(
        default=RalphTaskStatus.PENDING, description="Current status"
    )
    files_affected: list[str] = Field(
        default_factory=list, description="Files this task targets"
    )
    validation_commands: list[str] = Field(
        default_factory=list, description="Commands to validate this task"
    )


class RalphProgress(BaseModel):
    """Progress state persisted between iterations."""

    iteration: int = Field(default=0, description="Current iteration number")
    tasks: list[RalphTask] = Field(default_factory=list, description="Task list")
    accomplishments: list[str] = Field(
        default_factory=list, description="What was done across iterations"
    )
    remaining_work: list[str] = Field(
        default_factory=list, description="What still needs doing"
    )
    cumulative_cost: float = Field(default=0.0, description="Total cost so far")
    per_iteration_costs: list[float] = Field(
        default_factory=list, description="Cost per iteration"
    )
    per_iteration_tasks_completed: list[int] = Field(
        default_factory=list, description="Tasks completed per iteration"
    )
    commit_refs: list[str] = Field(
        default_factory=list, description="Commit SHA per iteration"
    )
    started_at: float = Field(
        default_factory=time.time, description="Start timestamp"
    )
    updated_at: float = Field(
        default_factory=time.time, description="Last update timestamp"
    )


class RalphIterationResult(BaseModel):
    """Result of a single Ralph iteration."""

    iteration: int = Field(..., description="Iteration number (1-based)")
    tasks_completed_this_iteration: int = Field(
        default=0, description="Tasks completed in this iteration"
    )
    tasks_remaining: int = Field(default=0, description="Tasks still incomplete")
    cost: float = Field(default=0.0, description="Cost for this iteration")
    commit_ref: str | None = Field(default=None, description="Git commit SHA")
    validation_results: list[dict[str, Any]] = Field(
        default_factory=list, description="Validation command results"
    )
    degradation_detected: bool = Field(
        default=False, description="Whether quality degradation was detected"
    )
    degradation_reason: str | None = Field(
        default=None, description="Reason for degradation flag"
    )


@dataclass
class RalphRunResult:
    """Final result of a complete Ralph execution."""

    completion_status: CompletionStatus
    iteration_count: int
    max_iterations: int
    total_cost: float
    per_iteration_costs: list[float] = field(default_factory=list)
    per_iteration_tasks_completed: list[int] = field(default_factory=list)
    commit_refs: list[str] = field(default_factory=list)
    progress_file_path: str | None = None
    tasks_completed: int = 0
    tasks_total: int = 0
    degradation_detected: bool = False
    degradation_reason: str | None = None
    duration_seconds: float = 0.0


def _is_command_allowed(command: str) -> bool:
    """Check if a shell command is in the allowlist."""
    if any(c in command for c in ("\n", "\r", "\x00")):
        return False
    try:
        parts = shlex.split(command.strip())
    except ValueError:
        return False
    if not parts:
        return False
    if parts[0] not in COMMAND_ALLOWLIST:
        return False
    for arg in parts[1:]:
        for meta in _SHELL_METACHARACTERS:
            if meta in arg:
                return False
    return True


def _run_validation_command(command: str, cwd: Path) -> dict[str, Any]:
    """Run a single validation command and return results."""
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "command": command,
            "passed": False,
            "error": f"Invalid command syntax: {exc}",
        }
    try:
        result = subprocess.run(
            parts,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return {
            "command": command,
            "passed": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout[:2000] if result.stdout else "",
            "stderr": result.stderr[:2000] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "passed": False,
            "error": "Command timed out after 120 seconds",
        }
    except FileNotFoundError:
        return {
            "command": command,
            "passed": False,
            "error": f"Command not found: {parts[0]}",
        }
    except Exception as exc:
        return {
            "command": command,
            "passed": False,
            "error": f"Unexpected error: {exc}",
        }


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in a directory."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        timeout=120,
    )


# =========================================================================
# Progress Persistence
# =========================================================================


def save_progress(progress: RalphProgress, workspace_path: Path) -> Path:
    """Save Ralph progress to the workspace, redacting secrets."""
    path = workspace_path / PROGRESS_FILENAME
    content = progress.model_dump_json(indent=2)
    cleaned, _ = redact_secrets(content)
    path.write_text(cleaned, encoding="utf-8")
    return path


def load_progress(workspace_path: Path) -> RalphProgress | None:
    """Load Ralph progress from the workspace."""
    path = workspace_path / PROGRESS_FILENAME
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        return RalphProgress.model_validate_json(content)
    except (json.JSONDecodeError, ValueError):
        return None


def save_task_status(tasks: list[RalphTask], workspace_path: Path) -> Path:
    """Save task status file to the workspace."""
    path = workspace_path / TASK_STATUS_FILENAME
    data = [t.model_dump() for t in tasks]
    content = json.dumps(data, indent=2)
    cleaned, _ = redact_secrets(content)
    path.write_text(cleaned, encoding="utf-8")
    return path


def load_task_status(workspace_path: Path) -> list[RalphTask] | None:
    """Load task status from the workspace."""
    path = workspace_path / TASK_STATUS_FILENAME
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return [RalphTask.model_validate(t) for t in data]
    except (json.JSONDecodeError, ValueError):
        return None


def commit_iteration(
    workspace_path: Path,
    iteration: int,
    message: str | None = None,
) -> str | None:
    """Git add and commit all changes in the workspace after an iteration.

    Returns the commit SHA, or None if nothing to commit.
    """
    try:
        _run_git(["add", "-A"], cwd=workspace_path)
        status = _run_git(["status", "--porcelain"], cwd=workspace_path)
        if not status.stdout.strip():
            return None
        msg = message or f"Ralph iteration {iteration}"
        _run_git(["commit", "-m", msg], cwd=workspace_path)
        result = _run_git(["rev-parse", "HEAD"], cwd=workspace_path)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


# =========================================================================
# Completion Evaluation
# =========================================================================


def evaluate_completion(tasks: list[RalphTask]) -> tuple[bool, int, int]:
    """Check if all tasks have passing status.

    Returns (all_complete, completed_count, remaining_count).
    """
    completed = sum(1 for t in tasks if t.status == RalphTaskStatus.PASSED)
    remaining = len(tasks) - completed
    return remaining == 0, completed, remaining


def detect_quality_degradation(
    current_results: list[dict[str, Any]],
    previous_results: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Detect if iteration N produced worse output than iteration N-1.

    Checks for:
    - Test regressions (previously passing tests now fail)
    - Increasing validation error counts
    """
    if not previous_results:
        return False, None

    prev_passed = {
        r["command"] for r in previous_results if r.get("passed", False)
    }
    curr_failed = {
        r["command"] for r in current_results if not r.get("passed", False)
    }

    regressions = prev_passed & curr_failed
    if regressions:
        return True, (
            f"Test regressions detected: {sorted(regressions)} "
            f"passed in previous iteration but failed in current"
        )

    prev_fail_count = sum(1 for r in previous_results if not r.get("passed", False))
    curr_fail_count = sum(1 for r in current_results if not r.get("passed", False))
    if curr_fail_count > prev_fail_count and prev_fail_count > 0:
        return True, (
            f"Validation failures increased from {prev_fail_count} to {curr_fail_count}"
        )

    return False, None


def check_budget_sufficient(
    remaining_budget: float,
    per_iteration_costs: list[float],
    min_budget_fraction: float = 0.1,
) -> bool:
    """Check if remaining budget can support another iteration.

    Uses average of past iteration costs to estimate next iteration cost.
    If no cost history, uses min_budget_fraction of the original budget.
    """
    if not per_iteration_costs:
        return remaining_budget > 0
    avg_cost = sum(per_iteration_costs) / len(per_iteration_costs)
    if avg_cost <= 0:
        return remaining_budget > 0
    return remaining_budget >= avg_cost


# =========================================================================
# Context Building for Ralph Iterations
# =========================================================================


def build_iteration_context(
    workspace_path: Path,
    work_item: WorkItem,
    recipe: Recipe | None,
    progress: RalphProgress | None,
    iteration: int,
) -> ContextPack:
    """Build fresh context pack for a Ralph iteration.

    Includes recipe instructions, task definitions, git diff of previous
    iteration's changes, and progress notes. No prior conversation history.
    """
    assembler = ContextAssembler(workspace_path)
    pack = assembler.assemble(work_item=work_item, recipe=recipe)

    if progress and iteration > 1:
        pack.trust_labels["progress_notes"] = TrustLevel.TRUSTED.value
        pack.trust_labels["previous_diff"] = TrustLevel.SEMI_TRUSTED.value

        try:
            diff_result = _run_git(["diff", "HEAD~1", "--stat"], cwd=workspace_path)
            if diff_result.stdout.strip():
                pack.evidence["previous_iteration_diff"] = diff_result.stdout[:3000]
        except subprocess.CalledProcessError:
            pass

        pack.evidence["progress_notes"] = {
            "iteration": progress.iteration,
            "accomplishments": progress.accomplishments[-5:],
            "remaining_work": progress.remaining_work,
            "tasks_status": [
                {"task_id": t.task_id, "title": t.title, "status": t.status.value}
                for t in progress.tasks
            ],
        }

    return pack


# =========================================================================
# Ralph Execution Strategy
# =========================================================================


class RalphExecutionStrategy:
    """Iterative bounded execution loop.

    Each iteration runs with fresh context. State persists between iterations
    via git history and progress/task status files. The loop exits when all
    tasks complete, budget is exhausted, max iterations reached, or quality
    degradation is detected.
    """

    def __init__(
        self,
        workspace_path: Path,
        work_item: WorkItem,
        recipe: Recipe | None = None,
        event_bus: EventBus | None = None,
        repo_id: str = "",
        run_id: str = "",
        max_iterations: int = RALPH_DEFAULT_MAX_ITERATIONS,
        budget: float = 5.0,
    ) -> None:
        self._workspace_path = workspace_path
        self._work_item = work_item
        self._recipe = recipe
        self._event_bus = event_bus
        self._repo_id = repo_id
        self._run_id = run_id
        self._budget = budget
        self._previous_validation_results: list[dict[str, Any]] = []

        self._max_iterations = min(
            max_iterations, RALPH_HARD_GLOBAL_MAX_ITERATIONS
        )

    @property
    def max_iterations(self) -> int:
        """Configured max iterations (capped by global hard limit)."""
        return self._max_iterations

    def run(self, tasks: list[RalphTask]) -> RalphRunResult:
        """Execute the Ralph iterative loop.

        Args:
            tasks: The tasks to execute across iterations.

        Returns:
            RalphRunResult with completion status and per-iteration data.
        """
        start_time = time.time()
        remaining_budget = self._budget

        progress = RalphProgress(
            iteration=0,
            tasks=tasks,
            started_at=start_time,
        )
        save_progress(progress, self._workspace_path)
        save_task_status(tasks, self._workspace_path)

        completion_status = CompletionStatus.FAILED
        degradation_detected = False
        degradation_reason: str | None = None

        for iteration_num in range(1, self._max_iterations + 1):
            loaded_tasks = load_task_status(self._workspace_path)
            if loaded_tasks is not None:
                tasks = loaded_tasks

            all_complete, completed_count, remaining_count = evaluate_completion(tasks)
            if all_complete:
                completion_status = CompletionStatus.COMPLETE
                break

            if not check_budget_sufficient(
                remaining_budget, progress.per_iteration_costs
            ):
                completion_status = CompletionStatus.PARTIAL
                break

            # Build fresh context (no conversation history)
            _context_pack = build_iteration_context(
                workspace_path=self._workspace_path,
                work_item=self._work_item,
                recipe=self._recipe,
                progress=progress if iteration_num > 1 else None,
                iteration=iteration_num,
            )

            # Run validation commands
            validation_commands = (
                self._recipe.validation.commands if self._recipe else []
            )
            validation_results: list[dict[str, Any]] = []
            for cmd in validation_commands:
                if not _is_command_allowed(cmd):
                    validation_results.append({
                        "command": cmd,
                        "passed": False,
                        "error": f"Command not in allowlist: {cmd}",
                    })
                    continue
                result = _run_validation_command(cmd, self._workspace_path)
                validation_results.append(result)

            # Detect quality degradation
            if iteration_num > 1:
                degraded, reason = detect_quality_degradation(
                    validation_results, self._previous_validation_results
                )
                if degraded:
                    degradation_detected = True
                    degradation_reason = reason
                    completion_status = CompletionStatus.FAILED
                    # Still record this iteration's data before breaking
                    iteration_cost = 0.0
                    remaining_budget -= iteration_cost

                    progress.iteration = iteration_num
                    progress.per_iteration_costs.append(iteration_cost)
                    progress.per_iteration_tasks_completed.append(0)
                    progress.cumulative_cost += iteration_cost
                    progress.updated_at = time.time()

                    commit_ref = commit_iteration(
                        self._workspace_path, iteration_num
                    )
                    if commit_ref:
                        progress.commit_refs.append(commit_ref)

                    save_progress(progress, self._workspace_path)
                    save_task_status(tasks, self._workspace_path)

                    self._emit_iteration_event(
                        iteration_num, 0, remaining_count,
                        iteration_cost, progress.cumulative_cost,
                    )
                    break

            self._previous_validation_results = validation_results

            # Update task statuses based on validation
            tasks_completed_this_iter = self._update_task_statuses(
                tasks, validation_results
            )

            iteration_cost = 0.0  # LLM cost tracked when model adapter is wired
            remaining_budget -= iteration_cost

            # Update progress
            all_complete_now, completed_now, remaining_now = evaluate_completion(tasks)

            progress.iteration = iteration_num
            progress.accomplishments.append(
                f"Iteration {iteration_num}: "
                f"{tasks_completed_this_iter} tasks completed"
            )
            progress.remaining_work = [
                t.title for t in tasks if t.status != RalphTaskStatus.PASSED
            ]
            progress.per_iteration_costs.append(iteration_cost)
            progress.per_iteration_tasks_completed.append(tasks_completed_this_iter)
            progress.cumulative_cost += iteration_cost
            progress.updated_at = time.time()

            # Commit iteration changes
            commit_ref = commit_iteration(self._workspace_path, iteration_num)
            if commit_ref:
                progress.commit_refs.append(commit_ref)

            save_progress(progress, self._workspace_path)
            save_task_status(tasks, self._workspace_path)

            # Emit iteration event
            self._emit_iteration_event(
                iteration_num, tasks_completed_this_iter, remaining_now,
                iteration_cost, progress.cumulative_cost,
            )

            if all_complete_now:
                completion_status = CompletionStatus.COMPLETE
                break

        else:
            # Max iterations reached without completion
            _, completed_count, remaining_count = evaluate_completion(tasks)
            if remaining_count == 0:
                completion_status = CompletionStatus.COMPLETE
            else:
                completion_status = CompletionStatus.PARTIAL

        _, final_completed, _ = evaluate_completion(tasks)
        elapsed = time.time() - start_time

        return RalphRunResult(
            completion_status=completion_status,
            iteration_count=progress.iteration,
            max_iterations=self._max_iterations,
            total_cost=progress.cumulative_cost,
            per_iteration_costs=progress.per_iteration_costs,
            per_iteration_tasks_completed=progress.per_iteration_tasks_completed,
            commit_refs=progress.commit_refs,
            progress_file_path=str(
                self._workspace_path / PROGRESS_FILENAME
            ),
            tasks_completed=final_completed,
            tasks_total=len(tasks),
            degradation_detected=degradation_detected,
            degradation_reason=degradation_reason,
            duration_seconds=elapsed,
        )

    def _update_task_statuses(
        self,
        tasks: list[RalphTask],
        validation_results: list[dict[str, Any]],
    ) -> int:
        """Update task statuses based on validation results.

        Returns the number of tasks newly completed this iteration.
        """
        newly_completed = 0
        all_passed = all(r.get("passed", False) for r in validation_results)

        for task in tasks:
            if task.status == RalphTaskStatus.PASSED:
                continue

            if task.validation_commands:
                task_passed = all(
                    r.get("passed", False)
                    for r in validation_results
                    if r.get("command") in task.validation_commands
                )
                if task_passed:
                    task.status = RalphTaskStatus.PASSED
                    newly_completed += 1
                else:
                    task.status = RalphTaskStatus.IN_PROGRESS
            elif all_passed:
                task.status = RalphTaskStatus.PASSED
                newly_completed += 1
            else:
                task.status = RalphTaskStatus.IN_PROGRESS

        return newly_completed

    def _emit_iteration_event(
        self,
        iteration: int,
        tasks_completed: int,
        tasks_remaining: int,
        iteration_cost: float,
        cumulative_cost: float,
    ) -> None:
        """Emit a RalphIterationCompleted event."""
        if self._event_bus is None:
            return
        self._event_bus.emit_ralph_iteration_completed(
            run_id=self._run_id,
            repo_id=self._repo_id,
            source_module="ralph_execution_strategy",
            iteration=iteration,
            tasks_completed=tasks_completed,
            tasks_remaining=tasks_remaining,
            iteration_cost=iteration_cost,
            cumulative_cost=cumulative_cost,
        )


# =========================================================================
# Strategy Selection
# =========================================================================


def select_execution_strategy(
    recipe: Recipe,
    task_count: int,
    budget: float,
    is_isolated: bool,
    global_ralph_threshold: int | None = None,
) -> ExecutionStrategy:
    """Select the appropriate execution strategy based on conditions.

    Args:
        recipe: The recipe governing execution.
        task_count: Number of tasks to execute.
        budget: Available budget.
        is_isolated: Whether an isolated workspace is available.
        global_ralph_threshold: Optional global override for ralph_threshold.

    Returns:
        The selected ExecutionStrategy.

    Raises:
        ValueError: If ralph_loop is selected but workspace is not isolated.
    """
    # Explicit strategy in recipe overrides auto-selection
    if recipe.execution_strategy != ExecutionStrategy.ONE_SHOT:
        strategy = recipe.execution_strategy
        if strategy == ExecutionStrategy.RALPH_LOOP:
            if not is_isolated:
                raise ValueError(
                    "ralph_loop requires an isolated workspace but none is available"
                )
            return ExecutionStrategy.RALPH_LOOP
        if strategy in (ExecutionStrategy.ONE_SHOT, ExecutionStrategy.BOUNDED_RETRY):
            return strategy

    # Auto-selection logic
    ralph_threshold: int = global_ralph_threshold or recipe.ralph_threshold

    if task_count > ralph_threshold and budget > 0 and is_isolated:
        return ExecutionStrategy.RALPH_LOOP

    if task_count > 1:
        return ExecutionStrategy.BOUNDED_RETRY

    return ExecutionStrategy.ONE_SHOT


# =========================================================================
# Manifest Builder
# =========================================================================


def build_ralph_manifest_fields(result: RalphRunResult) -> dict[str, Any]:
    """Build Ralph-specific manifest fields from a run result.

    Returns a dict that can be merged into a standard Manifest.
    """
    return {
        "execution_strategy": ExecutionStrategy.RALPH_LOOP.value,
        "iteration_count": result.iteration_count,
        "max_iterations": result.max_iterations,
        "per_iteration_costs": result.per_iteration_costs,
        "per_iteration_tasks_completed": result.per_iteration_tasks_completed,
        "commit_refs": result.commit_refs,
        "progress_file_path": result.progress_file_path,
        "completion_status": result.completion_status.value,
    }
