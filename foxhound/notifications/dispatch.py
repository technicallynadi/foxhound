"""Notification dispatch router.

Routes notifications to configured channels based on notification policy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from foxhound.notifications.channels.base import BaseNotificationChannel, Notification
from foxhound.notifications.policy import NotificationPolicy

logger = logging.getLogger(__name__)


def build_dispatch_from_config(config_path: Path | None = None) -> NotificationDispatch:
    """Build a NotificationDispatch from foxhound.yaml.

    Args:
        config_path: Path to foxhound.yaml. Defaults to cwd/foxhound.yaml.

    Returns:
        Configured NotificationDispatch with enabled channels registered.
    """
    import yaml

    from foxhound.notifications.channels import load_enabled_channels

    path = config_path or Path.cwd() / "foxhound.yaml"
    config: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("Failed to load %s for notifications", path)

    if not config.get("notifications", {}).get("enabled", False):
        return NotificationDispatch()

    dispatch = NotificationDispatch()
    for channel in load_enabled_channels(config):
        dispatch.register_channel(channel)

    return dispatch


class NotificationDispatch:
    """Routes notifications to configured channels based on policy."""

    def __init__(self) -> None:
        self._channels: list[BaseNotificationChannel] = []
        self._policy: NotificationPolicy = NotificationPolicy()
        self._sent_count: int = 0
        self._skipped_count: int = 0

    @property
    def channels(self) -> list[BaseNotificationChannel]:
        """Get registered channels."""
        return list(self._channels)

    @property
    def policy(self) -> NotificationPolicy:
        """Get the current notification policy."""
        return self._policy

    @property
    def stats(self) -> dict[str, int]:
        """Get delivery statistics."""
        return {
            "sent": self._sent_count,
            "skipped": self._skipped_count,
        }

    def register_channel(self, channel: BaseNotificationChannel) -> None:
        """Register a notification channel."""
        self._channels.append(channel)

    async def notify(self, notification: Notification) -> bool:
        """Route a notification to all applicable channels.

        Returns:
            True if at least one channel accepted the notification.
        """
        delivered = False

        for channel in self._channels:
            channel_name = channel.channel_name()

            if not self._policy.should_send(notification, channel_name):
                self._skipped_count += 1
                continue

            try:
                success = await channel.send(notification)
                if success:
                    logger.info("Notification sent via %s: %s", channel_name, notification.title)
                    delivered = True
                else:
                    logger.debug("Notification skipped by %s", channel_name)
            except Exception as e:
                logger.error("Notification failed on %s: %s", channel_name, e)

        if delivered:
            self._sent_count += 1

        return delivered

    async def notify_batch(self, notifications: list[Notification]) -> int:
        """Send multiple notifications.

        Returns:
            Number of notifications delivered to at least one channel.
        """
        count = 0
        for notification in notifications:
            if await self.notify(notification):
                count += 1
        return count
