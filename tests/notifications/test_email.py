"""Tests for email notification channel."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from foxhound.notifications.channels.base import Notification
from foxhound.notifications.channels.email import EmailNotificationChannel


def _make_notification(**overrides) -> Notification:
    defaults = {
        "notification_id": "test_001",
        "title": "Build Complete",
        "body": "Your build finished successfully",
        "priority": "normal",
        "trigger_type": "build_complete",
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Notification(**defaults)


class TestEmailNotificationChannel:
    def test_channel_name(self):
        assert EmailNotificationChannel().channel_name() == "email"

    @pytest.mark.asyncio
    async def test_send_without_configure_returns_false(self):
        channel = EmailNotificationChannel()
        result = await channel.send(_make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_send_calls_resend_with_correct_params(self):
        channel = EmailNotificationChannel()
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "email_123"})
        channel._resend = mock_resend
        channel._configured = True
        channel._to_address = "user@example.com"
        channel._from_address = "foxhound@notifications.foxhound.dev"

        notification = _make_notification(title="Build Complete")
        result = await channel.send(notification)

        assert result is True
        call_args = mock_resend.Emails.send.call_args[0][0]
        assert call_args["to"] == "user@example.com"
        assert call_args["from"] == "foxhound@notifications.foxhound.dev"
        assert "Build Complete" in call_args["subject"]
        assert "<div" in call_args["html"]

    @pytest.mark.asyncio
    async def test_send_returns_false_on_exception(self):
        channel = EmailNotificationChannel()
        mock_resend = MagicMock()
        mock_resend.Emails.send.side_effect = RuntimeError("API error")
        channel._resend = mock_resend
        channel._configured = True
        channel._to_address = "user@example.com"

        result = await channel.send(_make_notification())
        assert result is False

    def test_render_email_html_includes_title_and_body(self):
        channel = EmailNotificationChannel()
        notification = _make_notification(title="Alert!", body="Check this out")
        html = channel._render_email_html(notification)
        assert "Alert!" in html
        assert "Check this out" in html

    def test_render_email_html_includes_action_url(self):
        channel = EmailNotificationChannel()
        notification = _make_notification(action_url="https://foxhound.dev/opp/1")
        html = channel._render_email_html(notification)
        assert "https://foxhound.dev/opp/1" in html
        assert "Review in Foxhound" in html

    def test_render_email_html_includes_unsubscribe(self):
        channel = EmailNotificationChannel()
        notification = _make_notification(unsubscribe_url="https://foxhound.dev/unsub")
        html = channel._render_email_html(notification)
        assert "https://foxhound.dev/unsub" in html
        assert "Unsubscribe" in html

    def test_render_email_html_no_action_url(self):
        channel = EmailNotificationChannel()
        notification = _make_notification(action_url=None)
        html = channel._render_email_html(notification)
        assert "Review in Foxhound" not in html

    @pytest.mark.asyncio
    async def test_send_without_to_address_returns_false(self):
        channel = EmailNotificationChannel()
        channel._configured = True
        channel._to_address = None

        result = await channel.send(_make_notification())
        assert result is False
