import json
import uuid

from sqlalchemy import select

from app.db.models.foxhound_run import FoxhoundRun
from app.db.models.notification_delivery import NotificationDelivery
from app.db.session import async_session
from app.services.notification_service import deliver_event_notifications, deliver_run_notifications
from app.services.run_service import _build_run_output, _load_json


def _to_response(row: NotificationDelivery) -> dict:
    return {
        "delivery_id": row.id,
        "run_id": row.run_id,
        "channel": row.channel,
        "source_event": row.source_event,
        "status": row.status,
        "retry_of_delivery_id": row.retry_of_delivery_id,
        "attempt_number": row.attempt_number,
        "message": row.message,
        "http_status": row.http_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_notification_deliveries(limit: int = 100, run_id: str | None = None) -> list[dict]:
    async with async_session() as session:
        stmt = select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc()).limit(limit)
        if run_id:
            stmt = stmt.where(NotificationDelivery.run_id == run_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [_to_response(row) for row in rows]


async def get_notification_delivery(delivery_id: str) -> dict | None:
    async with async_session() as session:
        row = await session.get(NotificationDelivery, delivery_id)
        if not row:
            return None
    return _to_response(row)


async def retry_notification_delivery(delivery_id: str) -> dict | None:
    async with async_session() as session:
        delivery = await session.get(NotificationDelivery, delivery_id)
        if not delivery:
            return None
        run = await session.get(FoxhoundRun, delivery.run_id)
        if not run:
            return None

        notify_config = {delivery.channel: True}
        destination_config = _load_json(run.notification_destinations_json, {})
        result = _load_json(run.result_json, None)
        output = _build_run_output(run.query, result) if result else None

        if delivery.source_event in {"run.completed", "run.failed"}:
            notification_state = await deliver_run_notifications(
                run_id=run.id,
                query=run.query,
                status=run.status,
                notify_config=notify_config,
                destination_config=destination_config,
                output=output,
            )
        else:
            payload = _payload_for_event(run.events_json, delivery.source_event)
            notification_state = await deliver_event_notifications(
                run_id=run.id,
                query=run.query,
                notify_config=notify_config,
                destination_config=destination_config,
                event_type=delivery.source_event,
                payload=payload,
                output=output,
            )

        state = notification_state.get(delivery.channel, {})
        new_row = NotificationDelivery(
            id=f"nd_{uuid.uuid4().hex[:10]}",
            run_id=delivery.run_id,
            channel=delivery.channel,
            source_event=delivery.source_event,
            status=state.get("status", "unknown"),
            retry_of_delivery_id=delivery.id,
            attempt_number=(delivery.attempt_number or 1) + 1,
            message=state.get("message"),
            http_status=state.get("http_status"),
        )
        session.add(new_row)
        await session.commit()
        await session.refresh(new_row)
    return _to_response(new_row)


def _payload_for_event(events_json: str | None, source_event: str) -> dict:
    events = _load_json(events_json, [])
    for event in reversed(events):
        if event.get("event_type") == source_event:
            return event.get("payload", {})
    return {}
