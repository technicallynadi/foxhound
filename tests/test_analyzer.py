"""Tests for the analyzer engine module."""

import uuid

import pytest

from foxhound.analyzer.engine import (
    AnalyzerEngine,
    AnalyzerWorker,
    FailureClass,
)
from foxhound.core.models import (
    EventEnvelope,
    EventType,
    ExecutionMode,
    ExecutionSnapshot,
    PolicyRef,
    RecipeRef,
    RunRecord,
    RunState,
    TaskEnvelope,
)
from foxhound.harness.worker_protocol import (
    Capability,
    RuntimeHandle,
    WorkerClass,
)
from foxhound.storage.database import Database, EventStore, RunStore


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def engine(db: Database) -> AnalyzerEngine:
    return AnalyzerEngine(db)


@pytest.fixture
def run_store(db: Database) -> RunStore:
    return RunStore(db)


@pytest.fixture
def event_store(db: Database) -> EventStore:
    return EventStore(db)


def _make_run(
    run_id: str = "run_001",
    state: RunState = RunState.COMPLETED,
    failure_reason: str | None = None,
    retry_count: int = 0,
    total_cost: float = 0.1,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        job_id="job_001",
        worker_type="ExecutionWorker",
        state=state,
        total_cost=total_cost,
        retry_count=retry_count,
        failure_reason=failure_reason,
    )


def _make_event(
    run_id: str,
    event_type: EventType,
    payload: dict | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        source_module="test",
        run_id=run_id,
        payload=payload or {},
    )


