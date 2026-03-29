"""Settings API routes.

PUT /api/v1/settings/autopilot     — enable/disable, threshold, daily limit
PUT /api/v1/settings/notifications — channels, digest prefs
PUT /api/v1/settings/blocklist     — blacklist/whitelist companies
GET /api/v1/settings               — current settings
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AutopilotSettings(BaseModel):
    enabled: bool | None = None
    threshold: int | None = None
    daily_limit: int | None = None


class NotificationSettings(BaseModel):
    channels: list[str] | None = None
    on_apply: bool | None = None
    daily_digest: bool | None = None


class BlocklistSettings(BaseModel):
    blacklist: list[str] | None = None
    whitelist: list[str] | None = None


# ---------------------------------------------------------------------------
# GET current settings
# ---------------------------------------------------------------------------


@router.get("")
async def get_settings(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all user settings."""
    user_id = user["user_id"]
    profile = await _get_profile(db, user_id)

    return {
        "autopilot": {
            "enabled": bool(profile.autopilot_enabled),
            "threshold": profile.autopilot_threshold,
            "daily_limit": profile.daily_apply_limit,
        },
        "notifications": {
            "channels": json.loads(profile.notify_channels_json or '["email"]'),
            "on_apply": bool(profile.notify_on_apply),
            "daily_digest": bool(profile.notify_daily_digest),
        },
        "blocklist": {
            "blacklist": json.loads(profile.blacklisted_companies_json or "[]"),
            "whitelist": json.loads(profile.whitelisted_companies_json or "[]"),
        },
        "tier": profile.tier,
        "applications_this_month": profile.applications_this_month,
        "monthly_limit": profile.monthly_apply_limit,
    }


# ---------------------------------------------------------------------------
# PUT autopilot
# ---------------------------------------------------------------------------


@router.put("/autopilot")
async def update_autopilot(
    body: AutopilotSettings,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update autopilot settings."""
    user_id = user["user_id"]
    profile = await _get_profile(db, user_id)

    if profile.tier not in ("pro", "autopilot"):
        raise HTTPException(status_code=403, detail="Autopilot requires Pro or Autopilot tier.")

    changes = []
    if body.enabled is not None:
        profile.autopilot_enabled = body.enabled
        changes.append(f"autopilot {'enabled' if body.enabled else 'disabled'}")
    if body.threshold is not None:
        if body.threshold < 50 or body.threshold > 100:
            raise HTTPException(status_code=400, detail="Threshold must be 50-100.")
        profile.autopilot_threshold = body.threshold
        changes.append(f"threshold set to {body.threshold}%")
    if body.daily_limit is not None:
        if body.daily_limit < 1 or body.daily_limit > 20:
            raise HTTPException(status_code=400, detail="Daily limit must be 1-20.")
        profile.daily_apply_limit = body.daily_limit
        changes.append(f"daily limit set to {body.daily_limit}")

    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"changes": changes, "autopilot": {
        "enabled": bool(profile.autopilot_enabled),
        "threshold": profile.autopilot_threshold,
        "daily_limit": profile.daily_apply_limit,
    }}


# ---------------------------------------------------------------------------
# PUT notifications
# ---------------------------------------------------------------------------


@router.put("/notifications")
async def update_notifications(
    body: NotificationSettings,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification settings."""
    user_id = user["user_id"]
    profile = await _get_profile(db, user_id)

    changes = []
    if body.channels is not None:
        valid = {"email", "slack", "discord", "sms", "web"}
        for ch in body.channels:
            if ch not in valid:
                raise HTTPException(status_code=400, detail=f"Invalid channel: {ch}")
        profile.notify_channels_json = json.dumps(body.channels)
        changes.append(f"channels: {', '.join(body.channels)}")
    if body.on_apply is not None:
        profile.notify_on_apply = body.on_apply
        changes.append(f"on_apply {'enabled' if body.on_apply else 'disabled'}")
    if body.daily_digest is not None:
        profile.notify_daily_digest = body.daily_digest
        changes.append(f"daily_digest {'enabled' if body.daily_digest else 'disabled'}")

    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"changes": changes}


# ---------------------------------------------------------------------------
# PUT blocklist
# ---------------------------------------------------------------------------


@router.put("/blocklist")
async def update_blocklist(
    body: BlocklistSettings,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update company blacklist/whitelist."""
    user_id = user["user_id"]
    profile = await _get_profile(db, user_id)

    changes = []
    if body.blacklist is not None:
        profile.blacklisted_companies_json = json.dumps(body.blacklist)
        changes.append(f"blacklist: {len(body.blacklist)} companies")
    if body.whitelist is not None:
        profile.whitelisted_companies_json = json.dumps(body.whitelist)
        changes.append(f"whitelist: {len(body.whitelist)} companies")

    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"changes": changes}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_profile(db: AsyncSession, user_id: str) -> UserProfile:
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found. Upload your resume first.")
    return profile
