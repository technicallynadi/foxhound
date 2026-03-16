"""Web push notification channel for the Foxhound web UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification

logger = logging.getLogger(__name__)


class WebPushNotificationChannel:
    """Sends notifications to connected web UI clients via websocket."""

    def __init__(self) -> None:
        self._connected_clients: list[Any] = []

    def channel_name(self) -> str:
        return "web_push"

    def configure(self, config: dict) -> None:
        pass

    def add_client(self, client: Any) -> None:
        """Register a connected websocket client."""
        self._connected_clients.append(client)

    def remove_client(self, client: Any) -> None:
        """Unregister a disconnected client."""
        if client in self._connected_clients:
            self._connected_clients.remove(client)

    @property
    def connected_clients(self) -> list[Any]:
        """Get currently connected clients."""
        return list(self._connected_clients)

    async def send(self, notification: Notification) -> bool:
        """Send notification to all connected web UI clients."""
        if not self._connected_clients:
            return False

        payload = {
            "type": "notification",
            "title": notification.title,
            "body": notification.body,
            "priority": notification.priority,
            "action_url": notification.action_url,
            "timestamp": notification.timestamp.isoformat(),
        }

        sent_any = False
        disconnected: list[Any] = []

        for client in self._connected_clients:
            try:
                await client.send_json(payload)
                sent_any = True
            except Exception:
                disconnected.append(client)

        for client in disconnected:
            self._connected_clients.remove(client)

        return sent_any
