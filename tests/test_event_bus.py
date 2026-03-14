"""Tests for the event bus.

Validates pub/sub functionality, event emission, and all event type helpers.
"""

from foxhound.core import EventBus, EventEnvelope, EventSeverity, EventType


class TestEventBusBasics:
    """Test basic pub/sub functionality."""

    def test_create_event_bus(self) -> None:
        bus = EventBus()
        assert bus is not None

    def test_subscribe_and_receive(self) -> None:
        bus = EventBus()
        received: list[EventEnvelope] = []

        def handler(event: EventEnvelope) -> None:
            received.append(event)

        bus.subscribe(EventType.RUN_STARTED, handler)
        bus.emit(EventType.RUN_STARTED, source_module="test", run_id="run_001")

        assert len(received) == 1
        assert received[0].event_type == EventType.RUN_STARTED
        assert received[0].run_id == "run_001"

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[EventEnvelope] = []

        def handler(event: EventEnvelope) -> None:
            received.append(event)

        unsubscribe = bus.subscribe(EventType.RUN_STARTED, handler)
        bus.emit(EventType.RUN_STARTED, source_module="test")
        assert len(received) == 1

        unsubscribe()
        bus.emit(EventType.RUN_STARTED, source_module="test")
        assert len(received) == 1  # Should not increase

    def test_subscribe_all_wildcard(self) -> None:
        bus = EventBus()
        received: list[EventEnvelope] = []

        def handler(event: EventEnvelope) -> None:
            received.append(event)

        bus.subscribe_all(handler)

        bus.emit(EventType.RUN_STARTED, source_module="test")
        bus.emit(EventType.RUN_COMPLETED, source_module="test")
        bus.emit(EventType.APPROVAL_GRANTED, source_module="coordinator")

        assert len(received) == 3

    def test_multiple_handlers_same_type(self) -> None:
        bus = EventBus()
        received_a: list[EventEnvelope] = []
        received_b: list[EventEnvelope] = []

        def handler_a(event: EventEnvelope) -> None:
            received_a.append(event)

        def handler_b(event: EventEnvelope) -> None:
            received_b.append(event)

        bus.subscribe(EventType.RUN_STARTED, handler_a)
        bus.subscribe(EventType.RUN_STARTED, handler_b)

        bus.emit(EventType.RUN_STARTED, source_module="test")

        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_type_specific_filtering(self) -> None:
        bus = EventBus()
        started_events: list[EventEnvelope] = []
        completed_events: list[EventEnvelope] = []

        bus.subscribe(EventType.RUN_STARTED, started_events.append)
        bus.subscribe(EventType.RUN_COMPLETED, completed_events.append)

        bus.emit(EventType.RUN_STARTED, source_module="test")
        bus.emit(EventType.RUN_COMPLETED, source_module="test")
        bus.emit(EventType.RUN_STARTED, source_module="test")

        assert len(started_events) == 2
        assert len(completed_events) == 1


class TestEventEmission:
    """Test event emission and envelope creation."""

    def test_emit_returns_event(self) -> None:
        bus = EventBus()
        event = bus.emit(
            EventType.RUN_STARTED,
            source_module="test_module",
            run_id="run_123",
            repo_id="repo_456",
        )

        assert event.event_type == EventType.RUN_STARTED
        assert event.source_module == "test_module"
        assert event.run_id == "run_123"
        assert event.repo_id == "repo_456"
        assert event.event_id.startswith("evt_")

    def test_emit_with_payload(self) -> None:
        bus = EventBus()
        event = bus.emit(
            EventType.RUN_COMPLETED,
            source_module="test",
            payload={"duration_seconds": 42, "status": "success"},
        )

        assert event.payload["duration_seconds"] == 42
        assert event.payload["status"] == "success"

    def test_emit_with_severity(self) -> None:
        bus = EventBus()
        event = bus.emit(
            EventType.RUN_FAILED,
            source_module="test",
            severity=EventSeverity.ERROR,
        )

        assert event.severity == EventSeverity.ERROR

    def test_default_source_module(self) -> None:
        bus = EventBus(source_module="default_module")
        event = bus.emit(EventType.RUN_STARTED)

        assert event.source_module == "default_module"


