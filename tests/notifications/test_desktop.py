"""Tests for desktop notification channel."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foxhound.notifications.channels.base import Notification
from foxhound.notifications.channels.desktop import DesktopNotificationChannel


def _make_notification(**overrides) -> Notification:
    defaults = {
        "notification_id": "test_001",
        "title": "Test Alert",
        "body": "Something happened",
        "priority": "normal",
        "trigger_type": "opportunity_found_high",
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Notification(**defaults)


class TestDesktopNotificationChannel:
    def test_channel_name(self):
        channel = DesktopNotificationChannel()
        assert channel.channel_name() == "desktop"

    @pytest.mark.asyncio
    async def test_send_without_configure_returns_false(self):
        channel = DesktopNotificationChannel()
        result = await channel.send(_make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_send_calls_notifier_with_correct_args(self):
        channel = DesktopNotificationChannel()
        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock(return_value=None)
        channel._notifier = mock_notifier

        notification = _make_notification(title="Big Find", body="Check this out", priority="high")
        result = await channel.send(notification)

        assert result is True
        mock_notifier.send.assert_awaited_once_with(
            title="Big Find",
            message="Check this out",
            urgency="critical",
        )

    @pytest.mark.asyncio
    async def test_send_returns_false_on_exception(self):
        channel = DesktopNotificationChannel()
        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock(side_effect=RuntimeError("dbus failed"))
        channel._notifier = mock_notifier

        result = await channel.send(_make_notification())
        assert result is False

    @pytest.mark.parametrize(
        ("priority", "expected_urgency"),
        [
            ("low", "low"),
            ("normal", "normal"),
            ("high", "critical"),
            ("critical", "critical"),
            ("unknown", "normal"),
        ],
    )
    def test_urgency_mapping(self, priority: str, expected_urgency: str):
        channel = DesktopNotificationChannel()
        assert channel._map_urgency(priority) == expected_urgency

    def test_configure_without_library_sets_notifier_none(self):
        channel = DesktopNotificationChannel()
        with patch.dict("sys.modules", {"desktop_notifier": None}):
            with patch(
                "foxhound.notifications.channels.desktop.DesktopNotificationChannel.configure"
            ) as mock_configure:
                mock_configure.side_effect = lambda config: None
                channel.configure({})
        assert channel._notifier is None
