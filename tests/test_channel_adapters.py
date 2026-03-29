"""Tests for channel adapters: webhook verification, identity linking, webhook handlers."""

import hashlib
import hmac
import json
import time
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.channel.verification import verify_slack, verify_twilio
from app.services.channel.linking import (
    generate_link_code,
    redeem_link_code,
    resolve_user,
    resolve_by_phone,
    link_identity,
)


# ---------------------------------------------------------------------------
# Slack signature verification
# ---------------------------------------------------------------------------

def test_slack_verify_valid():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.slack_signing_secret = "test_secret"

        body = b'{"type":"url_verification","challenge":"xyz"}'
        ts = str(int(time.time()))
        basestring = f"v0:{ts}:{body.decode()}"
        sig = "v0=" + hmac.new(b"test_secret", basestring.encode(), hashlib.sha256).hexdigest()

        assert verify_slack(body, ts, sig) is True


def test_slack_verify_invalid():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.slack_signing_secret = "test_secret"
        assert verify_slack(b"body", str(int(time.time())), "v0=bad") is False


def test_slack_verify_old_timestamp():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.slack_signing_secret = "test_secret"
        old_ts = str(int(time.time()) - 600)
        assert verify_slack(b"body", old_ts, "v0=anything") is False


def test_slack_verify_skip_in_dev():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = True
        assert verify_slack(b"anything", "", "") is True


def test_slack_verify_no_secret():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.slack_signing_secret = ""
        assert verify_slack(b"body", str(int(time.time())), "v0=x") is False


# ---------------------------------------------------------------------------
# Twilio signature verification
# ---------------------------------------------------------------------------

def test_twilio_verify_valid():
    import base64

    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.twilio_auth_token = "test_token"

        url = "https://foxhound.com/api/v1/webhooks/sms"
        params = {"Body": "hello", "From": "+1234"}
        data = url + "Body" + "hello" + "From" + "+1234"
        sig = base64.b64encode(
            hmac.new(b"test_token", data.encode(), hashlib.sha1).digest()
        ).decode()

        assert verify_twilio(url, params, sig) is True


def test_twilio_verify_invalid():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = False
        mock.twilio_auth_token = "test_token"
        assert verify_twilio("https://x.com", {"Body": "hi"}, "badsig") is False


def test_twilio_verify_skip():
    with patch("app.services.channel.verification.settings") as mock:
        mock.skip_webhook_verify = True
        assert verify_twilio("", {}, "") is True


# ---------------------------------------------------------------------------
# Link code generation and redemption
# ---------------------------------------------------------------------------

def test_link_code_generate_and_redeem():
    uid = str(uuid4())
    code = generate_link_code(uid)
    assert len(code) == 6
    assert redeem_link_code(code) == uid


def test_link_code_single_use():
    uid = str(uuid4())
    code = generate_link_code(uid)
    redeem_link_code(code)
    assert redeem_link_code(code) is None


def test_link_code_invalid():
    assert redeem_link_code("BADCODE") is None


def test_link_code_expired():
    from app.services.channel import linking
    uid = str(uuid4())
    code = generate_link_code(uid)
    # Manually expire
    linking._link_codes[code] = (uid, time.time() - 700)
    assert redeem_link_code(code) is None


# ---------------------------------------------------------------------------
# Identity resolution (DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_user_not_found(db):
    result = await resolve_user(db, "slack", "unknown_slack_id")
    assert result is None


@pytest.mark.asyncio
async def test_link_and_resolve(db, user_id):
    await link_identity(db, user_id, "slack", "U12345", "Test User")
    await db.commit()
    result = await resolve_user(db, "slack", "U12345")
    assert result == user_id


@pytest.mark.asyncio
async def test_resolve_by_phone(db, user_id):
    """Resolve user by a unique phone number."""
    from app.db.models.user_profile import UserProfile
    unique_phone = "+15559990001"
    profile = UserProfile(
        id=str(uuid4()), user_id=user_id, email="phone_test@test.com",
        phone=unique_phone, tier="pro", monthly_apply_limit=50,
    )
    db.add(profile)
    await db.commit()
    result = await resolve_by_phone(db, unique_phone)
    assert result == user_id