class TestDiscoveryEventHelpers:
    """Test discovery-related event helpers."""

    def test_emit_work_item_discovered(self) -> None:
        bus = EventBus()
        received: list[EventEnvelope] = []
        bus.subscribe(EventType.WORK_ITEM_DISCOVERED, received.append)

        event = bus.emit_work_item_discovered(
            work_item_id="wi_001",
            repo_id="repo_123",
            source_module="discovery_engine",
            title="Fix authentication bug",
            source_type="github_issue",
        )

        assert len(received) == 1
        assert event.event_type == EventType.WORK_ITEM_DISCOVERED
        assert event.payload["work_item_id"] == "wi_001"
        assert event.payload["title"] == "Fix authentication bug"

    def test_emit_discovery_scan_completed(self) -> None:
        bus = EventBus()
        event = bus.emit_discovery_scan_completed(
            repo_id="repo_123",
            source_module="discovery_engine",
            items_found=5,
            duration_seconds=12.5,
        )

        assert event.event_type == EventType.DISCOVERY_SCAN_COMPLETED
        assert event.payload["items_found"] == 5
        assert event.payload["duration_seconds"] == 12.5


class TestExecutionEventHelpers:
    """Test execution-related event helpers."""

    def test_emit_run_queued(self) -> None:
        bus = EventBus()
        event = bus.emit_run_queued(
            run_id="run_001",
            job_id="job_001",
            repo_id="repo_123",
            source_module="coordinator",
            work_item_id="wi_001",
        )

        assert event.event_type == EventType.RUN_QUEUED
        assert event.run_id == "run_001"
        assert event.job_id == "job_001"
        assert event.payload["work_item_id"] == "wi_001"

    def test_emit_run_started(self) -> None:
        bus = EventBus()
        event = bus.emit_run_started(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            worker_type="ExecutionWorker",
        )

        assert event.event_type == EventType.RUN_STARTED
        assert event.payload["worker_type"] == "ExecutionWorker"

    def test_emit_run_completed(self) -> None:
        bus = EventBus()
        event = bus.emit_run_completed(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            duration_seconds=84.5,
            total_cost=0.45,
            branch_name="foxhound/fix-123",
        )

        assert event.event_type == EventType.RUN_COMPLETED
        assert event.payload["duration_seconds"] == 84.5
        assert event.payload["total_cost"] == 0.45
        assert event.payload["branch_name"] == "foxhound/fix-123"

    def test_emit_run_failed(self) -> None:
        bus = EventBus()
        event = bus.emit_run_failed(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            failure_reason="Test failures detected",
            duration_seconds=30.0,
        )

        assert event.event_type == EventType.RUN_FAILED
        assert event.severity == EventSeverity.ERROR
        assert event.payload["failure_reason"] == "Test failures detected"


class TestEvaluationEventHelpers:
    """Test evaluation-related event helpers."""

    def test_emit_evaluation_started(self) -> None:
        bus = EventBus()
        event = bus.emit_evaluation_started(
            run_id="run_001",
            source_module="evaluation_engine",
            evaluator_type="quality",
        )

        assert event.event_type == EventType.EVALUATION_STARTED
        assert event.payload["evaluator_type"] == "quality"

    def test_emit_evaluation_passed(self) -> None:
        bus = EventBus()
        event = bus.emit_evaluation_passed(
            run_id="run_001",
            source_module="evaluation_engine",
            evaluator_type="quality",
            confidence=0.95,
        )

        assert event.event_type == EventType.EVALUATION_PASSED
        assert event.payload["confidence"] == 0.95

    def test_emit_evaluation_failed(self) -> None:
        bus = EventBus()
        event = bus.emit_evaluation_failed(
            run_id="run_001",
            source_module="evaluation_engine",
            evaluator_type="quality",
            reason="Code coverage below threshold",
        )

        assert event.event_type == EventType.EVALUATION_FAILED
        assert event.severity == EventSeverity.WARNING


