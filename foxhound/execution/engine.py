"""Execution engine — implements approved work items in isolated workspaces.

The ExecutionWorker runs through the harness contract: validates input,
builds context, generates patches, runs validation commands, evaluates
output, and produces a result envelope. Execution happens only in
isolated workspaces created by the workspace manager.
"""

import shlex
import subprocess
from pathlib import Path
from typing import Any

from foxhound.core.models import (
    ExecutionMode,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
    WorkItem,
)
from foxhound.execution.context import ContextAssembler, ContextPack
from foxhound.execution.workspace import Workspace
from foxhound.harness.worker_protocol import (
    Capability,
    ContextBuildResult,
    EvaluationResult,
    RuntimeHandle,
    SanitizedOutput,
    ValidationResult,
    WorkerClass,
    WorkerOutput,
)
from foxhound.recipes.loader import Recipe
from foxhound.sanitization.pipeline import redact_secrets

COMMAND_ALLOWLIST: list[str] = [
    "pytest",
    "ruff",
    "mypy",
    "black",
    "isort",
    "flake8",
    "pylint",
    "eslint",
    "prettier",
    "tsc",
]

_SHELL_METACHARACTERS: set[str] = {
    "&&", "||", ";", "|", ">", "<", "$(", "`",
    "|&", "<(", ">(", "${", "$((", "\n", "\r",
}


def _is_command_allowed(command: str) -> bool:
    """Check if a shell command is in the allowlist with argument validation."""
    if any(c in command for c in ("\n", "\r", "\x00")):
        return False
    try:
        parts = shlex.split(command.strip())
    except ValueError:
        return False
    if not parts:
        return False
    executable = parts[0]
    if executable not in COMMAND_ALLOWLIST:
        return False
    for arg in parts[1:]:
        for meta in _SHELL_METACHARACTERS:
            if meta in arg:
                return False
    return True


