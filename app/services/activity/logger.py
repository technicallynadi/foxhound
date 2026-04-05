"""Activity logger: records agent actions for the activity feed."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db.models.agent_activity import AgentActivity
from app.db.session import async_session

logger = logging.getLogger(__name__)


async def log_activity(
    user_id: str,
    event_type: str,
    title: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    dedup_minutes: int = 5,
) -> AgentActivity | None:
    """Log an agent activity event. Deduplicates within a time window."""
    try:
        async with async_session() as db:
            # Dedup: skip if same user + event_type + title within the window
            if dedup_minutes > 0:
                cutoff = datetime.now(UTC) - timedelta(minutes=dedup_minutes)
                existing = await db.execute(
                    select(AgentActivity.id)
                    .where(
                        AgentActivity.user_id == user_id,
                        AgentActivity.event_type == event_type,
                        AgentActivity.title == title,
                        AgentActivity.created_at >= cutoff,
                    )
                    .limit(1)
                )
                if existing.scalar_one_or_none():
                    return None  # Duplicate, skip

            activity = AgentActivity(
                id=str(uuid4()),
                user_id=user_id,
                event_type=event_type,
                title=title,
                description=description,
                metadata_json=json.dumps(metadata) if metadata else None,
            )
            db.add(activity)
            await db.commit()
            return activity
    except Exception:
        logger.exception("Failed to log activity: %s", title)
        return None
