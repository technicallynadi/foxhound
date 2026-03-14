"""Notification dispatch for routing events through notification policy.

Routes system events to notification sinks based on severity and event type.
V1 supports CLI sink only. Slack/Discord/webhook sinks are stubbed for future.
"""

from enum import StrEnum
from typing import Protocol

from foxhound.core.models import EventEnvelope, EventType


class NotificationPriority(StrEnum):
    """Notification priority determining delivery behavior."""

    ALWAYS = "always"
    DEFAULT = "default"
    SUPPRESS = "suppress"


# Event routing policy: which events always surface vs get suppressed
EVENT_ROUTING: dict[EventType, NotificationPriority] = {
    # Always surface
    EventType.APPROVAL_REQUESTED: NotificationPriority.ALWAYS,
    EventType.RUN_FAILED: NotificationPriority.ALWAYS,
    EventType.SECURITY_VIOLATION_DETECTED: NotificationPriority.ALWAYS,
    EventType.APPROVAL_REJECTED: NotificationPriority.ALWAYS,
    EventType.POLICY_BLOCKED_ACTION: NotificationPriority.ALWAYS,
    # Default (shown unless user opts out)
    EventType.APPROVAL_GRANTED: NotificationPriority.DEFAULT,
    EventType.RUN_COMPLETED: NotificationPriority.DEFAULT,
    EventType.EVALUATION_PASSED: NotificationPriority.DEFAULT,
    EventType.EVALUATION_FAILED: NotificationPriority.DEFAULT,
    EventType.WORKER_SPAWN_FAILED: NotificationPriority.DEFAULT,
    EventType.RULE_SUGGESTION_CREATED: NotificationPriority.DEFAULT,
    # Suppress by default
    EventType.RUN_STARTED: NotificationPriority.SUPPRESS,
    EventType.RUN_QUEUED: NotificationPriority.SUPPRESS,
    EventType.DISCOVERY_SCAN_COMPLETED: NotificationPriority.SUPPRESS,
    EventType.EVALUATION_STARTED: NotificationPriority.SUPPRESS,
    EventType.SECURITY_SCAN_STARTED: NotificationPriority.SUPPRESS,
    EventType.RALPH_ITERATION_COMPLETED: NotificationPriority.SUPPRESS,
    EventType.WORKER_SPAWN_REQUESTED: NotificationPriority.SUPPRESS,
    EventType.WORKER_SPAWN_APPROVED: NotificationPriority.SUPPRESS,
    EventType.RULE_APPLIED: NotificationPriority.SUPPRESS,
    EventType.WORK_ITEM_DISCOVERED: NotificationPriority.SUPPRESS,
    # Promotion events
    EventType.PROMOTION_STARTED: NotificationPriority.SUPPRESS,
    EventType.PROMOTION_SUCCEEDED: NotificationPriority.DEFAULT,
    EventType.PROMOTION_FAILED: NotificationPriority.ALWAYS,
}


class NotificationSink(Protocol):
    """Protocol for notification delivery targets."""

    sink_name: str

    def send(self, message: str, priority: NotificationPriority, event: EventEnvelope) -> bool:
        """Deliver a notification message.

        Returns:
            True if delivery succeeded.
        """
        ...


class CliNotificationSink:
    """Prints notifications to the CLI console using Rich formatting."""

    sink_name = "cli"

    def __init__(self) -> None:
        self._messages: list[tuple[str, NotificationPriority, EventEnvelope]] = []

    @property
    def messages(self) -> list[tuple[str, NotificationPriority, EventEnvelope]]:
        """Access stored messages for testing."""
        return list(self._messages)

    def send(self, message: str, priority: NotificationPriority, event: EventEnvelope) -> bool:
        """Print notification to console."""
        self._messages.append((message, priority, event))

        from rich.console import Console

        console = Console()
        if priority == NotificationPriority.ALWAYS:
            console.print(f"[bold red]![/bold red] {message}")
        elif priority == NotificationPriority.DEFAULT:
            console.print(f"[cyan]>[/cyan] {message}")
        return True


def _format_event_message(event: EventEnvelope) -> str:
    """Format an event into a human-readable notification message."""
    payload = event.payload
    event_type = event.event_type

    if event_type == EventType.APPROVAL_REQUESTED:
        title = payload.get("title", "unknown")
        risk = payload.get("risk", "unknown")
        wid = payload.get("work_item_id", "")
        return f"Approval required: {title} (risk: {risk}) — foxhound approve {wid}"

    if event_type == EventType.RUN_FAILED:
        reason = payload.get("reason", "unknown")
        return f"Run failed: {reason}"

    if event_type == EventType.SECURITY_VIOLATION_DETECTED:
        return f"Security violation: {payload.get('details', 'check logs')}"

    if event_type == EventType.POLICY_BLOCKED_ACTION:
        return f"Policy blocked: {payload.get('rule', 'unknown rule')}"

    if event_type == EventType.APPROVAL_GRANTED:
        return f"Approved: {payload.get('work_item_id', 'unknown')}"

    if event_type == EventType.APPROVAL_REJECTED:
        return f"Rejected: {payload.get('work_item_id', 'unknown')}"

    if event_type == EventType.RUN_COMPLETED:
        worker = payload.get("worker", "unknown")
        duration = payload.get("duration_seconds", 0)
        return f"Run completed: {worker} ({duration:.1f}s)"

    if event_type == EventType.EVALUATION_FAILED:
        return f"Evaluation failed: {payload.get('reason', 'check results')}"

    # Default format
    return f"{event_type.value}: {payload}"


class NotificationDispatcher:
    """Routes events to registered notification sinks based on routing policy."""

    def __init__(self) -> None:
        self._sinks: list[NotificationSink] = []
        self._routing: dict[EventType, NotificationPriority] = dict(EVENT_ROUTING)
        self._suppressed_count: int = 0
        self._delivered_count: int = 0

    def add_sink(self, sink: NotificationSink) -> None:
        """Register a notification sink."""
        self._sinks.append(sink)

    @property
    def sinks(self) -> list[NotificationSink]:
        """Get registered sinks."""
        return list(self._sinks)

    @property
    def stats(self) -> dict[str, int]:
        """Get delivery statistics."""
        return {
            "delivered": self._delivered_count,
            "suppressed": self._suppressed_count,
        }

    def get_priority(self, event_type: EventType) -> NotificationPriority:
        """Get the routing priority for an event type."""
        return self._routing.get(event_type, NotificationPriority.DEFAULT)

    def override_priority(
        self, event_type: EventType, priority: NotificationPriority
    ) -> None:
        """Override the routing priority for an event type."""
        self._routing[event_type] = priority

    def dispatch(self, event: EventEnvelope) -> bool:
        """Route an event to sinks based on its priority.

        Returns:
            True if at least one sink received the message.
        """
        priority = self.get_priority(event.event_type)

        if priority == NotificationPriority.SUPPRESS:
            self._suppressed_count += 1
            return False

        message = _format_event_message(event)
        delivered = False

        for sink in self._sinks:
            if sink.send(message, priority, event):
                delivered = True

        if delivered:
            self._delivered_count += 1

        return delivered

    def dispatch_batch(self, events: list[EventEnvelope]) -> int:
        """Dispatch multiple events.

        Returns:
            Number of events delivered (not suppressed).
        """
        count = 0
        for event in events:
            if self.dispatch(event):
                count += 1
        return count
