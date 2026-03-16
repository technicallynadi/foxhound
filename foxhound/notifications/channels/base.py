"""Base notification channel protocol and notification model."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Notification(BaseModel):
    """A notification to send to the user."""

    notification_id: str
    title: str
    body: str
    priority: str = Field(default="normal", description="low, normal, high, critical")
    trigger_type: str = Field(..., description="Event that triggered this notification")
    action_url: str | None = None
    unsubscribe_url: str | None = None
    source_event_id: str | None = None
    timestamp: datetime

    # Opportunity-specific fields
    opportunity_id: str | None = None
    opportunity_score: float | None = None
    opportunity_source: str | None = None

    model_config = {"extra": "forbid"}


@runtime_checkable
class BaseNotificationChannel(Protocol):
    """Protocol that all notification channels must implement."""

    def channel_name(self) -> str:
        """Return the unique name for this channel."""
        ...

    def configure(self, config: dict) -> None:
        """Apply channel-specific configuration."""
        ...

    async def send(self, notification: Notification) -> bool:
        """Send a notification. Returns True on success."""
        ...
