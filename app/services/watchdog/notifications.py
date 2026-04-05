"""Watchdog-specific notification messages.

Uses the existing channel infrastructure from apply/notifications.py:
_get_user_channels(), _post_webhook(), send_slack_blocks().

Only fires on meaningful status transitions (active->removed, etc.).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.db.session import async_session
from app.services.notification_service import _post_webhook, send_slack_blocks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

MESSAGES = {
    "removed": (
        "The {title} role at {company} was taken down. "
        "This often means they're reviewing applications — stay ready."
    ),
    "edited": (
        "The posting for {title} at {company} was updated. "
        "{diff_summary}"
    ),
    "reposted": (
        "{company} reposted the {title} role. "
        "Your original application may be on file, or you can re-apply."
    ),
}


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def send_watchdog_alert(
    application: Application,
    job: JobListing,
    old_status: str,
    new_status: str,
    diff_summary: str | None,
) -> dict:
    """Send a watchdog status change notification."""
    async with async_session() as db:
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == application.user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return {"skipped": "no profile"}

    from app.services.apply.notifications import _get_user_channels

    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    template = MESSAGES.get(new_status)
    if not template:
        return {"skipped": f"no template for {new_status}"}

    message = template.format(
        title=job.title,
        company=job.company,
        diff_summary=diff_summary or "Check the posting for details.",
    )

    # Prefix with Foxhound branding
    message = f"[Foxhound Watchdog] {message}"

    results: dict = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            results["slack"] = await _send_slack_watchdog(
                webhook_url, message, job, application, new_status, diff_summary
            )
        elif channel == "discord":
            results["discord"] = await _send_discord_watchdog(
                webhook_url, message, job, application, new_status, diff_summary
            )
        elif channel == "sms":
            sms = f"Foxhound: {job.company} - {job.title} posting {new_status}."
            results["sms"] = await _post_webhook(
                webhook_url, {"text": sms, "to": getattr(profile, "phone", "") or ""}
            )

    return results


# ---------------------------------------------------------------------------
# Channel-specific formatters
# ---------------------------------------------------------------------------


async def _send_slack_watchdog(
    webhook_url: str,
    message: str,
    job: JobListing,
    application: Application,
    status: str,
    diff_summary: str | None,
) -> dict:
    """Send watchdog alert to Slack with Block Kit formatting."""
    days_since = _days_since_applied(application)

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{message}*"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Status:* {status}"},
                {"type": "mrkdwn", "text": f"*Days since applied:* {days_since}"},
                {"type": "mrkdwn", "text": f"*ATS:* {job.ats_type or 'unknown'}"},
            ],
        },
    ]
    if diff_summary:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Changes:* {diff_summary[:500]}",
                },
            }
        )

    return await send_slack_blocks(webhook_url, blocks, fallback_text=message)


async def _send_discord_watchdog(
    webhook_url: str,
    message: str,
    job: JobListing,
    application: Application,
    status: str,
    diff_summary: str | None,
) -> dict:
    """Send watchdog alert to Discord with embed."""
    color_map = {"removed": 0xFF4444, "edited": 0xFFA500, "reposted": 0x36A64F}
    days_since = _days_since_applied(application)

    embed: dict = {
        "title": f"Posting {status}: {job.company} -- {job.title}",
        "color": color_map.get(status, 0x888888),
        "fields": [
            {"name": "Status", "value": status, "inline": True},
            {"name": "Days Since Applied", "value": str(days_since), "inline": True},
        ],
    }
    if diff_summary:
        embed["fields"].append({"name": "Changes", "value": diff_summary[:1000]})

    return await _post_webhook(
        webhook_url, {"content": message, "embeds": [embed]}
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _days_since_applied(application: Application) -> int:
    ref = application.submitted_at or application.created_at
    if not ref:
        return 0
    delta = datetime.now(UTC) - ref
    return max(0, delta.days)