@pytest.mark.asyncio
async def test_resolve_by_phone_not_found(db):
    result = await resolve_by_phone(db, "+19999999999")
    assert result is None


@pytest.mark.asyncio
async def test_link_identity_upsert(db, user_id):
    """Linking same external_id again updates instead of duplicating."""
    await link_identity(db, user_id, "discord", "D999", "First")
    await db.commit()
    new_uid = str(uuid4())
    await link_identity(db, new_uid, "discord", "D999", "Second")
    await db.commit()
    result = await resolve_user(db, "discord", "D999")
    assert result == new_uid


# ---------------------------------------------------------------------------
# Slack webhook endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slack_url_verification():
    """Slack URL verification challenge returns the challenge token."""
    with patch("app.api.routes.agent_webhooks.verify_slack", return_value=True):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/slack",
                json={"type": "url_verification", "challenge": "test_challenge_123"},
            )
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "test_challenge_123"


@pytest.mark.asyncio
async def test_slack_invalid_signature():
    """Invalid Slack signature returns 401."""
    with patch("app.api.routes.agent_webhooks.verify_slack", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/slack",
                json={"event": {"text": "hello", "user": "U123"}},
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_slack_unknown_user():
    """Unknown Slack user gets link instructions."""
    with patch("app.api.routes.agent_webhooks.verify_slack", return_value=True):
        with patch("app.api.routes.agent_webhooks.resolve_user", new_callable=AsyncMock, return_value=None):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/webhooks/slack",
                    json={"event": {"text": "hello", "user": "UNKNOWN"}},
                )
    assert resp.status_code == 200
    assert "link" in resp.json()["text"].lower()


@pytest.mark.asyncio
async def test_slack_known_user(db, sample_profile):
    """Known Slack user gets agent response."""
    await link_identity(db, sample_profile.user_id, "slack", "UKNOWN_TEST", "Test")
    await db.commit()

    mock_result = {"response": "I found 3 matching jobs!", "session_id": "s1"}

    with patch("app.api.routes.agent_webhooks.verify_slack", return_value=True):
        with patch("app.api.routes.agent_webhooks.resolve_user", new_callable=AsyncMock, return_value=sample_profile.user_id):
            with patch("app.api.routes.agent_webhooks.agent.respond", new_callable=AsyncMock, return_value=mock_result):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/webhooks/slack",
                        json={"event": {"text": "find me jobs", "user": "UKNOWN_TEST"}},
                    )
    assert resp.status_code == 200
    assert "3 matching jobs" in resp.json()["text"]


# ---------------------------------------------------------------------------
# Discord webhook endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discord_ping():
    """Discord PING returns type 1."""
    with patch("app.api.routes.agent_webhooks.verify_discord", return_value=True):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/discord",
                json={"type": 1},
            )
    assert resp.status_code == 200
    assert resp.json()["type"] == 1


@pytest.mark.asyncio
async def test_discord_invalid_signature():
    with patch("app.api.routes.agent_webhooks.verify_discord", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/discord",
                json={"type": 2, "data": {"name": "hello"}, "member": {"user": {"id": "D1"}}},
            )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SMS webhook endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sms_invalid_signature():
    with patch("app.api.routes.agent_webhooks.verify_twilio", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/sms",
                data={"Body": "hello", "From": "+1234567890"},
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sms_unknown_number():
    with patch("app.api.routes.agent_webhooks.verify_twilio", return_value=True):
        with patch("app.api.routes.agent_webhooks.resolve_by_phone", new_callable=AsyncMock, return_value=None):
            with patch("app.api.routes.agent_webhooks.resolve_user", new_callable=AsyncMock, return_value=None):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/webhooks/sms",
                        data={"Body": "hello", "From": "+19999999999"},
                    )
    assert resp.status_code == 200
    assert "unknown" in resp.json()["message"].lower()
