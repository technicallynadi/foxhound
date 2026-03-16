"""Notification channel implementations and registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from foxhound.notifications.channels.base import BaseNotificationChannel
from foxhound.notifications.channels.desktop import DesktopNotificationChannel
from foxhound.notifications.channels.discord import DiscordNotificationChannel
from foxhound.notifications.channels.email import EmailNotificationChannel
from foxhound.notifications.channels.slack import SlackNotificationChannel
from foxhound.notifications.channels.sms import SMSNotificationChannel
from foxhound.notifications.channels.web_push import WebPushNotificationChannel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

CHANNEL_REGISTRY: dict[str, type[BaseNotificationChannel]] = {
    "desktop": DesktopNotificationChannel,
    "discord": DiscordNotificationChannel,
    "email": EmailNotificationChannel,
    "sms": SMSNotificationChannel,
    "web_push": WebPushNotificationChannel,
    "slack": SlackNotificationChannel,
}


def load_enabled_channels(config: dict) -> list[BaseNotificationChannel]:
    """Load and configure all enabled notification channels."""
    channels: list[BaseNotificationChannel] = []
    channels_config = config.get("notifications", {}).get("channels", {})
    for name, channel_config in channels_config.items():
        if not channel_config.get("enabled", False):
            continue
        channel_class = CHANNEL_REGISTRY.get(name)
        if channel_class is None:
            logger.warning("Unknown notification channel: %s", name)
            continue
        channel = channel_class()
        channel.configure(channel_config)
        channels.append(channel)
    return channels


__all__ = [
    "CHANNEL_REGISTRY",
    "BaseNotificationChannel",
    "DesktopNotificationChannel",
    "DiscordNotificationChannel",
    "EmailNotificationChannel",
    "SMSNotificationChannel",
    "SlackNotificationChannel",
    "WebPushNotificationChannel",
    "load_enabled_channels",
]
