"""Trend alert triggers for Scout opportunities."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from foxhound.notifications.channels.base import Notification

if TYPE_CHECKING:
    from foxhound.scout.connectors.base import RawOpportunity

logger = logging.getLogger(__name__)


class TrendAlertTrigger:
    """Generates notifications when Scout finds notable opportunities."""

    def __init__(self, min_trend_count: int = 5) -> None:
        self._min_trend_count = min_trend_count

    async def evaluate(
        self,
        new_opportunities: list[RawOpportunity],
        user_config: dict,
    ) -> list[Notification]:
        """Evaluate new opportunities and generate notifications for notable ones."""
        notifications: list[Notification] = []
        score_threshold = (
            user_config.get("notifications", {}).get("min_score_alert", 0.8)
        )

        for opp in new_opportunities:
            score = opp.raw_metadata.get("computed_score", 0)

            if score >= score_threshold:
                priority = self._score_to_priority(score)
                trigger_type = (
                    "opportunity_found_critical" if score >= 0.95
                    else "opportunity_found_high"
                )
                opp_id = str(opp.raw_metadata.get("id", ""))

                notifications.append(Notification(
                    notification_id=f"opp_alert_{opp_id}",
                    title=f"New opportunity ({score:.2f})",
                    body=opp.title,
                    priority=priority,
                    trigger_type=trigger_type,
                    action_url=f"/opportunities/{opp_id}",
                    opportunity_id=opp_id,
                    opportunity_score=score,
                    opportunity_source=opp.source_type,
                    timestamp=datetime.now(timezone.utc),
                ))

        # Trend spike detection
        topic_counts = self._count_by_topic(new_opportunities)
        for topic, count in topic_counts.items():
            if count >= self._min_trend_count:
                notifications.append(Notification(
                    notification_id=f"trend_{topic}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    title=f"Trending: {topic}",
                    body=f"{count} new opportunities related to {topic} discovered this cycle",
                    priority="high",
                    trigger_type="trend_spike",
                    timestamp=datetime.now(timezone.utc),
                ))

        return notifications

    def _score_to_priority(self, score: float) -> str:
        if score >= 0.95:
            return "critical"
        if score >= 0.9:
            return "high"
        return "normal"

    def _count_by_topic(self, opportunities: list[RawOpportunity]) -> dict[str, int]:
        """Count opportunities by topic tag from raw_metadata."""
        topics: Counter[str] = Counter()
        for opp in opportunities:
            topic = opp.raw_metadata.get("topic")
            if topic:
                topics[topic] += 1
        return dict(topics)
