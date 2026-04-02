"""Verify Slack request signatures using HMAC-SHA256.

Slack signs every incoming request with a signing secret so we can
confirm the payload actually came from Slack and was not tampered with.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request


async def verify_slack_signature(request: Request, signing_secret: str) -> bool:
    """Return True if the request signature is valid and fresh.

    Checks:
    1. Timestamp header exists and is within 5 minutes (replay protection).
    2. HMAC-SHA256 of ``v0:{timestamp}:{body}`` matches the signature header.
    """
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        return False

    # Reject requests older than 5 minutes
    try:
        ts = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - ts) > 300:
        return False

    # Read the raw body (must be cached on the request for later use)
    body = (await request.body()).decode("utf-8")

    # Compute expected signature: v0=<hex digest>
    sig_basestring = f"v0:{timestamp}:{body}"
    expected = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected, signature)