class TestSecurityEventHelpers:
    """Test security-related event helpers."""

    def test_emit_security_scan_started(self) -> None:
        bus = EventBus()
        event = bus.emit_security_scan_started(
            run_id="run_001",
            source_module="security_review_worker",
        )

        assert event.event_type == EventType.SECURITY_SCAN_STARTED

    def test_emit_security_violation_detected(self) -> None:
        bus = EventBus()
        event = bus.emit_security_violation_detected(
            run_id="run_001",
            source_module="security_review_worker",
            violation_type="sensitive_file_access",
            details="Attempted to read .env file",
        )

        assert event.event_type == EventType.SECURITY_VIOLATION_DETECTED
        assert event.severity == EventSeverity.ERROR
        assert event.payload["violation_type"] == "sensitive_file_access"


class TestApprovalEventHelpers:
    """Test approval-related event helpers."""

    def test_emit_approval_requested(self) -> None:
        bus = EventBus()
        event = bus.emit_approval_requested(
            work_item_id="wi_001",
            repo_id="repo_123",
            source_module="coordinator",
            title="Fix authentication bug",
        )

        assert event.event_type == EventType.APPROVAL_REQUESTED
        assert event.payload["work_item_id"] == "wi_001"

    def test_emit_approval_granted(self) -> None:
        bus = EventBus()
        event = bus.emit_approval_granted(
            work_item_id="wi_001",
            repo_id="repo_123",
            source_module="cli",
            approved_by="developer",
        )

        assert event.event_type == EventType.APPROVAL_GRANTED
        assert event.payload["approved_by"] == "developer"

    def test_emit_approval_rejected(self) -> None:
        bus = EventBus()
        event = bus.emit_approval_rejected(
            work_item_id="wi_001",
            repo_id="repo_123",
            source_module="cli",
            reason="Out of scope",
        )

        assert event.event_type == EventType.APPROVAL_REJECTED
        assert event.payload["reason"] == "Out of scope"


class TestRalphEventHelpers:
    """Test Ralph iteration event helpers."""

    def test_emit_ralph_iteration_completed(self) -> None:
        bus = EventBus()
        event = bus.emit_ralph_iteration_completed(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            iteration=3,
            tasks_completed=2,
            tasks_remaining=5,
            iteration_cost=0.12,
            cumulative_cost=0.45,
        )

        assert event.event_type == EventType.RALPH_ITERATION_COMPLETED
        assert event.payload["iteration"] == 3
        assert event.payload["tasks_completed"] == 2
        assert event.payload["cumulative_cost"] == 0.45


class TestSpawningEventHelpers:
    """Test worker spawning event helpers."""

    def test_emit_worker_spawn_requested(self) -> None:
        bus = EventBus()
        event = bus.emit_worker_spawn_requested(
            parent_job_id="job_001",
            run_id="run_001",
            source_module="execution_worker",
            requested_worker_type="PatchQualityEvaluator",
            reason="Validate patch quality",
        )

        assert event.event_type == EventType.WORKER_SPAWN_REQUESTED
        assert event.job_id == "job_001"
        assert event.payload["requested_worker_type"] == "PatchQualityEvaluator"

    def test_emit_worker_spawn_approved(self) -> None:
        bus = EventBus()
        event = bus.emit_worker_spawn_approved(
            parent_job_id="job_001",
            child_job_id="job_002",
            run_id="run_001",
            source_module="coordinator",
            worker_type="PatchQualityEvaluator",
        )

        assert event.event_type == EventType.WORKER_SPAWN_APPROVED
        assert event.payload["child_job_id"] == "job_002"

    def test_emit_worker_spawn_failed(self) -> None:
        bus = EventBus()
        event = bus.emit_worker_spawn_failed(
            parent_job_id="job_001",
            run_id="run_001",
            source_module="coordinator",
            worker_type="PatchQualityEvaluator",
            reason="Budget exhausted",
        )

        assert event.event_type == EventType.WORKER_SPAWN_FAILED
        assert event.severity == EventSeverity.WARNING
        assert event.payload["reason"] == "Budget exhausted"


