"""Activity logger: records agent actions for the activity feed."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from app.db.models.agent_activity import AgentActivity
from app.db.session import async_session

logger = logging.getLogger(__name__)


async def log_activity(
    user_id: str,
    event_type: str,
    title: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentActivity:
    """Log an agent activity event. Non-blocking, always succeeds."""
    try:
        async with async_session() as db:
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
