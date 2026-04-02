import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth_service import get_current_user

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "impression", "click", "detail_dwell", "detail_scroll",
    "view_build_plans", "return_visit", "share", "export",
    "sandbox_create", "github_publish", "dismiss", "bounce",
}


class InteractionEventRequest(BaseModel):
    session_id: str
    opportunity_id: str
    event_type: str
    query_context: str | None = None
    display_position: int | None = None
    payload: dict = Field(default_factory=dict)
    ranker_variant: str = "heuristic"


class BatchEventRequest(BaseModel):
    events: list[InteractionEventRequest] = Field(..., max_length=50)


@router.post("/events")
async def record_events(batch: BatchEventRequest, user: dict = Depends(get_current_user)):
    """Batch-record interaction events for ML feedback.

    Frontend sends these in batches every 5 seconds or on page unload
    via navigator.sendBeacon.
    """
    from app.db.session import async_session
    from app.db.models.interaction_event import InteractionEvent

    valid_events = [e for e in batch.events if e.event_type in VALID_EVENT_TYPES]
    if not valid_events:
        return {"recorded": 0}

    try:
        async with async_session() as session:
            for event in valid_events:
                row = InteractionEvent(
                    session_id=event.session_id,
                    opportunity_id=event.opportunity_id,
                    event_type=event.event_type,
                    query_context=event.query_context,
                    display_position=event.display_position,
                    payload_json=json.dumps(event.payload),
                    ranker_variant=event.ranker_variant,
                )
                session.add(row)
            await session.commit()
    except Exception as e:
        logger.warning("Failed to record feedback events: %s", e)
        return {"recorded": 0, "error": "Failed to record events. Please try again."}

    return {"recorded": len(valid_events)}
