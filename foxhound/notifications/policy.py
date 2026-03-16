"""Notification routing policy.

Determines which notifications route to which channels based on
trigger type, priority, and user preferences.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification


class NotificationPolicy:
    """Determines which notifications route to which channels."""

    ALWAYS_SURFACE = frozenset({
        "approval_required",
        "build_failed",
        "security_blocked",
    })

    DESKTOP_AND_ABOVE = frozenset({
        "opportunity_found_high",
        "build_complete",
        "maintenance_needed",
        "trend_spike",
        "weekly_digest",
    })

    SMS_ONLY = frozenset({
        "opportunity_found_critical",
        "build_failed_critical",
    })

    SUPPRESSED = frozenset({
        "scan_started",
        "scan_completed",
        "analyzer_completed",
    })

    def should_send(self, notification: Notification, channel: str) -> bool:
        """Determine whether a notification should be sent to a given channel."""
        trigger = notification.trigger_type

        if trigger in self.SUPPRESSED:
            return False

        if trigger in self.ALWAYS_SURFACE:
            return True

        if channel == "sms":
            if trigger in self.SMS_ONLY:
                return True
            return notification.priority == "critical"

        if channel == "desktop" and trigger in self.DESKTOP_AND_ABOVE:
            return True

        if channel == "email" and trigger in self.DESKTOP_AND_ABOVE:
            return True

        if channel == "web_push":
            return trigger not in self.SUPPRESSED

        if channel == "slack" and trigger in self.DESKTOP_AND_ABOVE:
            return True

        if channel == "discord" and trigger in self.DESKTOP_AND_ABOVE:
            return True

        return False
