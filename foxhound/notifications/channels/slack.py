"""Slack notification channel using incoming webhooks."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification

logger = logging.getLogger(__name__)


class SlackNotificationChannel:
    """Sends notifications to Slack via incoming webhook."""

    def __init__(self) -> None:
        self._webhook_url: str | None = None
        self._channel: str | None = None

    def channel_name(self) -> str:
        return "slack"

    def configure(self, config: dict) -> None:
        self._webhook_url = os.environ.get(config.get("webhook_env", "SLACK_WEBHOOK_URL"))
        self._channel = config.get("channel")

    async def send(self, notification: Notification) -> bool:
        """Post a notification to Slack via webhook."""
        if not self._webhook_url:
            logger.debug("Slack not configured — skipping")
            return False

        icon = ":red_circle:" if notification.priority in ("high", "critical") else ":large_blue_circle:"
        payload: dict[str, str] = {
            "text": f"{icon} *Foxhound* | {notification.title}\n{notification.body}",
        }
        if self._channel:
            payload["channel"] = self._channel

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self._webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except (HTTPError, URLError, OSError) as exc:
            logger.warning("Slack notification failed: %s", exc)
            return False
