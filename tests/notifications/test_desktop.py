"""Tests for desktop notification channel."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
    async def test_send_osascript_calls_subprocess(self):
        channel = DesktopNotificationChannel()
        channel._method = "osascript"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            notification = _make_notification(title="Big Find", body="Check this out")
            result = await channel.send(notification)

        assert result is True
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"

    @pytest.mark.asyncio
    async def test_send_returns_false_on_exception(self):
        channel = DesktopNotificationChannel()
        channel._method = "osascript"

        with patch("subprocess.run", side_effect=RuntimeError("failed")):
            result = await channel.send(_make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_send_notify_send(self):
        channel = DesktopNotificationChannel()
        channel._method = "notify-send"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = await channel.send(_make_notification(priority="high"))

        assert result is True
        args = mock_run.call_args[0][0]
        assert args[0] == "notify-send"
        assert "critical" in args  # high maps to critical urgency

    # -- AppleScript sanitization --

    @pytest.mark.parametrize(
        ("input_text", "expected_contains"),
        [
            ('hello "world"', 'hello \\"world\\"'),
            ("test\\backslash", "test\\\\backslash"),
            ('a\\" & do shell script "evil"', None),  # should not contain unescaped quote
        ],
    )
    def test_sanitize_for_applescript(self, input_text, expected_contains):
        result = DesktopNotificationChannel._sanitize_for_applescript(input_text)
        if expected_contains:
            assert expected_contains in result
        # Ensure no unescaped quotes (every " preceded by \)
        import re
        unescaped = re.findall(r'(?<!\\)"', result)
        assert len(unescaped) == 0

    def test_sanitize_strips_control_chars(self):
        result = DesktopNotificationChannel._sanitize_for_applescript("hello\x00world\x07")
        assert "\x00" not in result
        assert "\x07" not in result
        assert "hello" in result

    def test_configure_sets_method(self):
        channel = DesktopNotificationChannel()
        with patch("sys.platform", "darwin"):
            channel.configure({})
        assert channel._method is not None
