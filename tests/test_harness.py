"""Tests for the agent harness runtime."""

import pytest

from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventEnvelope,
    EventType,
    ExecutionMode,
    ExecutionSnapshot,
    PolicyRef,
    RecipeRef,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
)
from foxhound.harness.runtime import Harness, HarnessError
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


def _task_envelope(
    execution_mode: ExecutionMode = ExecutionMode.FULL_EXECUTE,
) -> TaskEnvelope:
    return TaskEnvelope(
        task_id="task-1",
        job_id="job-1",
        run_id="run-1",
        repo_id="repo-1",
        execution_snapshot=ExecutionSnapshot(
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="test", version="1.0.0", content_hash="def"),
            config_hash="cfg",
        ),
        execution_mode=execution_mode,
    )


class GoodWorker:
    """Worker that succeeds at every stage."""

    worker_name = "good_worker"
    worker_class = WorkerClass.HELPER
    capabilities = {Capability.REPO_READ, Capability.REPO_WRITE}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds = 300
    default_budget = 1.0

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        return ContextBuildResult(context_hash="ctx-hash")

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        return WorkerOutput(payload={"action": "patch"}, cost=0.1)

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        return SanitizedOutput(payload=output.payload)

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        return EvaluationResult(passed=True, confidence=0.95)

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        return ResultEnvelope(
            status=ResultStatus.SUCCESS, confidence=result.confidence
        )


class FailValidationWorker(GoodWorker):
    """Worker that fails validation."""

    worker_name = "fail_validation"

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        return ValidationResult(valid=False, errors=["missing required field"])


class ExplodeOnExecuteWorker(GoodWorker):
    """Worker that raises during execute."""

    worker_name = "explode_execute"

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        raise RuntimeError("Simulated crash")


class ExplodeOnContextWorker(GoodWorker):
    """Worker that raises during build_context."""

    worker_name = "explode_context"

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        raise ValueError("Bad context")


class FailEvaluationWorker(GoodWorker):
    """Worker whose evaluation returns failure."""

    worker_name = "fail_eval"

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        return EvaluationResult(
            passed=False,
            safety_flags=["suspicious_pattern"],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        return ResultEnvelope(
            status=ResultStatus.QUARANTINED,
            safety_flags=result.safety_flags,
        )


class TestHarnessLifecycle:
    def test_successful_run(self) -> None:
        harness = Harness()
        result = harness.run(GoodWorker(), _task_envelope())

        assert result.result_envelope.status == ResultStatus.SUCCESS
        assert result.result_envelope.confidence == 0.95
        assert result.stage_reached == "finalize"
        assert result.duration_seconds > 0
        assert result.total_cost == 0.1

    def test_all_stages_populated(self) -> None:
        harness = Harness()
        result = harness.run(GoodWorker(), _task_envelope())

        assert result.validation.valid is True
        assert result.context is not None
        assert result.context.context_hash == "ctx-hash"
        assert result.raw_output is not None
        assert result.sanitized_output is not None
        assert result.evaluation is not None
        assert result.evaluation.passed is True


class TestValidationFailure:
    def test_returns_failed_on_invalid_input(self) -> None:
        harness = Harness()
        result = harness.run(FailValidationWorker(), _task_envelope())

        assert result.result_envelope.status == ResultStatus.FAILED
        assert "missing required field" in result.result_envelope.payload["errors"]
        assert result.stage_reached == "validate_input"

    def test_skips_remaining_stages(self) -> None:
        harness = Harness()
        result = harness.run(FailValidationWorker(), _task_envelope())

        assert result.context is None
        assert result.raw_output is None


class TestExecutionFailure:
    def test_runtime_error_caught(self) -> None:
        harness = Harness()
        result = harness.run(ExplodeOnExecuteWorker(), _task_envelope())

        assert result.result_envelope.status == ResultStatus.FAILED
        assert result.stage_reached == "execute"
        assert "Simulated crash" in result.result_envelope.payload["error"]

    def test_context_error_caught(self) -> None:
        harness = Harness()
        result = harness.run(ExplodeOnContextWorker(), _task_envelope())

        assert result.result_envelope.status == ResultStatus.FAILED
        assert result.stage_reached == "build_context"


class TestEvaluationFailure:
    def test_quarantined_on_eval_failure(self) -> None:
        harness = Harness()
        result = harness.run(FailEvaluationWorker(), _task_envelope())

        assert result.result_envelope.status == ResultStatus.QUARANTINED
        assert "suspicious_pattern" in result.result_envelope.safety_flags
        assert result.stage_reached == "finalize"


class TestEventEmission:
    def test_emits_lifecycle_events(self) -> None:
        bus = EventBus(source_module="test")
        events: list[EventEnvelope] = []
        bus.subscribe_all(events.append)

        harness = Harness(event_bus=bus)
        harness.run(GoodWorker(), _task_envelope())

        # 6 stage events + 1 completion event = 7
        assert len(events) == 7
        stages = [e.payload.get("stage") for e in events if "stage" in e.payload]
        assert "validate_input" in stages
        assert "finalize" in stages

    def test_emits_failure_event(self) -> None:
        bus = EventBus(source_module="test")
        events: list[EventEnvelope] = []
        bus.subscribe(EventType.RUN_FAILED, events.append)

        harness = Harness(event_bus=bus)
        harness.run(ExplodeOnExecuteWorker(), _task_envelope())

        assert len(events) == 1
        assert events[0].payload["stage"] == "execute"


class TestCapabilityValidation:
    def test_no_capabilities_worker_raises_for_full_execute(self) -> None:
        class NoCapsWorker(GoodWorker):
            worker_name = "no_caps"
            capabilities: set[Capability] = set()

        harness = Harness()
        with pytest.raises(HarnessError, match="lacks repo access"):
            harness.run(NoCapsWorker(), _task_envelope())

    def test_read_only_mode_passes_with_read_cap(self) -> None:
        class ReadOnlyWorker(GoodWorker):
            worker_name = "read_only"
            capabilities = {Capability.REPO_READ}

        harness = Harness()
        result = harness.run(
            ReadOnlyWorker(),
            _task_envelope(execution_mode=ExecutionMode.READ_ONLY),
        )
        assert result.result_envelope.status == ResultStatus.SUCCESS
