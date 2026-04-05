from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.session import init_db
from app.services.auth_service import get_current_user
from app.services.notification_history_service import get_notification_delivery, list_notification_deliveries, retry_notification_delivery

router = APIRouter(prefix="/v1", tags=["notifications"])


@router.get("/notifications")
async def list_notifications_endpoint(
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    await init_db()
    return {"deliveries": await list_notification_deliveries(limit=limit, user_id=user["user_id"])}


@router.get("/runs/{run_id}/notifications")
async def list_run_notifications_endpoint(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    await init_db()
    return {"run_id": run_id, "deliveries": await list_notification_deliveries(limit=limit, run_id=run_id, user_id=user["user_id"])}


@router.get("/notifications/{delivery_id}")
async def get_notification_endpoint(
    delivery_id: str,
    user: dict = Depends(get_current_user),
):
    await init_db()
    delivery = await get_notification_delivery(delivery_id, user_id=user["user_id"])
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    return delivery


@router.post("/notifications/{delivery_id}/retry")
async def retry_notification_endpoint(
    delivery_id: str,
    user: dict = Depends(get_current_user),
):
    await init_db()
    delivery = await retry_notification_delivery(delivery_id, user_id=user["user_id"])
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    return delivery
