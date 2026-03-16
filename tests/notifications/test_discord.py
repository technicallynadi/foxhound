"""Tests for Discord notification channel."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from foxhound.notifications.channels.base import Notification
from foxhound.notifications.channels.discord import DiscordNotificationChannel


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


class TestDiscordNotificationChannel:
    def test_channel_name(self):
        assert DiscordNotificationChannel().channel_name() == "discord"

    @pytest.mark.asyncio
    async def test_send_without_configure_returns_false(self):
        channel = DiscordNotificationChannel()
        result = await channel.send(_make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_send_posts_embed_with_correct_structure(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            notification = _make_notification(title="New Opp", body="Check it out")
            result = await channel.send(notification)

        assert result is True
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert len(payload["embeds"]) == 1
        assert payload["embeds"][0]["title"] == "New Opp"
        assert payload["embeds"][0]["description"] == "Check it out"

    @pytest.mark.asyncio
    async def test_high_priority_uses_red_color(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            await channel.send(_make_notification(priority="critical"))

        payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert payload["embeds"][0]["color"] == 0xFF0000

    @pytest.mark.asyncio
    async def test_normal_priority_uses_blue_color(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            await channel.send(_make_notification(priority="normal"))

        payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert payload["embeds"][0]["color"] == 0x3498DB

    @pytest.mark.asyncio
    async def test_action_url_included_in_embed(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            await channel.send(_make_notification(action_url="https://foxhound.dev/opp/1"))

        payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert payload["embeds"][0]["url"] == "https://foxhound.dev/opp/1"

    @pytest.mark.asyncio
    async def test_no_action_url_omits_url_field(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            await channel.send(_make_notification(action_url=None))

        payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert "url" not in payload["embeds"][0]

    @pytest.mark.asyncio
    async def test_send_returns_false_on_network_error(self):
        channel = DiscordNotificationChannel()
        channel._webhook_url = "https://discord.com/api/webhooks/test"

        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = await channel.send(_make_notification())

        assert result is False

    def test_configure_reads_env_var(self):
        channel = DiscordNotificationChannel()
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://discord.com/hook"}):
            channel.configure({})
        assert channel._webhook_url == "https://discord.com/hook"

    def test_configure_custom_env_var(self):
        channel = DiscordNotificationChannel()
        with patch.dict("os.environ", {"MY_DISCORD": "https://discord.com/custom"}):
            channel.configure({"webhook_env": "MY_DISCORD"})
        assert channel._webhook_url == "https://discord.com/custom"
