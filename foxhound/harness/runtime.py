"""Agent harness — standard lifecycle wrapper for all workers.

Enforces the six-method contract in order, handles budget/timeout
enforcement, emits lifecycle events, validates capabilities, and
captures artifacts. Workers never run outside the harness.
"""

import time
from datetime import UTC, datetime

from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventType,
    ExecutionMode,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
)
from foxhound.harness.worker_protocol import (
    Capability,
    ContextBuildResult,
    EvaluationResult,
    RuntimeHandle,
    SanitizedOutput,
    ValidationResult,
    Worker,
    WorkerOutput,
    validate_worker_capabilities,
)
from foxhound.sanitization.pipeline import redact_secrets


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class HarnessError(Exception):
    """Raised when the harness detects a contract violation."""


class HarnessResult:
    """Complete result from a harness-managed worker run."""

    def __init__(
        self,
        *,
        result_envelope: ResultEnvelope,
        validation: ValidationResult,
        context: ContextBuildResult | None = None,
        raw_output: WorkerOutput | None = None,
        sanitized_output: SanitizedOutput | None = None,
        evaluation: EvaluationResult | None = None,
        duration_seconds: float = 0.0,
        total_cost: float = 0.0,
        stage_reached: str = "validate_input",
    ) -> None:
        self.result_envelope = result_envelope
        self.validation = validation
        self.context = context
        self.raw_output = raw_output
        self.sanitized_output = sanitized_output
        self.evaluation = evaluation
        self.duration_seconds = duration_seconds
        self.total_cost = total_cost
        self.stage_reached = stage_reached


