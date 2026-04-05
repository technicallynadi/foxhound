import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.notification_destination import NotificationDestination
from app.db.session import async_session


def _load_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _mask_destination(channel: str, config: dict) -> dict:
    if channel in {"discord", "slack"}:
        return {"configured": bool(config.get("webhook_url"))}
    if channel == "sms":
        phone = config.get("phone_number", "")
        digits = "".join(ch for ch in phone if ch.isdigit())
        return {"phone_number": f"***{digits[-4:]}" if len(digits) >= 4 else ""}
    return {}


def _require_user_id(user_id: str) -> str:
    normalized = str(user_id or "").strip()
    if not normalized:
        raise ValueError("user_id is required")
    return normalized


def _to_response(row: NotificationDestination) -> dict:
    config = _load_json(row.destination_config_json, {})
    return {
        "destination_id": row.id,
        "label": row.label,
        "channel": row.channel,
        "audience_type": row.audience_type or "human",
        "event_types": config.get("event_types", []),
        "active": row.active,
        "details": _mask_destination(row.channel, config),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create_notification_destination(request: dict) -> dict:
    user_id = _require_user_id(str(request.get("user_id") or ""))
    channel = request["channel"]
    raw = request.get("value", "").strip()
    audience_type = (request.get("audience_type") or "human").strip() or "human"
    config = {}
    if channel in {"discord", "slack"}:
        config["webhook_url"] = raw
    elif channel == "sms":
        config["phone_number"] = raw
    config["event_types"] = [str(item).strip() for item in (request.get("event_types") or []) if str(item).strip()]

    row = NotificationDestination(
        id=f"dest_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        label=(request.get("label") or f"{channel} destination").strip()[:120],
        channel=channel,
        audience_type=audience_type,
        destination_config_json=json.dumps(config),
        active=bool(request.get("active", True)),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with async_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _to_response(row)


async def list_notification_destinations(active_only: bool = False, user_id: str = "") -> list[dict]:
    scoped_user_id = _require_user_id(user_id)
    async with async_session() as session:
        stmt = (
            select(NotificationDestination)
            .where(NotificationDestination.user_id == scoped_user_id)
            .order_by(NotificationDestination.updated_at.desc())
        )
        if active_only:
            stmt = stmt.where(NotificationDestination.active.is_(True))
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [_to_response(row) for row in rows]


async def resolve_notification_destinations(destination_ids: list[str]) -> dict:
    if not destination_ids:
        return {}
    async with async_session() as session:
        result = await session.execute(
            select(NotificationDestination).where(NotificationDestination.id.in_(destination_ids))
        )
        rows = result.scalars().all()

    resolved = {}
    for row in rows:
        config = _load_json(row.destination_config_json, {})
        if row.channel == "discord" and config.get("webhook_url"):
            resolved["discord_webhook_url"] = config["webhook_url"]
            resolved["discord_audience_type"] = row.audience_type or "human"
            resolved["discord_event_types"] = config.get("event_types", [])
        elif row.channel == "slack" and config.get("webhook_url"):
            resolved["slack_webhook_url"] = config["webhook_url"]
            resolved["slack_audience_type"] = row.audience_type or "human"
            resolved["slack_event_types"] = config.get("event_types", [])
        elif row.channel == "sms" and config.get("phone_number"):
            resolved["sms_phone_number"] = config["phone_number"]
            resolved["sms_audience_type"] = row.audience_type or "human"
            resolved["sms_event_types"] = config.get("event_types", [])
    return resolved
