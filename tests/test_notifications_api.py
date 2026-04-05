"""Security tests for notification routes (user scoping + auth edge cases)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.notification_destination import NotificationDestination
from app.main import app


def _set_test_user(user_id: str) -> None:
    from app.main import app as fastapi_app
    from app.services.auth_service import get_current_user

    override_fn = fastapi_app.dependency_overrides.get(get_current_user)
    if override_fn:
        override_fn._test_user_id = user_id


@pytest.mark.asyncio
async def test_list_notifications_scoped_by_user(db):
    user_a = str(uuid4())
    user_b = str(uuid4())
    own_delivery_id = f"nd_{uuid4().hex[:10]}"
    other_delivery_id = f"nd_{uuid4().hex[:10]}"

    db.add_all(
        [
            NotificationDelivery(
                id=own_delivery_id,
                user_id=user_a,
                run_id=f"run_{uuid4().hex[:8]}",
                channel="slack",
                source_event="run.completed",
                status="sent",
                created_at=datetime.now(UTC),
            ),
            NotificationDelivery(
                id=other_delivery_id,
                user_id=user_b,
                run_id=f"run_{uuid4().hex[:8]}",
                channel="discord",
                source_event="run.failed",
                status="failed",
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await db.commit()

    _set_test_user(user_a)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/notifications")

    assert resp.status_code == 200
    delivery_ids = [item["delivery_id"] for item in resp.json()["deliveries"]]
    assert own_delivery_id in delivery_ids
    assert other_delivery_id not in delivery_ids


@pytest.mark.asyncio
async def test_get_notification_hides_other_users_records(db):
    user_a = str(uuid4())
    user_b = str(uuid4())
    other_delivery_id = f"nd_{uuid4().hex[:10]}"

    db.add(
        NotificationDelivery(
            id=other_delivery_id,
            user_id=user_b,
            run_id=f"run_{uuid4().hex[:8]}",
            channel="slack",
            source_event="run.completed",
            status="sent",
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()

    _set_test_user(user_a)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/notifications/{other_delivery_id}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_notification_destinations_scoped_by_user(db):
    user_a = str(uuid4())
    user_b = str(uuid4())
    own_destination_id = f"dest_{uuid4().hex[:10]}"
    other_destination_id = f"dest_{uuid4().hex[:10]}"

    db.add_all(
        [
            NotificationDestination(
                id=own_destination_id,
                user_id=user_a,
                label="My Slack",
                channel="slack",
                audience_type="human",
                destination_config_json='{"webhook_url":"https://hooks.slack.test/a"}',
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
            NotificationDestination(
                id=other_destination_id,
                user_id=user_b,
                label="Other Slack",
                channel="slack",
                audience_type="human",
                destination_config_json='{"webhook_url":"https://hooks.slack.test/b"}',
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ]
    )
    await db.commit()

    _set_test_user(user_a)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/notification-destinations")

    assert resp.status_code == 200
    destination_ids = [item["destination_id"] for item in resp.json()["destinations"]]
    assert own_destination_id in destination_ids
    assert other_destination_id not in destination_ids


@pytest.mark.asyncio
async def test_notifications_reject_missing_authenticated_user_id():
    _set_test_user("")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/notifications")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authenticated user id missing"


@pytest.mark.asyncio
async def test_notification_destinations_reject_missing_authenticated_user_id():
    _set_test_user("")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/notification-destinations",
            json={
                "label": "Slack",
                "channel": "slack",
                "audience_type": "human",
                "event_types": [],
                "value": "https://hooks.slack.test/a",
                "active": True,
            },
        )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authenticated user id missing"
