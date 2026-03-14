"""Tests for the Worker Protocol and related types."""

import pytest

from foxhound.core.models import (
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
    WorkerClass,
    WorkerOutput,
)


class StubWorker:
    """Minimal worker implementation for protocol testing."""

    worker_name = "stub_worker"
    worker_class = WorkerClass.HELPER
    capabilities = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds = 300
    default_budget = 1.0

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        return ContextBuildResult(context_hash="abc")

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        return WorkerOutput(payload={"result": "done"})

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        return SanitizedOutput(payload=output.payload)

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        return EvaluationResult(passed=True, confidence=0.9)

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        return ResultEnvelope(
            status=ResultStatus.SUCCESS,
            confidence=result.confidence,
        )


class TestWorkerProtocol:
    def test_stub_worker_satisfies_protocol(self) -> None:
        worker = StubWorker()
        assert isinstance(worker, Worker)

    def test_worker_metadata(self) -> None:
        worker = StubWorker()
        assert worker.worker_name == "stub_worker"
        assert worker.worker_class == WorkerClass.HELPER
        assert Capability.REPO_READ in worker.capabilities

    def test_worker_class_enum(self) -> None:
        assert WorkerClass.ROOT == "root"
        assert WorkerClass.HELPER == "helper"

    def test_capability_enum(self) -> None:
        assert Capability.REPO_READ == "repo_read"
        assert Capability.REPO_WRITE == "repo_write"
        assert Capability.NETWORK == "network"
        assert Capability.SHELL == "shell"
        assert Capability.SPAWN == "spawn"


class TestValidationResult:
    def test_valid_result(self) -> None:
        r = ValidationResult(valid=True)
        assert r.valid is True
        assert r.errors == []

    def test_invalid_result(self) -> None:
        r = ValidationResult(valid=False, errors=["missing field"])
        assert r.valid is False
        assert "missing field" in r.errors

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(Exception):
            ValidationResult(valid=True, extra="bad")  # type: ignore[call-arg]


class TestContextBuildResult:
    def test_creation(self) -> None:
        r = ContextBuildResult(
            context_pack={"key": "value"},
            context_hash="hash123",
            files_included=["src/main.py"],
            trust_labels={"src/main.py": "semi_trusted"},
        )
        assert r.context_hash == "hash123"
        assert len(r.files_included) == 1


class TestWorkerOutput:
    def test_creation(self) -> None:
        o = WorkerOutput(
            payload={"result": "patched"},
            commands_run=["pytest"],
            files_changed=["src/main.py"],
            cost=0.05,
        )
        assert o.cost == 0.05
        assert "pytest" in o.commands_run


class TestSanitizedOutput:
    def test_creation_with_redactions(self) -> None:
        s = SanitizedOutput(
            payload={"result": "clean"},
            redactions_applied=["removed secret from line 42"],
        )
        assert len(s.redactions_applied) == 1


class TestEvaluationResult:
    def test_passed(self) -> None:
        e = EvaluationResult(passed=True, confidence=0.95)
        assert e.passed is True
        assert e.confidence == 0.95

    def test_failed_with_flags(self) -> None:
        e = EvaluationResult(
            passed=False,
            safety_flags=["untrusted_content_in_output"],
            evaluator_notes=["Found external URL in output"],
        )
        assert e.passed is False
        assert len(e.safety_flags) == 1


class TestRuntimeHandle:
    def test_has_capability(self) -> None:
        handle = RuntimeHandle(
            execution_mode=ExecutionMode.FULL_EXECUTE,
            capabilities={Capability.REPO_READ, Capability.REPO_WRITE},
            budget_remaining=1.0,
            timeout_remaining=300.0,
        )
        assert handle.has_capability(Capability.REPO_READ)
        assert not handle.has_capability(Capability.NETWORK)

    def test_consume_budget(self) -> None:
        handle = RuntimeHandle(
            execution_mode=ExecutionMode.FULL_EXECUTE,
            capabilities=set(),
            budget_remaining=1.0,
            timeout_remaining=300.0,
        )
        handle.consume_budget(0.3)
        assert handle.budget_remaining == pytest.approx(0.7)

    def test_consume_budget_exceeds_raises(self) -> None:
        handle = RuntimeHandle(
            execution_mode=ExecutionMode.FULL_EXECUTE,
            capabilities=set(),
            budget_remaining=0.5,
            timeout_remaining=300.0,
        )
        with pytest.raises(RuntimeError, match="Budget exceeded"):
            handle.consume_budget(1.0)
