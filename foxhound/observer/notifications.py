"""Notification dispatch for routing events through notification policy.

Routes system events to notification sinks based on severity and event type.
Supports CLI, Slack, Discord, and generic webhook sinks.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from urllib.error import HTTPError, URLError

from foxhound.core.models import EventEnvelope, EventType

if TYPE_CHECKING:
    from foxhound.core.config import NotificationsConfig

logger = logging.getLogger(__name__)


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


class SlackNotificationSink:
    """Sends notifications to a Slack channel via incoming webhook."""

    sink_name = "slack"

    def __init__(self, webhook_url: str, channel: str | None = None) -> None:
        self._webhook_url = webhook_url
        self._channel = channel

    def send(self, message: str, priority: NotificationPriority, event: EventEnvelope) -> bool:
        """Post a formatted message to Slack."""
        icon = ":red_circle:" if priority == NotificationPriority.ALWAYS else ":large_blue_circle:"
        payload: dict[str, str] = {
            "text": f"{icon} *foxhound* | {message}",
        }
        if self._channel:
            payload["channel"] = self._channel
        return _post_json(self._webhook_url, payload, "Slack")


class DiscordNotificationSink:
    """Sends notifications to a Discord channel via webhook."""

    sink_name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(self, message: str, priority: NotificationPriority, event: EventEnvelope) -> bool:
        """Post a formatted message to Discord."""
        color = 0xFF0000 if priority == NotificationPriority.ALWAYS else 0x3498DB
        payload = {
            "embeds": [{
                "title": "foxhound",
                "description": message,
                "color": color,
            }],
        }
        return _post_json(self._webhook_url, payload, "Discord")


class WebhookNotificationSink:
    """Sends JSON payloads to a generic HTTP endpoint."""

    sink_name = "webhook"

    def __init__(self, endpoint_url: str, headers: dict[str, str] | None = None) -> None:
        self._endpoint_url = endpoint_url
        self._headers = headers or {}

    def send(self, message: str, priority: NotificationPriority, event: EventEnvelope) -> bool:
        """POST a JSON payload to the configured endpoint."""
        payload = {
            "source": "foxhound",
            "message": message,
            "priority": priority.value,
            "event_type": event.event_type.value,
            "run_id": event.run_id,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        }
        return _post_json(self._endpoint_url, payload, "Webhook", self._headers)


def _post_json(
    url: str,
    payload: dict[str, Any],
    sink_label: str,
    extra_headers: dict[str, str] | None = None,
) -> bool:
    """POST a JSON payload to a URL. Returns True on success."""
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status: int = resp.status
            return status < 400
    except (HTTPError, URLError, OSError) as exc:
        logger.warning("%s notification failed: %s", sink_label, exc)
        return False
    except Exception as exc:
        logger.warning("%s notification error: %s", sink_label, exc)
        return False


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


def build_sinks_from_config(
    notifications_config: NotificationsConfig,
) -> list[NotificationSink]:
    """Create notification sinks from configuration.

    Args:
        notifications_config: Notifications section from foxhound.yaml.

    Returns:
        List of configured and ready sinks.
    """
    sinks: list[NotificationSink] = []
    for sink_config in notifications_config.sinks:
        if sink_config.type == "slack":
            sinks.append(SlackNotificationSink(
                webhook_url=sink_config.url,
                channel=sink_config.channel,
            ))
        elif sink_config.type == "discord":
            sinks.append(DiscordNotificationSink(
                webhook_url=sink_config.url,
            ))
        elif sink_config.type == "webhook":
            sinks.append(WebhookNotificationSink(
                endpoint_url=sink_config.url,
                headers=sink_config.headers,
            ))
        else:
            logger.warning("Unknown notification sink type: %s", sink_config.type)
    return sinks
