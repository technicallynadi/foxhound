"""Discord notification channel using webhooks."""

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


class DiscordNotificationChannel:
    """Sends notifications to Discord via webhook."""

    def __init__(self) -> None:
        self._webhook_url: str | None = None

    def channel_name(self) -> str:
        return "discord"

    def configure(self, config: dict) -> None:
        self._webhook_url = os.environ.get(config.get("webhook_env", "DISCORD_WEBHOOK_URL"))

    async def send(self, notification: Notification) -> bool:
        """Post a notification to Discord via webhook embed."""
        if not self._webhook_url:
            logger.debug("Discord not configured — skipping")
            return False

        color = 0xFF0000 if notification.priority in ("high", "critical") else 0x3498DB
        embed: dict = {
            "title": notification.title,
            "description": notification.body,
            "color": color,
        }
        if notification.action_url:
            embed["url"] = notification.action_url

        payload = {"embeds": [embed]}

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
            logger.warning("Discord notification failed: %s", exc)
            return False
