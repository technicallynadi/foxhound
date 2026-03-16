"""SMS notification channel using Twilio."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from twilio.rest import Client

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification

logger = logging.getLogger(__name__)


class SMSNotificationChannel:
    """Sends SMS notifications via Twilio."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._from_number: str | None = None
        self._to_number: str | None = None

    def channel_name(self) -> str:
        return "sms"

    def configure(self, config: dict) -> None:
        account_sid = os.environ.get(config.get("account_sid_env", "TWILIO_ACCOUNT_SID"))
        auth_token = os.environ.get(config.get("auth_token_env", "TWILIO_AUTH_TOKEN"))
        self._from_number = os.environ.get(config.get("from_number_env", "TWILIO_FROM_NUMBER"))
        self._to_number = os.environ.get(config.get("to_number_env", "USER_PHONE_NUMBER"))

        if account_sid and auth_token:
            self._client = Client(account_sid, auth_token)

    async def send(self, notification: Notification) -> bool:
        """Send an SMS notification via Twilio."""
        if not self._client or not self._to_number or not self._from_number:
            logger.debug("SMS not configured — skipping")
            return False

        try:
            message_body = f"Foxhound: {notification.title}\n{notification.body[:120]}"
            if notification.action_url:
                message_body += f"\n{notification.action_url}"

            self._client.messages.create(
                body=message_body,
                from_=self._from_number,
                to=self._to_number,
            )
            return True
        except Exception as e:
            logger.warning("SMS notification failed: %s", e)
            return False
