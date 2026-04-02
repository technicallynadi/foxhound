"""Map Slack user IDs to Foxhound UserProfile records.

Users link their Slack account via the Settings page. This module looks
up the mapping and stores new links.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile


async def get_foxhound_user(
    slack_user_id: str,
    db: AsyncSession,
) -> UserProfile | None:
    """Look up a Foxhound user by their linked Slack user ID.

    If no linked user is found and only one profile exists (single-user / beta),
    auto-link that profile to this Slack user ID.

    Returns the UserProfile if found, or None.
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.slack_user_id == slack_user_id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        return profile

    # Auto-link: if there's exactly one profile, link it automatically
    all_profiles = await db.execute(select(UserProfile))
    profiles = all_profiles.scalars().all()
    if len(profiles) == 1:
        profiles[0].slack_user_id = slack_user_id
        await db.commit()
        return profiles[0]

    return None


async def link_slack_user(
    foxhound_user_id: str,
    slack_user_id: str,
    db: AsyncSession,
) -> UserProfile | None:
    """Store the Slack user ID on a Foxhound user profile.

    Returns the updated UserProfile, or None if the user was not found.
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == foxhound_user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return None

    profile.slack_user_id = slack_user_id
    await db.commit()
    return profile
