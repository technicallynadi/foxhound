"""Tests for notification routing policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from foxhound.notifications.channels.base import Notification
from foxhound.notifications.policy import NotificationPolicy


def _make_notification(**overrides) -> Notification:
    defaults = {
        "notification_id": "test_001",
        "title": "Test",
        "body": "Test body",
        "priority": "normal",
        "trigger_type": "opportunity_found_high",
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Notification(**defaults)


class TestNotificationPolicy:
    @pytest.fixture()
    def policy(self) -> NotificationPolicy:
        return NotificationPolicy()

    # -- ALWAYS_SURFACE events go to all channels --

    @pytest.mark.parametrize("trigger", ["approval_required", "build_failed", "security_blocked"])
    @pytest.mark.parametrize("channel", ["desktop", "discord", "email", "sms", "web_push", "slack"])
    def test_always_surface_goes_to_all_channels(self, policy, trigger, channel):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, channel) is True

    # -- SUPPRESSED events go nowhere --

    @pytest.mark.parametrize("trigger", ["scan_started", "scan_completed", "analyzer_completed"])
    @pytest.mark.parametrize("channel", ["desktop", "discord", "email", "sms", "web_push", "slack"])
    def test_suppressed_events_go_nowhere(self, policy, trigger, channel):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, channel) is False

    # -- SMS only fires for SMS_ONLY triggers or critical priority --

    def test_sms_fires_for_opportunity_found_critical(self, policy):
        notification = _make_notification(trigger_type="opportunity_found_critical")
        assert policy.should_send(notification, "sms") is True

    def test_sms_fires_for_build_failed_critical(self, policy):
        notification = _make_notification(trigger_type="build_failed_critical")
        assert policy.should_send(notification, "sms") is True

    def test_sms_fires_for_critical_priority(self, policy):
        notification = _make_notification(trigger_type="some_other_trigger", priority="critical")
        assert policy.should_send(notification, "sms") is True

    def test_sms_does_not_fire_for_normal_priority(self, policy):
        notification = _make_notification(trigger_type="opportunity_found_high", priority="normal")
        assert policy.should_send(notification, "sms") is False

    # -- DESKTOP_AND_ABOVE triggers --

    @pytest.mark.parametrize(
        "trigger",
        ["opportunity_found_high", "build_complete", "maintenance_needed", "trend_spike", "weekly_digest"],
    )
    def test_desktop_fires_for_desktop_and_above(self, policy, trigger):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, "desktop") is True

    @pytest.mark.parametrize(
        "trigger",
        ["opportunity_found_high", "build_complete", "maintenance_needed", "trend_spike", "weekly_digest"],
    )
    def test_email_fires_for_desktop_and_above(self, policy, trigger):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, "email") is True

    @pytest.mark.parametrize(
        "trigger",
        ["opportunity_found_high", "build_complete", "maintenance_needed", "trend_spike", "weekly_digest"],
    )
    def test_slack_fires_for_desktop_and_above(self, policy, trigger):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, "slack") is True

    # -- Web push fires for everything non-suppressed --

    def test_web_push_fires_for_non_suppressed(self, policy):
        notification = _make_notification(trigger_type="opportunity_found_high")
        assert policy.should_send(notification, "web_push") is True

    def test_web_push_suppressed(self, policy):
        notification = _make_notification(trigger_type="scan_started")
        assert policy.should_send(notification, "web_push") is False

    # -- Discord fires for DESKTOP_AND_ABOVE --

    @pytest.mark.parametrize(
        "trigger",
        ["opportunity_found_high", "build_complete", "maintenance_needed", "trend_spike", "weekly_digest"],
    )
    def test_discord_fires_for_desktop_and_above(self, policy, trigger):
        notification = _make_notification(trigger_type=trigger)
        assert policy.should_send(notification, "discord") is True

    # -- Unknown trigger falls through to False for desktop/email --

    def test_unknown_trigger_desktop_returns_false(self, policy):
        notification = _make_notification(trigger_type="unknown_event", priority="normal")
        assert policy.should_send(notification, "desktop") is False

    def test_unknown_trigger_web_push_returns_true(self, policy):
        notification = _make_notification(trigger_type="unknown_event")
        assert policy.should_send(notification, "web_push") is True
