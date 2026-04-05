"""Slack Bot events endpoint.

POST /api/v1/slack/events
    - URL verification (one-time Slack setup handshake)
    - message.im events (user DMs the bot)
    - message events in channels (if bot is mentioned)

Every request is signature-verified. Message processing happens in
a background task so we always respond to Slack within <3 seconds.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.services.slack.signature import verify_slack_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/slack", tags=["slack"])


@router.post("/events")
async def slack_events(request: Request):
    """Handle incoming Slack Events API payloads.

    Returns ``{"ok": true}`` immediately. Actual message handling is
    dispatched to a background asyncio task.
    """
    # ------------------------------------------------------------------
    # Verify request signature FIRST (before processing body)
    # ------------------------------------------------------------------
    if settings.slack_signing_secret:
        if not await verify_slack_signature(request, settings.slack_signing_secret):
            raise HTTPException(status_code=403, detail="Invalid Slack signature")
    else:
        logger.warning("SLACK_SIGNING_SECRET not configured -- rejecting request")
        raise HTTPException(status_code=403, detail="Slack signing secret not configured")

    body = await request.json()

    # ------------------------------------------------------------------
    # URL verification challenge (one-time during Slack app setup)
    # ------------------------------------------------------------------
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # ------------------------------------------------------------------
    # Route event
    # ------------------------------------------------------------------
    event = body.get("event", {})
    event_type = event.get("type", "")
    logger.info(
        "Slack event received: type=%s event_type=%s user=%s text=%s",
        body.get("type"),
        event_type,
        event.get("user", event.get("event", {}).get("user")),
        event.get("event", {}).get("text", "")[:50],
    )

    # Only handle message events
    if event_type == "message":
        # Ignore bot's own messages to avoid infinite loops
        if event.get("bot_id") or event.get("subtype"):
            logger.info("Ignoring bot/subtype message")
            return {"ok": True}

        # Fire-and-forget background task
        logger.info("Dispatching message handler for user=%s", event.get("user"))
        asyncio.create_task(_handle_slack_message(event))

    return {"ok": True}


# ------------------------------------------------------------------
# Background message handler
# ------------------------------------------------------------------


async def _handle_slack_message(event: dict) -> None:
    """Process a Slack message through FoxhoundAgent and reply.

    Runs as a background task so the events endpoint can return fast.
    Uses a fresh DB session (not the request-scoped one).
    """
    slack_user_id = event.get("user", "")
    text = event.get("text", "").strip()
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")

    logger.info("Handling message: user=%s channel=%s text=%s", slack_user_id, channel, text[:50])

    if not text or not slack_user_id or not channel:
        logger.warning("Missing text/user/channel, skipping")
        return

    # Lazy imports to avoid circular imports at module load
    from app.db.session import async_session
    from app.services.slack import client as slack_client
    from app.services.slack.formatter import format_agent_response
    from app.services.slack.user_mapper import get_foxhound_user

    try:
        async with async_session() as db:
            # Map Slack user to Foxhound user
            foxhound_user = await get_foxhound_user(slack_user_id, db)
            logger.info("User lookup: slack_user=%s foxhound_user=%s", slack_user_id, foxhound_user)
            if not foxhound_user:
                await slack_client.send_reply(
                    channel,
                    thread_ts,
                    "I don't recognise your Slack account. Link it first at usefoxhound.com/settings",
                )
                return

            # Route through FoxhoundAgent (lazy import to avoid circular deps)
            from app.services.agent.agent import FoxhoundAgent

            agent = FoxhoundAgent()
            response = await agent.respond(
                db=db,
                user_id=foxhound_user.user_id,
                message=text,
                channel="slack",
            )

            # Format and send
            blocks = format_agent_response(response)
            fallback_text = response.get("response", "Done.")

            await slack_client.send_reply(
                channel,
                thread_ts,
                fallback_text,
                blocks=blocks,
            )

            # Handle screenshot uploads from tool results
            for result_entry in response.get("tool_results", []):
                result = result_entry.get("result", {})
                if not isinstance(result, dict):
                    continue
                screenshot = result.get("screenshot_bytes") or result.get("screenshot_data")
                if screenshot and isinstance(screenshot, bytes):
                    await slack_client.upload_file(
                        channel,
                        screenshot,
                        "application_screenshot.png",
                        thread_ts=thread_ts,
                    )

    except Exception:
        logger.exception("Error handling Slack message from user=%s", slack_user_id)
        try:
            from app.services.slack import client as slack_client

            await slack_client.send_reply(
                channel,
                thread_ts,
                "Something went wrong processing your request. Please try again.",
            )
        except Exception:
            logger.exception("Failed to send error message to Slack")
