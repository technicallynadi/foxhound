"""Webhook signature verification for Slack, Discord, and Twilio.

Each function returns True if the request signature is valid.
In dev mode (FOXHOUND_SKIP_WEBHOOK_VERIFY=1), verification is skipped.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)


def verify_slack(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature (HMAC-SHA256).

    Slack sends:
    - X-Slack-Request-Timestamp: unix timestamp
    - X-Slack-Signature: v0=<hex digest>

    We compute: v0=HMAC-SHA256(signing_secret, "v0:{timestamp}:{body}")
    """
    if settings.skip_webhook_verify:
        return True

    secret = settings.slack_signing_secret
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not configured")
        return False

    # Reject requests older than 5 minutes (replay protection)
    try:
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("Slack request timestamp too old")
            return False
    except (ValueError, TypeError):
        return False

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        secret.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


def verify_discord(body: bytes, signature: str, timestamp: str) -> bool:
    """Verify Discord interaction signature (Ed25519).

    Discord sends:
    - X-Signature-Ed25519: hex-encoded signature
    - X-Signature-Timestamp: timestamp string

    We verify: Ed25519(public_key, timestamp + body) == signature
    """
    if settings.skip_webhook_verify:
        return True

    public_key_hex = settings.discord_public_key
    if not public_key_hex:
        logger.warning("DISCORD_PUBLIC_KEY not configured")
        return False

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        message = timestamp.encode() + body
        public_key.verify(bytes.fromhex(signature), message)
        return True
    except ImportError:
        # cryptography not installed — fall back to nacl
        try:
            from nacl.signing import VerifyKey
            vk = VerifyKey(bytes.fromhex(public_key_hex))
            vk.verify(timestamp.encode() + body, bytes.fromhex(signature))
            return True
        except ImportError:
            logger.error("Neither cryptography nor PyNaCl installed for Discord verification")
            return False
        except Exception:
            return False
    except Exception:
        return False


def verify_twilio(url: str, params: dict[str, str], signature: str) -> bool:
    """Verify Twilio request signature (HMAC-SHA1).

    Twilio sends X-Twilio-Signature: base64-encoded HMAC-SHA1.
    Message = URL + sorted param key-value pairs concatenated.
    """
    if settings.skip_webhook_verify:
        return True

    auth_token = settings.twilio_auth_token
    if not auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not configured")
        return False

    import base64

    # Build the data string: URL + sorted params
    data = url
    for key in sorted(params.keys()):
        data += key + params[key]

    computed = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()

    return hmac.compare_digest(computed, signature)