class TestRulesPolicyEventHelpers:
    """Test rules and policy event helpers."""

    def test_emit_rule_suggestion_created(self) -> None:
        bus = EventBus()
        event = bus.emit_rule_suggestion_created(
            repo_id="repo_123",
            source_module="analyzer",
            rule_name="include_auth_schema",
            evidence="Auth tasks frequently fail without schema",
            confidence=0.85,
        )

        assert event.event_type == EventType.RULE_SUGGESTION_CREATED
        assert event.payload["rule_name"] == "include_auth_schema"
        assert event.payload["confidence"] == 0.85

    def test_emit_policy_blocked_action(self) -> None:
        bus = EventBus()
        event = bus.emit_policy_blocked_action(
            run_id="run_001",
            source_module="harness",
            action="shell_execute",
            policy_name="restricted_commands",
            reason="Command not in allowlist",
        )

        assert event.event_type == EventType.POLICY_BLOCKED_ACTION
        assert event.severity == EventSeverity.WARNING
        assert event.payload["policy_name"] == "restricted_commands"

    def test_emit_rule_applied(self) -> None:
        bus = EventBus()
        event = bus.emit_rule_applied(
            run_id="run_001",
            source_module="rules_engine",
            rule_name="max_retries",
            rule_type="hard",
            outcome="blocked",
        )

        assert event.event_type == EventType.RULE_APPLIED
        assert event.payload["rule_type"] == "hard"
        assert event.payload["outcome"] == "blocked"


class TestEventBusIntegration:
    """Integration tests for event bus scenarios."""

    def test_full_run_lifecycle(self) -> None:
        """Test a complete run lifecycle through events."""
        bus = EventBus(source_module="test_harness")
        events: list[EventEnvelope] = []
        bus.subscribe_all(events.append)

        # Simulate run lifecycle
        bus.emit_run_queued(
            run_id="run_001",
            job_id="job_001",
            repo_id="repo_123",
            source_module="coordinator",
            work_item_id="wi_001",
        )
        bus.emit_run_started(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            worker_type="ExecutionWorker",
        )
        bus.emit_evaluation_started(
            run_id="run_001",
            source_module="evaluation_engine",
            evaluator_type="quality",
        )
        bus.emit_evaluation_passed(
            run_id="run_001",
            source_module="evaluation_engine",
            evaluator_type="quality",
            confidence=0.9,
        )
        bus.emit_run_completed(
            run_id="run_001",
            repo_id="repo_123",
            source_module="execution_engine",
            duration_seconds=60.0,
            total_cost=0.25,
        )

        assert len(events) == 5
        event_types = [e.event_type for e in events]
        assert EventType.RUN_QUEUED in event_types
        assert EventType.RUN_STARTED in event_types
        assert EventType.RUN_COMPLETED in event_types

    def test_failed_run_with_security_violation(self) -> None:
        """Test a run that fails due to security violation."""
        bus = EventBus()
        events: list[EventEnvelope] = []
        bus.subscribe_all(events.append)

        bus.emit_run_started(
            run_id="run_002",
            repo_id="repo_123",
            source_module="execution_engine",
        )
        bus.emit_security_scan_started(
            run_id="run_002",
            source_module="security_review_worker",
        )
        bus.emit_security_violation_detected(
            run_id="run_002",
            source_module="security_review_worker",
            violation_type="blocked_path",
            details="Attempted to access .env",
        )
        bus.emit_run_failed(
            run_id="run_002",
            repo_id="repo_123",
            source_module="execution_engine",
            failure_reason="Security violation detected",
        )

        assert len(events) == 4
        error_events = [e for e in events if e.severity == EventSeverity.ERROR]
        assert len(error_events) == 2  # Violation + Failed