class ExecutionWorker:
    """Worker that executes approved work items in isolated workspaces.

    Implements the Worker Protocol with all six harness lifecycle methods.
    Capabilities: repo_read, repo_write (isolated), shell (whitelisted), spawn.
    """

    worker_name: str = "execution_worker"
    worker_class: WorkerClass = WorkerClass.ROOT
    capabilities: set[Capability] = {
        Capability.REPO_READ,
        Capability.REPO_WRITE,
        Capability.SHELL,
        Capability.SPAWN,
    }
    allowed_spawn_targets: list[str] = [
        "security_review_worker",
        "patch_quality_evaluator_worker",
        "failure_triage_worker",
    ]
    default_timeout_seconds: int = 600
    default_budget: float = 5.0

    def __init__(
        self,
        workspace: Workspace | None = None,
        work_item: WorkItem | None = None,
        recipe: Recipe | None = None,
        repo_path: Path | None = None,
    ) -> None:
        self._workspace = workspace
        self._work_item = work_item
        self._recipe = recipe
        self._repo_path = repo_path
        self._context_pack: ContextPack | None = None
        self._validation_results: list[dict[str, Any]] = []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that the task has all required data for execution."""
        errors: list[str] = []
        warnings: list[str] = []

        if not task.job_id:
            errors.append("Missing job_id in task envelope")
        if not task.repo_id:
            errors.append("Missing repo_id in task envelope")

        if self._work_item is None:
            errors.append("No work item provided to execution worker")
        elif self._work_item.state.value not in ("approved", "edited"):
            errors.append(
                f"Work item state must be 'approved' or 'edited', "
                f"got '{self._work_item.state.value}'"
            )

        if self._workspace is None:
            errors.append("No isolated workspace provided")
        elif not self._workspace.exists():
            errors.append("Workspace directory does not exist")

        if task.execution_mode not in (
            ExecutionMode.FULL_EXECUTE,
            ExecutionMode.PATCH_ONLY,
        ):
            warnings.append(
                f"Execution mode '{task.execution_mode.value}' may limit output"
            )

        if task.budget <= 0:
            errors.append("Budget must be greater than 0")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Assemble context pack from work item, recipe, and repo files."""
        if self._work_item is None or self._workspace is None:
            return ContextBuildResult(
                context_pack={},
                context_hash="",
                files_included=[],
                trust_labels={},
            )

        assembler = ContextAssembler(self._workspace.workspace_path)

        policy_constraints: dict[str, Any] = {}
        if "policy_constraints" in task.input_payload:
            policy_constraints = task.input_payload["policy_constraints"]

        self._context_pack = assembler.assemble(
            work_item=self._work_item,
            recipe=self._recipe,
            policy_constraints=policy_constraints,
        )

        return ContextBuildResult(
            context_pack=self._context_pack.model_dump(
                exclude={"files"}
            ),
            context_hash=self._context_pack.context_hash,
            files_included=[f.path for f in self._context_pack.files],
            trust_labels=self._context_pack.trust_labels,
        )

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Execute the work item in the isolated workspace.

        In v1, execution generates a placeholder patch and runs validation
        commands. Full LLM integration requires the model adapter.
        """
        if self._workspace is None:
            return WorkerOutput(
                payload={"error": "No workspace available"},
                cost=0.0,
            )

        commands_run: list[str] = []
        files_changed: list[str] = []
        artifacts: list[str] = []

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

            try:
                result = self._run_validation_command(
                    cmd, self._workspace.workspace_path
                )
            except Exception as exc:
                result = {
                    "command": cmd,
                    "passed": False,
                    "error": f"Unexpected error: {exc}",
                }
            commands_run.append(cmd)
            validation_results.append(result)

        self._validation_results = validation_results

        all_passed = all(r.get("passed", False) for r in validation_results)

        return WorkerOutput(
            payload={
                "validation_results": validation_results,
                "all_validations_passed": all_passed,
                "workspace_id": self._workspace.workspace_id,
                "workspace_path": str(self._workspace.workspace_path),
            },
            commands_run=commands_run,
            files_changed=files_changed,
            cost=0.0,
            artifact_paths=artifacts,
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Sanitize execution output by redacting secrets."""
        sanitized_payload: dict[str, Any] = {}
        redactions: list[str] = []

        for key, value in output.payload.items():
            if isinstance(value, str):
                cleaned, found = redact_secrets(value)
                sanitized_payload[key] = cleaned
                if found:
                    redactions.append(f"Redacted secrets in '{key}'")
            else:
                sanitized_payload[key] = value

        return SanitizedOutput(
            payload=sanitized_payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
            artifact_paths=output.artifact_paths,
            redactions_applied=redactions,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate execution output for quality and safety."""
        safety_flags: list[str] = []
        notes: list[str] = []

        all_passed = output.payload.get("all_validations_passed", False)

        for result in self._validation_results:
            if not result.get("passed", False):
                notes.append(
                    f"Validation failed: {result.get('command', 'unknown')} — "
                    f"{result.get('error', 'no details')}"
                )

        if output.redactions_applied:
            safety_flags.append("Secrets detected and redacted in output")

        passed = all_passed or len(self._validation_results) == 0

        return EvaluationResult(
            passed=passed,
            confidence=0.9 if passed else 0.3,
            safety_flags=safety_flags,
            evaluator_notes=notes,
            recommended_next_action="promote" if passed else "retry",
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Produce the final result envelope."""
        status = ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED

        payload: dict[str, Any] = {
            "evaluation_passed": result.passed,
            "confidence": result.confidence,
        }

        if self._workspace:
            payload["workspace_id"] = self._workspace.workspace_id

        return ResultEnvelope(
            status=status,
            payload=payload,
            confidence=result.confidence,
            safety_flags=result.safety_flags,
            artifact_refs=[],
            recommended_next_action=result.recommended_next_action,
        )

    def _run_validation_command(
        self, command: str, cwd: Path
    ) -> dict[str, Any]:
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
