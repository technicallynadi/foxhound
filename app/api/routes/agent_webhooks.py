"""Channel adapter webhooks for FoxhoundAgent.

Each channel: verify signature -> extract message -> resolve user -> call agent -> format response.
All channels feed into the same FoxhoundAgent.respond() method.
DM-only privacy model: all conversations are 1:1 private messages.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.agent.agent import FoxhoundAgent
from app.services.channel.linking import (
    link_identity,
    redeem_link_code,
    resolve_by_phone,
    resolve_user,
)
from app.services.channel.verification import verify_discord, verify_slack, verify_twilio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

agent = FoxhoundAgent()

LINK_HELP = "To connect your account, go to Foxhound settings and generate a link code, then send: link YOUR_CODE"


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


@router.post("/slack")
async def slack_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Slack event/interaction payloads."""
    body = await request.body()

    # Verify signature
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not verify_slack(body, timestamp, signature):
        raise HTTPException(401, "Invalid Slack signature")

    # Parse payload
    content_type = request.headers.get("content-type", "")
    if "form" in content_type:
        form = await request.form()
        payload = json.loads(form.get("payload", "{}"))
    else:
        payload = json.loads(body)

    # Handle URL verification challenge (Slack setup handshake)
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    # Slack retries — ack immediately to avoid duplicate processing
    if request.headers.get("x-slack-retry-num"):
        return {"ok": True}

    # Extract message text and Slack user ID
    event = payload.get("event", {})
    text = event.get("text", "")
    slack_user_id = event.get("user") or payload.get("user", {}).get("id", "")

    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return {"ok": True}

    # Try interactive payload (buttons, modals)
    if not text:
        actions = payload.get("actions", [])
        if actions:
            text = actions[0].get("value", "")
            slack_user_id = slack_user_id or payload.get("user", {}).get("id", "")

    if not text or not slack_user_id:
        return {"ok": True}

    # Handle link command
    if text.strip().lower().startswith("link "):
        code = text.strip().split(None, 1)[1].strip()
        return await _handle_link(db, "slack", slack_user_id, code, "slack")

    # Resolve Foxhound user
    user_id = await resolve_user(db, "slack", slack_user_id)
    if not user_id:
        return {"text": LINK_HELP}

    result = await agent.respond(db=db, user_id=user_id, message=text, channel="slack")
    return {"text": result["response"]}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


@router.post("/discord")
async def discord_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Discord interaction webhooks."""
    body = await request.body()

    # Verify signature
    signature = request.headers.get("x-signature-ed25519", "")
    timestamp = request.headers.get("x-signature-timestamp", "")
    if not verify_discord(body, signature, timestamp):
        raise HTTPException(401, "Invalid Discord signature")

    payload = json.loads(body)

    # PING verification (Discord setup handshake)
    if payload.get("type") == 1:
        return {"type": 1}

    # Extract user and content
    discord_user_id = ""
    if payload.get("member", {}).get("user"):
        discord_user_id = payload["member"]["user"].get("id", "")
    elif payload.get("user"):
        discord_user_id = payload["user"].get("id", "")

    content = ""

    # Slash command
    if payload.get("type") == 2:
        options = payload.get("data", {}).get("options", [])
        content = " ".join(o.get("value", "") for o in options) if options else payload.get("data", {}).get("name", "")

    # Message component interaction (button click)
    if payload.get("type") == 3:
        content = payload.get("data", {}).get("custom_id", "")

    # Modal submit
    if payload.get("type") == 5:
        components = payload.get("data", {}).get("components", [])
        for row in components:
            for comp in row.get("components", []):
                if comp.get("value"):
                    content = comp["value"]
                    break

    if not content or not discord_user_id:
        return {"type": 4, "data": {"content": "No input received."}}

    # Handle link command
    if content.strip().lower().startswith("link "):
        code = content.strip().split(None, 1)[1].strip()
        result = await _handle_link(db, "discord", discord_user_id, code, "discord")
        return {"type": 4, "data": {"content": result.get("text", result.get("message", ""))}}

    # Resolve Foxhound user
    user_id = await resolve_user(db, "discord", discord_user_id)
    if not user_id:
        return {"type": 4, "data": {"content": LINK_HELP}}

    result = await agent.respond(db=db, user_id=user_id, message=content, channel="discord")
    return {"type": 4, "data": {"content": result["response"][:2000]}}


# ---------------------------------------------------------------------------
# SMS (Twilio)
# ---------------------------------------------------------------------------


@router.post("/sms")
async def sms_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Twilio inbound SMS."""
    await request.body()

    # Parse form data
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    # Verify signature
    twilio_signature = request.headers.get("x-twilio-signature", "")
    request_url = str(request.url)
    if not verify_twilio(request_url, params, twilio_signature):
        raise HTTPException(401, "Invalid Twilio signature")

    text = params.get("Body", "").strip()
    from_number = params.get("From", "").strip()

    if not text or not from_number:
        return _twiml_response("")

    # Handle link command
    if text.lower().startswith("link "):
        code = text.split(None, 1)[1].strip()
        result = await _handle_link(db, "sms", from_number, code, "sms")
        return _twiml_response(result.get("text", result.get("message", "")))

    # Resolve user by phone number (auto-links if found)
    user_id = await resolve_by_phone(db, from_number)
    if not user_id:
        # Try channel_identities table
        user_id = await resolve_user(db, "sms", from_number)

    if not user_id:
        return _twiml_response(
            "Foxhound: Unknown number. Link your phone in Foxhound settings or reply: link YOUR_CODE"
        )

    result = await agent.respond(db=db, user_id=user_id, message=text, channel="sms")
    return _twiml_response(result["response"][:1500])


# ---------------------------------------------------------------------------
# Link code API (for web UI to generate codes)
# ---------------------------------------------------------------------------


@router.post("/link-code")
async def generate_link_code_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate a link code for the authenticated user."""
    # Get auth from header
    from fastapi.security import HTTPBearer

    from app.services.auth_service import get_current_user
    from app.services.channel.linking import generate_link_code

    security = HTTPBearer(auto_error=False)
    credentials = await security(request)
    if not credentials:
        raise HTTPException(401, "Missing authorization")
    user = await get_current_user(credentials)
    code = generate_link_code(user["user_id"])
    return {"code": code, "expires_in": 600}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _handle_link(db: AsyncSession, channel: str, external_id: str, code: str, display_channel: str) -> dict:
    """Handle a 'link CODE' message from any channel."""
    user_id = redeem_link_code(code)
    if not user_id:
        return {"text": "Invalid or expired link code. Generate a new one in Foxhound settings."}

    await link_identity(db, user_id, channel, external_id)
    await db.commit()
    logger.info("Linked %s identity for user %s", channel, user_id)
    return {"text": f"Your {display_channel} account is now linked to Foxhound. You can chat with me here."}


def _twiml_response(message: str) -> dict:
    """Return a TwiML-compatible response for Twilio.

    Twilio accepts JSON responses for messaging webhooks when
    configured for JSON. For TwiML, wrap in <Response><Message>.
    We return JSON which works with Twilio's newer webhook format.
    """
    if not message:
        return {"message": ""}
    return {"message": message}
