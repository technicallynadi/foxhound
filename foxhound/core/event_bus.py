"""Event bus for typed local pub/sub communication.

This module provides the event bus abstraction that delivers events to the TUI,
observer, analyzer, and notification sinks. All system actions emit structured
events through this bus.

Spec References:
- Engineering Blueprint §1.1 (module 03): Event bus responsibility
- Engineering Blueprint §4.3: Event model categories
- Event Schema Spec §2: Event envelope structure
- Event Schema Spec §8: Event bus flow
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
    _utc_now,
)

# Type alias for event handlers
EventHandler = Callable[[EventEnvelope], None]


class EventBus:
    """Typed local pub/sub event bus.

    Delivers events to registered handlers based on event type. Supports
    both type-specific subscriptions and wildcard subscriptions that receive
    all events.

    Thread Safety:
        This implementation is NOT thread-safe. For concurrent access,
        external synchronization is required.

    Example:
        >>> bus = EventBus()
        >>> def on_run_started(event: EventEnvelope) -> None:
        ...     print(f"Run started: {event.run_id}")
        >>> bus.subscribe(EventType.RUN_STARTED, on_run_started)
        >>> bus.emit_run_started("run_001", "repo_123", "execution_engine")
    """

    def __init__(self, source_module: str = "event_bus") -> None:
        """Initialize the event bus.

        Args:
            source_module: Default source module name for events emitted via helpers.
        """
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._source_module = source_module

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler,
    ) -> Callable[[], None]:
        """Subscribe to events of a specific type.

        Args:
            event_type: The type of events to subscribe to.
            handler: Callback function that receives matching events.

        Returns:
            Unsubscribe function that removes this subscription.
        """
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            self._handlers[event_type].remove(handler)

        return unsubscribe

    def subscribe_all(self, handler: EventHandler) -> Callable[[], None]:
        """Subscribe to all events (wildcard subscription).

        Args:
            handler: Callback function that receives all events.

        Returns:
            Unsubscribe function that removes this subscription.
        """
        self._wildcard_handlers.append(handler)

        def unsubscribe() -> None:
            self._wildcard_handlers.remove(handler)

        return unsubscribe

    def publish(self, event: EventEnvelope) -> None:
        """Publish an event to all matching subscribers.

        Args:
            event: The event to publish.
        """
        # Deliver to type-specific handlers
        for handler in self._handlers[event.event_type]:
            handler(event)

        # Deliver to wildcard handlers
        for handler in self._wildcard_handlers:
            handler(event)

    def emit(
        self,
        event_type: EventType,
        source_module: str | None = None,
        run_id: str | None = None,
        repo_id: str | None = None,
        job_id: str | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        payload: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        """Create and publish an event.

        Convenience method that creates an EventEnvelope and publishes it.

        Args:
            event_type: Type of event to emit.
            source_module: Module emitting the event. Defaults to bus default.
            run_id: Associated run ID.
            repo_id: Associated repository ID.
            job_id: Associated job ID.
            severity: Event severity level.
            payload: Additional event data.

        Returns:
            The created and published event envelope.
        """
        event = EventEnvelope(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            timestamp=_utc_now(),
            source_module=source_module or self._source_module,
            run_id=run_id,
            repo_id=repo_id,
            job_id=job_id,
            severity=severity,
            payload=payload or {},
        )
        self.publish(event)
        return event

    # =========================================================================
    # Discovery Event Helpers
    # =========================================================================

    def emit_work_item_discovered(
        self,
        work_item_id: str,
        repo_id: str,
        source_module: str,
        title: str,
        source_type: str,
    ) -> EventEnvelope:
        """Emit a WorkItemDiscovered event."""
        return self.emit(
            event_type=EventType.WORK_ITEM_DISCOVERED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "work_item_id": work_item_id,
                "title": title,
                "source_type": source_type,
            },
        )

    def emit_discovery_scan_completed(
        self,
        repo_id: str,
        source_module: str,
        items_found: int,
        duration_seconds: float,
    ) -> EventEnvelope:
        """Emit a DiscoveryScanCompleted event."""
        return self.emit(
            event_type=EventType.DISCOVERY_SCAN_COMPLETED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "items_found": items_found,
                "duration_seconds": duration_seconds,
            },
        )

    # =========================================================================
    # Execution Event Helpers
    # =========================================================================

    def emit_run_queued(
        self,
        run_id: str,
        job_id: str,
        repo_id: str,
        source_module: str,
        work_item_id: str,
    ) -> EventEnvelope:
        """Emit a RunQueued event."""
        return self.emit(
            event_type=EventType.RUN_QUEUED,
            source_module=source_module,
            run_id=run_id,
            job_id=job_id,
            repo_id=repo_id,
            payload={"work_item_id": work_item_id},
        )

    def emit_run_started(
        self,
        run_id: str,
        repo_id: str,
        source_module: str,
        job_id: str | None = None,
        worker_type: str | None = None,
    ) -> EventEnvelope:
        """Emit a RunStarted event."""
        return self.emit(
            event_type=EventType.RUN_STARTED,
            source_module=source_module,
            run_id=run_id,
            repo_id=repo_id,
            job_id=job_id,
            payload={"worker_type": worker_type} if worker_type else {},
        )

    def emit_run_completed(
        self,
        run_id: str,
        repo_id: str,
        source_module: str,
        duration_seconds: float,
        total_cost: float = 0.0,
        branch_name: str | None = None,
        job_id: str | None = None,
    ) -> EventEnvelope:
        """Emit a RunCompleted event."""
        payload: dict[str, Any] = {
            "duration_seconds": duration_seconds,
            "total_cost": total_cost,
            "status": "success",
        }
        if branch_name:
            payload["branch_name"] = branch_name
        return self.emit(
            event_type=EventType.RUN_COMPLETED,
            source_module=source_module,
            run_id=run_id,
            repo_id=repo_id,
            job_id=job_id,
            payload=payload,
        )

    def emit_run_failed(
        self,
        run_id: str,
        repo_id: str,
        source_module: str,
        failure_reason: str,
        duration_seconds: float = 0.0,
        job_id: str | None = None,
    ) -> EventEnvelope:
        """Emit a RunFailed event."""
        return self.emit(
            event_type=EventType.RUN_FAILED,
            source_module=source_module,
            run_id=run_id,
            repo_id=repo_id,
            job_id=job_id,
            severity=EventSeverity.ERROR,
            payload={
                "failure_reason": failure_reason,
                "duration_seconds": duration_seconds,
                "status": "failed",
            },
        )

    # =========================================================================
    # Evaluation Event Helpers
    # =========================================================================

    def emit_evaluation_started(
        self,
        run_id: str,
        source_module: str,
        evaluator_type: str,
    ) -> EventEnvelope:
        """Emit an EvaluationStarted event."""
        return self.emit(
            event_type=EventType.EVALUATION_STARTED,
            source_module=source_module,
            run_id=run_id,
            payload={"evaluator_type": evaluator_type},
        )

    def emit_evaluation_passed(
        self,
        run_id: str,
        source_module: str,
        evaluator_type: str,
        confidence: float,
    ) -> EventEnvelope:
        """Emit an EvaluationPassed event."""
        return self.emit(
            event_type=EventType.EVALUATION_PASSED,
            source_module=source_module,
            run_id=run_id,
            payload={
                "evaluator_type": evaluator_type,
                "confidence": confidence,
            },
        )

    def emit_evaluation_failed(
        self,
        run_id: str,
        source_module: str,
        evaluator_type: str,
        reason: str,
    ) -> EventEnvelope:
        """Emit an EvaluationFailed event."""
        return self.emit(
            event_type=EventType.EVALUATION_FAILED,
            source_module=source_module,
            run_id=run_id,
            severity=EventSeverity.WARNING,
            payload={
                "evaluator_type": evaluator_type,
                "reason": reason,
            },
        )

    # =========================================================================
    # Security Event Helpers
    # =========================================================================

    def emit_security_scan_started(
        self,
        run_id: str,
        source_module: str,
    ) -> EventEnvelope:
        """Emit a SecurityScanStarted event."""
        return self.emit(
            event_type=EventType.SECURITY_SCAN_STARTED,
            source_module=source_module,
            run_id=run_id,
        )

    def emit_security_violation_detected(
        self,
        run_id: str,
        source_module: str,
        violation_type: str,
        details: str,
    ) -> EventEnvelope:
        """Emit a SecurityViolationDetected event."""
        return self.emit(
            event_type=EventType.SECURITY_VIOLATION_DETECTED,
            source_module=source_module,
            run_id=run_id,
            severity=EventSeverity.ERROR,
            payload={
                "violation_type": violation_type,
                "details": details,
            },
        )

    # =========================================================================
    # Approval Event Helpers
    # =========================================================================

    def emit_approval_requested(
        self,
        work_item_id: str,
        repo_id: str,
        source_module: str,
        title: str,
    ) -> EventEnvelope:
        """Emit an ApprovalRequested event."""
        return self.emit(
            event_type=EventType.APPROVAL_REQUESTED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "work_item_id": work_item_id,
                "title": title,
            },
        )

    def emit_approval_granted(
        self,
        work_item_id: str,
        repo_id: str,
        source_module: str,
        approved_by: str = "user",
    ) -> EventEnvelope:
        """Emit an ApprovalGranted event."""
        return self.emit(
            event_type=EventType.APPROVAL_GRANTED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "work_item_id": work_item_id,
                "approved_by": approved_by,
            },
        )

    def emit_approval_rejected(
        self,
        work_item_id: str,
        repo_id: str,
        source_module: str,
        reason: str = "",
    ) -> EventEnvelope:
        """Emit an ApprovalRejected event."""
        return self.emit(
            event_type=EventType.APPROVAL_REJECTED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "work_item_id": work_item_id,
                "reason": reason,
            },
        )

    # =========================================================================
    # Ralph Event Helpers
    # =========================================================================

    def emit_ralph_iteration_completed(
        self,
        run_id: str,
        repo_id: str,
        source_module: str,
        iteration: int,
        tasks_completed: int,
        tasks_remaining: int,
        iteration_cost: float,
        cumulative_cost: float,
    ) -> EventEnvelope:
        """Emit a RalphIterationCompleted event."""
        return self.emit(
            event_type=EventType.RALPH_ITERATION_COMPLETED,
            source_module=source_module,
            run_id=run_id,
            repo_id=repo_id,
            payload={
                "iteration": iteration,
                "tasks_completed": tasks_completed,
                "tasks_remaining": tasks_remaining,
                "iteration_cost": iteration_cost,
                "cumulative_cost": cumulative_cost,
            },
        )

    # =========================================================================
    # Spawning Event Helpers
    # =========================================================================

    def emit_worker_spawn_requested(
        self,
        parent_job_id: str,
        run_id: str,
        source_module: str,
        requested_worker_type: str,
        reason: str,
    ) -> EventEnvelope:
        """Emit a WorkerSpawnRequested event."""
        return self.emit(
            event_type=EventType.WORKER_SPAWN_REQUESTED,
            source_module=source_module,
            run_id=run_id,
            job_id=parent_job_id,
            payload={
                "requested_worker_type": requested_worker_type,
                "reason": reason,
            },
        )

    def emit_worker_spawn_approved(
        self,
        parent_job_id: str,
        child_job_id: str,
        run_id: str,
        source_module: str,
        worker_type: str,
    ) -> EventEnvelope:
        """Emit a WorkerSpawnApproved event."""
        return self.emit(
            event_type=EventType.WORKER_SPAWN_APPROVED,
            source_module=source_module,
            run_id=run_id,
            job_id=parent_job_id,
            payload={
                "child_job_id": child_job_id,
                "worker_type": worker_type,
            },
        )

    def emit_worker_spawn_failed(
        self,
        parent_job_id: str,
        run_id: str,
        source_module: str,
        worker_type: str,
        reason: str,
    ) -> EventEnvelope:
        """Emit a WorkerSpawnFailed event."""
        return self.emit(
            event_type=EventType.WORKER_SPAWN_FAILED,
            source_module=source_module,
            run_id=run_id,
            job_id=parent_job_id,
            severity=EventSeverity.WARNING,
            payload={
                "worker_type": worker_type,
                "reason": reason,
            },
        )

    # =========================================================================
    # Rules/Policy Event Helpers
    # =========================================================================

    def emit_rule_suggestion_created(
        self,
        repo_id: str,
        source_module: str,
        rule_name: str,
        evidence: str,
        confidence: float,
    ) -> EventEnvelope:
        """Emit a RuleSuggestionCreated event."""
        return self.emit(
            event_type=EventType.RULE_SUGGESTION_CREATED,
            source_module=source_module,
            repo_id=repo_id,
            payload={
                "rule_name": rule_name,
                "evidence": evidence,
                "confidence": confidence,
            },
        )

    def emit_policy_blocked_action(
        self,
        run_id: str,
        source_module: str,
        action: str,
        policy_name: str,
        reason: str,
    ) -> EventEnvelope:
        """Emit a PolicyBlockedAction event."""
        return self.emit(
            event_type=EventType.POLICY_BLOCKED_ACTION,
            source_module=source_module,
            run_id=run_id,
            severity=EventSeverity.WARNING,
            payload={
                "action": action,
                "policy_name": policy_name,
                "reason": reason,
            },
        )

    def emit_rule_applied(
        self,
        run_id: str,
        source_module: str,
        rule_name: str,
        rule_type: str,
        outcome: str,
    ) -> EventEnvelope:
        """Emit a RuleApplied event."""
        return self.emit(
            event_type=EventType.RULE_APPLIED,
            source_module=source_module,
            run_id=run_id,
            payload={
                "rule_name": rule_name,
                "rule_type": rule_type,
                "outcome": outcome,
            },
        )
