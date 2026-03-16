"""Tests for notification dispatch router."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from foxhound.notifications.channels.base import Notification
from foxhound.notifications.dispatch import NotificationDispatch


def _make_notification(**overrides) -> Notification:
    defaults = {
        "notification_id": "test_001",
        "title": "Test Alert",
        "body": "Something happened",
        "priority": "normal",
        "trigger_type": "build_complete",
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Notification(**defaults)


class FakeChannel:
    """Fake channel for testing dispatch logic."""

    def __init__(self, name: str = "desktop", should_succeed: bool = True):
        self._name = name
        self._should_succeed = should_succeed
        self.sent: list[Notification] = []

    def channel_name(self) -> str:
        return self._name

    def configure(self, config: dict) -> None:
        pass

    async def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return self._should_succeed


class FailingChannel:
    """Channel that raises exceptions."""

    def channel_name(self) -> str:
        return "failing"

    def configure(self, config: dict) -> None:
        pass

    async def send(self, notification: Notification) -> bool:
        raise RuntimeError("Channel exploded")


class TestNotificationDispatch:
    @pytest.fixture()
    def dispatch(self) -> NotificationDispatch:
        return NotificationDispatch()

    def test_initial_stats(self, dispatch):
        assert dispatch.stats == {"sent": 0, "skipped": 0}

    def test_register_channel(self, dispatch):
        channel = FakeChannel()
        dispatch.register_channel(channel)
        assert len(dispatch.channels) == 1
        assert dispatch.channels[0].channel_name() == "desktop"

    def test_channels_returns_copy(self, dispatch):
        dispatch.register_channel(FakeChannel())
        channels = dispatch.channels
        channels.clear()
        assert len(dispatch.channels) == 1

    @pytest.mark.asyncio
    async def test_notify_routes_to_matching_channel(self, dispatch):
        channel = FakeChannel("desktop")
        dispatch.register_channel(channel)

        notification = _make_notification(trigger_type="build_complete")
        result = await dispatch.notify(notification)

        assert result is True
        assert len(channel.sent) == 1
        assert dispatch.stats["sent"] == 1

    @pytest.mark.asyncio
    async def test_notify_skips_channel_per_policy(self, dispatch):
        channel = FakeChannel("sms")
        dispatch.register_channel(channel)

        # build_complete with normal priority should not go to SMS
        notification = _make_notification(trigger_type="build_complete", priority="normal")
        result = await dispatch.notify(notification)

        assert result is False
        assert len(channel.sent) == 0

    @pytest.mark.asyncio
    async def test_notify_suppressed_event(self, dispatch):
        channel = FakeChannel("desktop")
        dispatch.register_channel(channel)

        notification = _make_notification(trigger_type="scan_started")
        result = await dispatch.notify(notification)

        assert result is False
        assert len(channel.sent) == 0

    @pytest.mark.asyncio
    async def test_notify_always_surface_goes_to_all(self, dispatch):
        desktop = FakeChannel("desktop")
        email = FakeChannel("email")
        sms = FakeChannel("sms")
        dispatch.register_channel(desktop)
        dispatch.register_channel(email)
        dispatch.register_channel(sms)

        notification = _make_notification(trigger_type="approval_required")
        result = await dispatch.notify(notification)

        assert result is True
        assert len(desktop.sent) == 1
        assert len(email.sent) == 1
        assert len(sms.sent) == 1

    @pytest.mark.asyncio
    async def test_notify_handles_channel_exception(self, dispatch):
        good_channel = FakeChannel("desktop")
        bad_channel = FailingChannel()
        dispatch.register_channel(good_channel)
        dispatch.register_channel(bad_channel)

        # Force policy to send to "failing" channel — use always_surface trigger
        notification = _make_notification(trigger_type="approval_required")
        result = await dispatch.notify(notification)

        # Desktop still got the notification
        assert result is True
        assert len(good_channel.sent) == 1

    @pytest.mark.asyncio
    async def test_notify_channel_returns_false(self, dispatch):
        channel = FakeChannel("desktop", should_succeed=False)
        dispatch.register_channel(channel)

        notification = _make_notification(trigger_type="build_complete")
        result = await dispatch.notify(notification)

        assert result is False
        assert len(channel.sent) == 1

    @pytest.mark.asyncio
    async def test_notify_batch(self, dispatch):
        channel = FakeChannel("desktop")
        dispatch.register_channel(channel)

        notifications = [
            _make_notification(trigger_type="build_complete", notification_id="n1"),
            _make_notification(trigger_type="scan_started", notification_id="n2"),  # suppressed
            _make_notification(trigger_type="approval_required", notification_id="n3"),
        ]
        count = await dispatch.notify_batch(notifications)

        assert count == 2
        assert len(channel.sent) == 2

    @pytest.mark.asyncio
    async def test_notify_batch_empty(self, dispatch):
        assert await dispatch.notify_batch([]) == 0

    @pytest.mark.asyncio
    async def test_multiple_channels_partial_delivery(self, dispatch):
        desktop = FakeChannel("desktop", should_succeed=True)
        sms = FakeChannel("sms", should_succeed=False)
        dispatch.register_channel(desktop)
        dispatch.register_channel(sms)

        notification = _make_notification(trigger_type="build_complete")
        result = await dispatch.notify(notification)

        # Desktop succeeded, SMS was policy-skipped
        assert result is True

    def test_policy_accessible(self, dispatch):
        assert dispatch.policy is not None
