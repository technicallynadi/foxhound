"""Email notification channel using Resend."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import resend as _resend_module

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification

logger = logging.getLogger(__name__)


class EmailNotificationChannel:
    """Sends email notifications via Resend."""

    def __init__(self) -> None:
        self._resend = _resend_module
        self._configured: bool = False
        self._from_address: str = "foxhound@notifications.foxhound.dev"
        self._to_address: str | None = None

    def channel_name(self) -> str:
        return "email"

    def configure(self, config: dict) -> None:
        api_key = os.environ.get(config.get("api_key_env", "RESEND_API_KEY"))
        self._from_address = config.get("from_address", self._from_address)
        self._to_address = os.environ.get(config.get("to_address_env", "USER_EMAIL"))

        if api_key:
            self._resend.api_key = api_key
            self._configured = True

    async def send(self, notification: Notification) -> bool:
        """Send an email notification via Resend."""
        if not self._configured or not self._to_address:
            logger.debug("Email not configured — skipping")
            return False

        try:
            self._resend.Emails.send({
                "from": self._from_address,
                "to": self._to_address,
                "subject": f"Foxhound: {notification.title}",
                "html": self._render_email_html(notification),
            })
            return True
        except Exception as e:
            logger.warning("Email notification failed: %s", e)
            return False

    def _render_email_html(self, notification: Notification) -> str:
        """Render notification as branded HTML email."""
        from html import escape

        title = escape(notification.title)
        body = escape(notification.body)

        action_button = ""
        if notification.action_url:
            url = escape(notification.action_url, quote=True)
            action_button = (
                f'<a href="{url}" '
                'style="background: #E8A838; color: #1a1a1a; padding: 12px 24px; '
                'border-radius: 6px; text-decoration: none; display: inline-block;">'
                "Review in Foxhound</a>"
            )

        unsubscribe_link = ""
        if notification.unsubscribe_url:
            unsub_url = escape(notification.unsubscribe_url, quote=True)
            unsubscribe_link = (
                '<p style="color: #666; font-size: 12px; margin-top: 32px;">'
                "You're receiving this because you have notifications enabled in Foxhound. "
                f'<a href="{unsub_url}">Unsubscribe</a></p>'
            )

        return (
            '<div style="font-family: Inter, sans-serif; max-width: 600px; margin: 0 auto;">'
            f"<h3>{title}</h3>"
            f"<p>{body}</p>"
            f"{action_button}"
            f"{unsubscribe_link}"
            "</div>"
        )
