"""Tests for trend alert triggers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from foxhound.notifications.triggers.trend_alerts import TrendAlertTrigger
from foxhound.scout.connectors.base import RawOpportunity


def _make_opportunity(
    score: float = 0.5,
    title: str = "Test Opportunity",
    topic: str | None = None,
    opp_id: str = "opp_1",
) -> RawOpportunity:
    metadata: dict = {"computed_score": score, "id": opp_id}
    if topic is not None:
        metadata["topic"] = topic
    return RawOpportunity(
        source_type="test",
        source_url="https://example.com",
        title=title,
        raw_metadata=metadata,
        discovered_at=datetime.now(timezone.utc),
    )


class TestTrendAlertTrigger:
    @pytest.fixture()
    def trigger(self) -> TrendAlertTrigger:
        return TrendAlertTrigger()

    @pytest.fixture()
    def user_config(self) -> dict:
        return {"notifications": {"min_score_alert": 0.8}}

    # -- High-score alerts --

    @pytest.mark.asyncio
    async def test_high_score_generates_notification(self, trigger, user_config):
        opps = [_make_opportunity(score=0.85, title="OAuth lib")]
        notifications = await trigger.evaluate(opps, user_config)

        assert len(notifications) == 1
        assert notifications[0].title == "New opportunity (0.85)"
        assert notifications[0].trigger_type == "opportunity_found_high"
        assert notifications[0].priority == "normal"

    @pytest.mark.asyncio
    async def test_critical_score_generates_critical_notification(self, trigger, user_config):
        opps = [_make_opportunity(score=0.96, title="Critical find")]
        notifications = await trigger.evaluate(opps, user_config)

        assert len(notifications) == 1
        assert notifications[0].trigger_type == "opportunity_found_critical"
        assert notifications[0].priority == "critical"

    @pytest.mark.asyncio
    async def test_score_0_90_is_high_priority(self, trigger, user_config):
        opps = [_make_opportunity(score=0.92)]
        notifications = await trigger.evaluate(opps, user_config)

        assert len(notifications) == 1
        assert notifications[0].priority == "high"

    @pytest.mark.asyncio
    async def test_below_threshold_no_notification(self, trigger, user_config):
        opps = [_make_opportunity(score=0.5)]
        notifications = await trigger.evaluate(opps, user_config)

        assert len(notifications) == 0

    @pytest.mark.asyncio
    async def test_at_threshold_generates_notification(self, trigger, user_config):
        opps = [_make_opportunity(score=0.8)]
        notifications = await trigger.evaluate(opps, user_config)

        assert len(notifications) == 1

    @pytest.mark.asyncio
    async def test_custom_threshold(self, trigger):
        config = {"notifications": {"min_score_alert": 0.5}}
        opps = [_make_opportunity(score=0.6)]
        notifications = await trigger.evaluate(opps, config)

        assert len(notifications) == 1

    @pytest.mark.asyncio
    async def test_default_threshold_when_not_configured(self, trigger):
        notifications = await trigger.evaluate(
            [_make_opportunity(score=0.85)], {}
        )
        assert len(notifications) == 1

    # -- Trend spike detection --

    @pytest.mark.asyncio
    async def test_trend_spike_with_5_same_topic(self, trigger, user_config):
        opps = [_make_opportunity(score=0.3, topic="oauth", opp_id=f"opp_{i}") for i in range(5)]
        notifications = await trigger.evaluate(opps, user_config)

        trend_notifications = [n for n in notifications if n.trigger_type == "trend_spike"]
        assert len(trend_notifications) == 1
        assert "oauth" in trend_notifications[0].title
        assert "5" in trend_notifications[0].body

    @pytest.mark.asyncio
    async def test_no_trend_spike_with_4_same_topic(self, trigger, user_config):
        opps = [_make_opportunity(score=0.3, topic="oauth", opp_id=f"opp_{i}") for i in range(4)]
        notifications = await trigger.evaluate(opps, user_config)

        trend_notifications = [n for n in notifications if n.trigger_type == "trend_spike"]
        assert len(trend_notifications) == 0

    @pytest.mark.asyncio
    async def test_trend_spike_custom_min_count(self, user_config):
        trigger = TrendAlertTrigger(min_trend_count=3)
        opps = [_make_opportunity(score=0.3, topic="auth", opp_id=f"opp_{i}") for i in range(3)]
        notifications = await trigger.evaluate(opps, user_config)

        trend_notifications = [n for n in notifications if n.trigger_type == "trend_spike"]
        assert len(trend_notifications) == 1

    @pytest.mark.asyncio
    async def test_no_topic_no_trend_spike(self, trigger, user_config):
        opps = [_make_opportunity(score=0.3, topic=None, opp_id=f"opp_{i}") for i in range(10)]
        notifications = await trigger.evaluate(opps, user_config)

        trend_notifications = [n for n in notifications if n.trigger_type == "trend_spike"]
        assert len(trend_notifications) == 0

    @pytest.mark.asyncio
    async def test_mixed_high_score_and_trend(self, trigger, user_config):
        opps = [
            _make_opportunity(score=0.9, topic="oauth", opp_id=f"high_{i}")
            for i in range(5)
        ]
        notifications = await trigger.evaluate(opps, user_config)

        score_alerts = [n for n in notifications if n.trigger_type.startswith("opportunity_found")]
        trend_alerts = [n for n in notifications if n.trigger_type == "trend_spike"]
        assert len(score_alerts) == 5
        assert len(trend_alerts) == 1

    @pytest.mark.asyncio
    async def test_empty_opportunities_no_notifications(self, trigger, user_config):
        notifications = await trigger.evaluate([], user_config)
        assert notifications == []

    @pytest.mark.asyncio
    async def test_notification_includes_opportunity_metadata(self, trigger, user_config):
        opps = [_make_opportunity(score=0.85, opp_id="abc123")]
        notifications = await trigger.evaluate(opps, user_config)

        assert notifications[0].opportunity_id == "abc123"
        assert notifications[0].opportunity_score == 0.85
        assert notifications[0].opportunity_source == "test"
        assert "/opportunities/abc123" in (notifications[0].action_url or "")
