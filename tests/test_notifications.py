"""Tests for notification service: receipts, digests, follow-ups, match alerts."""

import json
import pytest
from unittest.mock import AsyncMock, patch
from app.services.apply.notifications import (
    _get_user_channels,
    send_new_match_alert,
    send_followup_day3,
    send_followup_day7,
    send_followup_day14,
)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------

def test_get_user_channels_no_webhooks():
    """No webhook URLs configured → no channels."""
    profile = type("P", (), {"notify_channels_json": '["slack"]'})()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = ""
        mock_settings.discord_webhook_url = ""
        mock_settings.sms_webhook_url = ""
        result = _get_user_channels(profile)
    assert result == {}


def test_get_user_channels_default():
    """Default channels (email only) → no webhooks."""
    profile = type("P", (), {"notify_channels_json": '["email"]'})()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = "https://hooks.slack.com/test"
        result = _get_user_channels(profile)
    assert result == {}


# ---------------------------------------------------------------------------
# New match alert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_match_alert_no_channels():
    profile = type("P", (), {
        "notify_channels_json": '["email"]',
        "autopilot_threshold": 80,
    })()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = ""
        mock_settings.discord_webhook_url = ""
        mock_settings.sms_webhook_url = ""
        result = await send_new_match_alert(profile, [])
    assert result == {"skipped": "no channels"}


# ---------------------------------------------------------------------------
# Follow-up messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_day3_no_channels():
    profile = type("P", (), {"notify_channels_json": '["email"]'})()
    job = type("J", (), {"company": "Anthropic", "title": "Engineer", "ats_type": "greenhouse"})()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = ""
        mock_settings.discord_webhook_url = ""
        mock_settings.sms_webhook_url = ""
        result = await send_followup_day3(profile, job)
    assert result == {"skipped": "no channels"}


@pytest.mark.asyncio
async def test_followup_day7_no_channels():
    profile = type("P", (), {"notify_channels_json": '["email"]'})()
    job = type("J", (), {"company": "Stripe", "title": "Backend", "ats_type": "lever"})()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = ""
        mock_settings.discord_webhook_url = ""
        mock_settings.sms_webhook_url = ""
        result = await send_followup_day7(profile, job)
    assert result == {"skipped": "no channels"}


@pytest.mark.asyncio
async def test_followup_day14_no_channels():
    profile = type("P", (), {"notify_channels_json": '["email"]'})()
    job = type("J", (), {"company": "OpenAI", "title": "ML Eng", "ats_type": "ashby"})()
    with patch("app.services.apply.notifications.settings") as mock_settings:
        mock_settings.slack_webhook_url = ""
        mock_settings.discord_webhook_url = ""
        mock_settings.sms_webhook_url = ""
        result = await send_followup_day14(profile, job)
    assert result == {"skipped": "no channels"}
