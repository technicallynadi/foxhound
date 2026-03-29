"""Channel identity linking: connect external messaging IDs to Foxhound users.

Two linking methods:
1. Link code: user generates a code in web UI, sends "link CODE" in Slack/Discord
2. Phone match: SMS users are matched by phone number on UserProfile
"""

from __future__ import annotations

import logging
import secrets
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# In-memory link codes: {code: (user_id, created_at)}
# Production should use Redis or DB, but this works for single-instance.
_link_codes: dict[str, tuple[str, float]] = {}
LINK_CODE_TTL = 600  # 10 minutes


def generate_link_code(user_id: str) -> str:
    """Generate a 6-char alphanumeric link code for the user."""
    code = secrets.token_hex(3).upper()  # 6 hex chars
    _link_codes[code] = (user_id, time.time())
    return code


def redeem_link_code(code: str) -> str | None:
    """Redeem a link code. Returns user_id if valid, None if expired/invalid."""
    entry = _link_codes.pop(code.upper(), None)
    if not entry:
        return None
    user_id, created_at = entry
    if time.time() - created_at > LINK_CODE_TTL:
        return None
    return user_id


async def resolve_user(
    db: AsyncSession, channel: str, external_id: str
) -> str | None:
    """Resolve a Foxhound user_id from a channel + external identity."""
    result = await db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == channel,
            ChannelIdentity.external_id == external_id,
            ChannelIdentity.verified == True,
        )
    )
    identity = result.scalar_one_or_none()
    return identity.user_id if identity else None


async def resolve_by_phone(db: AsyncSession, phone: str) -> str | None:
    """Resolve user by phone number (SMS channel)."""
    # Normalize: strip spaces, ensure +
    normalized = phone.strip().replace(" ", "")
    if not normalized.startswith("+"):
        normalized = "+" + normalized

    result = await db.execute(
        select(UserProfile).where(UserProfile.phone == normalized)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None

    # Auto-create/update channel identity for SMS
    existing = await db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == "sms",
            ChannelIdentity.external_id == normalized,
        )
    )
    identity = existing.scalar_one_or_none()
    if not identity:
        identity = ChannelIdentity(
            id=str(uuid4()),
            user_id=profile.user_id,
            channel="sms",
            external_id=normalized,
            verified=True,
        )
        db.add(identity)
        await db.flush()

    return profile.user_id


async def link_identity(
    db: AsyncSession,
    user_id: str,
    channel: str,
    external_id: str,
    display_name: str | None = None,
) -> ChannelIdentity:
    """Create or update a verified channel identity."""
    result = await db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == channel,
            ChannelIdentity.external_id == external_id,
        )
    )
    identity = result.scalar_one_or_none()

    if identity:
        identity.user_id = user_id
        identity.verified = True
        if display_name:
            identity.display_name = display_name
    else:
        identity = ChannelIdentity(
            id=str(uuid4()),
            user_id=user_id,
            channel=channel,
            external_id=external_id,
            verified=True,
            display_name=display_name,
        )
        db.add(identity)

    await db.flush()
    return identity
