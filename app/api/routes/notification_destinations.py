from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.session import init_db
from app.services.auth_service import get_current_user
from app.services.notification_destination_service import (
    create_notification_destination,
    list_notification_destinations,
)

router = APIRouter(prefix="/v1", tags=["notification-destinations"])


class NotificationDestinationCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    channel: str = Field(..., pattern="^(discord|slack|sms)$")
    audience_type: str = Field(default="human", pattern="^(human|agent|hybrid)$")
    event_types: list[str] = Field(default_factory=list)
    value: str = Field(..., min_length=1, max_length=500)
    active: bool = Field(default=True)


def _require_user_id(user: dict) -> str:
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user id missing")
    return user_id


@router.post("/notification-destinations")
async def create_notification_destination_endpoint(
    request: NotificationDestinationCreateRequest,
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    return await create_notification_destination({**request.model_dump(), "user_id": user_id})


@router.get("/notification-destinations")
async def list_notification_destinations_endpoint(
    active_only: bool = Query(True),
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    return {"destinations": await list_notification_destinations(active_only=active_only, user_id=user_id)}
