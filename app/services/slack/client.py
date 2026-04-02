"""Async Slack API client using httpx.

All methods use the Bot Token (xoxb-...) from settings for authorization.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.slack_bot_token}"}


async def send_message(
    channel: str,
    text: str,
    blocks: list[dict] | None = None,
) -> dict:
    """Send a message to a Slack channel via chat.postMessage.

    Returns the Slack API response dict.
    """
    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers=_auth_headers(),
            json=payload,
        )
        data = resp.json()

    if not data.get("ok"):
        logger.error("Slack chat.postMessage failed: %s", data.get("error"))
    return data


async def send_reply(
    channel: str,
    thread_ts: str,
    text: str,
    blocks: list[dict] | None = None,
) -> dict:
    """Reply in a thread via chat.postMessage with thread_ts."""
    payload: dict = {
        "channel": channel,
        "text": text,
        "thread_ts": thread_ts,
    }
    if blocks:
        payload["blocks"] = blocks

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers=_auth_headers(),
            json=payload,
        )
        data = resp.json()

    if not data.get("ok"):
        logger.error("Slack thread reply failed: %s", data.get("error"))
    return data


async def upload_file(
    channel: str,
    file_bytes: bytes,
    filename: str,
    thread_ts: str | None = None,
) -> dict:
    """Upload a file to a Slack channel via files.uploadV2.

    Uses multipart form upload. Optionally threads the upload.
    """
    data_fields: dict[str, str] = {
        "channel_id": channel,
        "filename": filename,
    }
    if thread_ts:
        data_fields["thread_ts"] = thread_ts

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SLACK_API_BASE}/files.uploadV2",
            headers=_auth_headers(),
            data=data_fields,
            files={"file": (filename, file_bytes, "image/png")},
        )
        result = resp.json()

    if not result.get("ok"):
        logger.error("Slack files.uploadV2 failed: %s", result.get("error"))
    return result
