from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.session import init_db
from app.services.auth_service import get_current_user
from app.services.notification_history_service import (
    get_notification_delivery,
    list_notification_deliveries,
    retry_notification_delivery,
)

router = APIRouter(prefix="/v1", tags=["notifications"])


def _require_user_id(user: dict) -> str:
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user id missing")
    return user_id


@router.get("/notifications")
async def list_notifications_endpoint(
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    return {"deliveries": await list_notification_deliveries(limit=limit, user_id=user_id)}


@router.get("/runs/{run_id}/notifications")
async def list_run_notifications_endpoint(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    return {
        "run_id": run_id,
        "deliveries": await list_notification_deliveries(limit=limit, run_id=run_id, user_id=user_id),
    }


@router.get("/notifications/{delivery_id}")
async def get_notification_endpoint(
    delivery_id: str,
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    delivery = await get_notification_delivery(delivery_id, user_id=user_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    return delivery


@router.post("/notifications/{delivery_id}/retry")
async def retry_notification_endpoint(
    delivery_id: str,
    user: dict = Depends(get_current_user),
):
    await init_db()
    user_id = _require_user_id(user)
    delivery = await retry_notification_delivery(delivery_id, user_id=user_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    return delivery