class TestFailureClassification:
    def test_timeout_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="execution timed out")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.TIMEOUT

    def test_budget_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="budget exceeded limit")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.BUDGET_EXCEEDED

    def test_security_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="security violation detected")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.SECURITY_VIOLATION

    def test_validation_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="lint check failed")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.VALIDATION_FAILURE

    def test_model_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="model provider error")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.WRONG_MODEL

    def test_context_gap_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="missing context files")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.CONTEXT_GAP

    def test_bad_ticket_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="unclear ticket description")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.BAD_TICKET

    def test_unknown_failure(self, engine: AnalyzerEngine, run_store: RunStore) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="something unexpected")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class == FailureClass.UNKNOWN

    def test_completed_run_no_failure_class(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(state=RunState.COMPLETED)
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.failure_class is None


class TestContextGapDetection:
    def test_detects_missing_eval_events(
        self,
        engine: AnalyzerEngine,
        run_store: RunStore,
        event_store: EventStore,
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="unknown")
        run_store.save(run)
        # Only save a start event, no evaluation events
        event_store.save(_make_event("run_001", EventType.RUN_STARTED))

        diagnosis = engine.analyze_run("run_001")
        gap_text = " ".join(diagnosis.context_gaps)
        assert "evaluation" in gap_text.lower() or "security" in gap_text.lower()

    def test_detects_missing_resource_from_eval(
        self,
        engine: AnalyzerEngine,
        run_store: RunStore,
        event_store: EventStore,
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="unknown")
        run_store.save(run)
        event_store.save(_make_event(
            "run_001",
            EventType.EVALUATION_FAILED,
            payload={"reason": "schema file not found"},
        ))

        diagnosis = engine.analyze_run("run_001")
        assert any("missing" in g.lower() or "not found" in g.lower()
                    for g in diagnosis.context_gaps)


class TestReadinessAssessment:
    def test_high_retry_count_flagged(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(retry_count=5, state=RunState.FAILED, failure_reason="timeout")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert any("retry" in i.lower() for i in diagnosis.readiness_issues)

    def test_no_failure_reason_flagged(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason=None)
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert any("no failure reason" in i.lower() for i in diagnosis.readiness_issues)


class TestRuleSuggestions:
    def test_context_gap_generates_suggestion(
        self,
        engine: AnalyzerEngine,
        run_store: RunStore,
        event_store: EventStore,
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="missing context")
        run_store.save(run)
        event_store.save(_make_event(
            "run_001",
            EventType.EVALUATION_FAILED,
            payload={"reason": "helper file not found"},
        ))

        diagnosis = engine.analyze_run("run_001")
        assert len(diagnosis.rule_suggestions) > 0

    def test_timeout_with_retries_generates_suggestion(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(
            state=RunState.FAILED,
            failure_reason="timed out",
            retry_count=3,
        )
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        timeout_suggestions = [
            s for s in diagnosis.rule_suggestions
            if s.get("rule_name") == "increase_timeout"
        ]
        assert len(timeout_suggestions) > 0

    def test_suggestions_persisted_to_db(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(
            state=RunState.FAILED,
            failure_reason="timed out",
            retry_count=3,
        )
        run_store.save(run)
        engine.analyze_run("run_001")
        pending = engine.get_pending_suggestions()
        assert len(pending) > 0

    def test_approve_suggestion(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(
            state=RunState.FAILED,
            failure_reason="timed out",
            retry_count=3,
        )
        run_store.save(run)
        engine.analyze_run("run_001")
        pending = engine.get_pending_suggestions()
        assert len(pending) > 0

        sid = pending[0]["suggestion_id"]
        assert engine.approve_suggestion(sid) is True

    def test_reject_suggestion(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(
            state=RunState.FAILED,
            failure_reason="timed out",
            retry_count=3,
        )
        run_store.save(run)
        engine.analyze_run("run_001")
        pending = engine.get_pending_suggestions()
        sid = pending[0]["suggestion_id"]
        assert engine.reject_suggestion(sid) is True


class TestAnalysisConfidence:
    def test_classified_failure_increases_confidence(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="lint failed")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.confidence >= 0.7

    def test_unknown_failure_lower_confidence(
        self, engine: AnalyzerEngine, run_store: RunStore
    ) -> None:
        run = _make_run(state=RunState.FAILED, failure_reason="weird error xyz")
        run_store.save(run)
        diagnosis = engine.analyze_run("run_001")
        assert diagnosis.confidence < 0.8

    def test_run_not_found(self, engine: AnalyzerEngine) -> None:
        diagnosis = engine.analyze_run("nonexistent")
        assert diagnosis.confidence == 0.0
        assert "not found" in diagnosis.recommendations[0].lower()


class TestAnalyzerWorker:
    def test_worker_attributes(self) -> None:
        db = Database(":memory:")
        worker = AnalyzerWorker(db)
        assert worker.worker_name == "analyzer_worker"
        assert worker.worker_class == WorkerClass.HELPER
        assert Capability.REPO_READ in worker.capabilities
        assert Capability.REPO_WRITE not in worker.capabilities
        assert Capability.SHELL not in worker.capabilities

    def test_validate_input_requires_run_id(self) -> None:
        db = Database(":memory:")
        worker = AnalyzerWorker(db)
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo1",
            execution_snapshot=ExecutionSnapshot(
                recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
                policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
                config_hash="ch",
            ),
            input_payload={},
        )
        result = worker.validate_input(task)
        assert result.valid is False

    def test_validate_input_with_run_id(self) -> None:
        db = Database(":memory:")
        worker = AnalyzerWorker(db)
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo1",
            execution_snapshot=ExecutionSnapshot(
                recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
                policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
                config_hash="ch",
            ),
            input_payload={"run_id": "run_001"},
        )
        result = worker.validate_input(task)
        assert result.valid is True

    def test_full_lifecycle(self) -> None:
        db = Database(":memory:")
        run_store = RunStore(db)
        run = _make_run(state=RunState.FAILED, failure_reason="test failed")
        run_store.save(run)

        worker = AnalyzerWorker(db)
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo1",
            execution_snapshot=ExecutionSnapshot(
                recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
                policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
                config_hash="ch",
            ),
            input_payload={"run_id": "run_001"},
        )

        # Run through lifecycle
        v = worker.validate_input(task)
        assert v.valid

        ctx = worker.build_context(task)
        assert ctx.context_pack["run_id"] == "run_001"

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        output = worker.execute(task, runtime)
        assert output.payload["run_id"] == "run_001"

        sanitized = worker.sanitize_output(output)
        evaluation = worker.evaluate_output(sanitized)
        assert evaluation.passed is True

        result = worker.finalize(evaluation)
        assert result.status.value == "success"