class Harness:
    """Lifecycle runtime wrapper for workers.

    Executes the six-method contract in order:
    1. validate_input
    2. build_context
    3. execute
    4. sanitize_output
    5. evaluate_output
    6. finalize

    Enforces budget, timeout, and capability boundaries at each stage.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus(source_module="harness")

    def run(self, worker: Worker, task: TaskEnvelope) -> HarnessResult:
        """Execute a worker through the full lifecycle.

        Args:
            worker: The worker implementation to run.
            task: The task envelope with frozen config.

        Returns:
            HarnessResult with all stage outputs and the final ResultEnvelope.
        """
        start_time = time.monotonic()

        self._validate_capabilities(worker, task)
        self._enforce_capabilities_matrix(worker)

        # Stage 1: validate_input
        self._emit_stage_event("validate_input", task, worker)
        try:
            validation = worker.validate_input(task)
        except Exception as exc:
            return self._fail_at_stage(
                "validate_input", str(exc), start_time, task, worker
            )

        if not validation.valid:
            return HarnessResult(
                result_envelope=ResultEnvelope(
                    status=ResultStatus.FAILED,
                    payload={"errors": validation.errors},
                    safety_flags=validation.warnings,
                ),
                validation=validation,
                duration_seconds=time.monotonic() - start_time,
                stage_reached="validate_input",
            )

        # Stage 2: build_context
        self._emit_stage_event("build_context", task, worker)
        try:
            context = worker.build_context(task)
        except Exception as exc:
            return self._fail_at_stage(
                "build_context", str(exc), start_time, task, worker,
                validation=validation,
            )

        # Stage 3: execute
        self._emit_stage_event("execute", task, worker)
        runtime = RuntimeHandle(
            execution_mode=task.execution_mode,
            capabilities=worker.capabilities,
            budget_remaining=task.budget,
            timeout_remaining=float(task.timeout_seconds),
        )

        try:
            raw_output = worker.execute(task, runtime)
        except RuntimeError as exc:
            # Budget/timeout exceeded
            return self._fail_at_stage(
                "execute", str(exc), start_time, task, worker,
                validation=validation, context=context,
            )
        except Exception as exc:
            return self._fail_at_stage(
                "execute", str(exc), start_time, task, worker,
                validation=validation, context=context,
            )

        # Stage 4: sanitize_output
        self._emit_stage_event("sanitize_output", task, worker)
        try:
            sanitized = worker.sanitize_output(raw_output)
        except Exception as exc:
            return self._fail_at_stage(
                "sanitize_output", str(exc), start_time, task, worker,
                validation=validation, context=context, raw_output=raw_output,
            )

        # Stage 5: evaluate_output
        self._emit_stage_event("evaluate_output", task, worker)
        try:
            evaluation = worker.evaluate_output(sanitized)
        except Exception as exc:
            return self._fail_at_stage(
                "evaluate_output", str(exc), start_time, task, worker,
                validation=validation, context=context,
                raw_output=raw_output, sanitized_output=sanitized,
            )

        # Stage 6: finalize
        self._emit_stage_event("finalize", task, worker)
        try:
            result_envelope = worker.finalize(evaluation)
        except Exception as exc:
            return self._fail_at_stage(
                "finalize", str(exc), start_time, task, worker,
                validation=validation, context=context,
                raw_output=raw_output, sanitized_output=sanitized,
                evaluation=evaluation,
            )

        duration = time.monotonic() - start_time

        self._event_bus.emit(
            event_type=EventType.RUN_COMPLETED,
            source_module="harness",
            run_id=task.run_id,
            job_id=task.job_id,
            repo_id=task.repo_id,
            payload={
                "worker": worker.worker_name,
                "duration_seconds": duration,
                "status": result_envelope.status.value,
            },
        )

        return HarnessResult(
            result_envelope=result_envelope,
            validation=validation,
            context=context,
            raw_output=raw_output,
            sanitized_output=sanitized,
            evaluation=evaluation,
            duration_seconds=duration,
            total_cost=raw_output.cost,
            stage_reached="finalize",
        )

    def _enforce_capabilities_matrix(self, worker: Worker) -> None:
        """Enforce the per-worker capabilities matrix.

        Raises:
            HarnessError: If the worker declares disallowed capabilities.
        """
        violations = validate_worker_capabilities(
            worker.worker_name, worker.capabilities
        )
        if violations:
            raise HarnessError(
                f"Capabilities matrix violation: {'; '.join(violations)}"
            )

    def _validate_capabilities(
        self, worker: Worker, task: TaskEnvelope
    ) -> None:
        """Validate that the worker's capabilities are compatible with the task.

        Raises:
            HarnessError: If capabilities are insufficient.
        """
        if task.execution_mode == ExecutionMode.FULL_EXECUTE:
            if Capability.REPO_WRITE not in worker.capabilities:
                if Capability.REPO_READ not in worker.capabilities:
                    raise HarnessError(
                        f"Worker '{worker.worker_name}' lacks repo access "
                        f"capabilities for full_execute mode"
                    )

    def _emit_stage_event(
        self, stage: str, task: TaskEnvelope, worker: Worker
    ) -> None:
        """Emit a lifecycle stage event."""
        self._event_bus.emit(
            event_type=EventType.RUN_STARTED,
            source_module="harness",
            run_id=task.run_id,
            job_id=task.job_id,
            repo_id=task.repo_id,
            payload={"stage": stage, "worker": worker.worker_name},
        )

    @staticmethod
    def _safe_error_summary(error: str) -> str:
        """Produce a redacted error summary safe for event payloads and storage."""
        truncated = error[:200]
        redacted, _ = redact_secrets(truncated)
        return redacted

    def _fail_at_stage(
        self,
        stage: str,
        error: str,
        start_time: float,
        task: TaskEnvelope,
        worker: Worker,
        *,
        validation: ValidationResult | None = None,
        context: ContextBuildResult | None = None,
        raw_output: WorkerOutput | None = None,
        sanitized_output: SanitizedOutput | None = None,
        evaluation: EvaluationResult | None = None,
    ) -> HarnessResult:
        """Create a failure result when a stage raises."""
        duration = time.monotonic() - start_time
        safe_error = self._safe_error_summary(error)

        self._event_bus.emit(
            event_type=EventType.RUN_FAILED,
            source_module="harness",
            run_id=task.run_id,
            job_id=task.job_id,
            repo_id=task.repo_id,
            payload={
                "stage": stage,
                "error": safe_error,
                "worker": worker.worker_name,
            },
        )

        return HarnessResult(
            result_envelope=ResultEnvelope(
                status=ResultStatus.FAILED,
                payload={"stage": stage, "error": safe_error},
            ),
            validation=validation or ValidationResult(valid=True),
            context=context,
            raw_output=raw_output,
            sanitized_output=sanitized_output,
            evaluation=evaluation,
            duration_seconds=duration,
            stage_reached=stage,
        )
