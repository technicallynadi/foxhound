"""Foxhound application notification service.

Extends the existing notification infrastructure with application-specific
message types: application receipts, daily digests, conversation questions,
and status updates.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.services.notification_service import (
    _post_webhook,
    _skipped_state,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------


def _get_user_channels(profile: UserProfile) -> dict:
    """Resolve which channels the user has enabled and their webhook URLs."""
    channels = json.loads(profile.notify_channels_json or '["email"]')
    resolved = {}
    if "slack" in channels and settings.slack_webhook_url:
        resolved["slack"] = settings.slack_webhook_url
    if "discord" in channels and settings.discord_webhook_url:
        resolved["discord"] = settings.discord_webhook_url
    if "sms" in channels and settings.sms_webhook_url:
        resolved["sms"] = settings.sms_webhook_url
    return resolved


# ---------------------------------------------------------------------------
# Application receipt
# ---------------------------------------------------------------------------


async def send_application_receipt(
    profile: UserProfile,
    application: Application,
    job: JobListing,
    screenshot_url: str | None = None,
) -> dict:
    """Send a notification after an application is submitted or fails.

    Message format:
    [Foxhound] Applied to {company} — {title}
    Match: {score}% | Fields filled: {n}
    Status: Submitted / Failed (reason)
    """
    if not profile.notify_on_apply:
        return {"skipped": "notify_on_apply disabled"}

    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    # Build message
    status_emoji = "Submitted" if application.status == "submitted" else f"Failed ({application.error_type or 'unknown'})"
    fields_filled = json.loads(application.fields_filled_json or "[]")

    message = (
        f"[Foxhound] Applied to {job.company} — {job.title}\n"
        f"Status: {status_emoji}\n"
        f"Fields filled: {len(fields_filled)}\n"
        f"ATS: {job.ats_type or 'unknown'}"
    )

    if application.tinyfish_duration_ms:
        message += f"\nCompleted in {application.tinyfish_duration_ms / 1000:.1f}s"

    if screenshot_url:
        message += f"\nScreenshot: {screenshot_url}"

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            results["slack"] = await _send_slack_application(
                webhook_url, message, job, application, screenshot_url
            )
        elif channel == "discord":
            results["discord"] = await _send_discord_application(
                webhook_url, message, job, application, screenshot_url
            )
        elif channel == "sms":
            # SMS gets a shorter message
            sms_msg = f"Foxhound: Applied to {job.company} — {job.title}. Status: {status_emoji}"
            results["sms"] = await _post_webhook(
                webhook_url, {"text": sms_msg, "to": profile.phone or ""}
            )

    return results


async def _send_slack_application(
    webhook_url: str,
    message: str,
    job: JobListing,
    application: Application,
    screenshot_url: str | None,
) -> dict:
    """Send application receipt to Slack with rich formatting."""
    status_color = "#36a64f" if application.status == "submitted" else "#ff4444"
    fields_filled = json.loads(application.fields_filled_json or "[]")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Applied to {job.company} — {job.title}*",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Status:* {application.status}"},
                {"type": "mrkdwn", "text": f"*ATS:* {job.ats_type or 'unknown'}"},
                {"type": "mrkdwn", "text": f"*Fields filled:* {len(fields_filled)}"},
                {"type": "mrkdwn", "text": f"*Trigger:* {application.trigger}"},
            ],
        },
    ]

    if application.error_message:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Error:* {application.error_message[:200]}"},
        })

    if screenshot_url:
        blocks.append({
            "type": "image",
            "image_url": screenshot_url,
            "alt_text": f"Application screenshot for {job.company}",
        })

    body = {"text": message, "blocks": blocks}
    return await _post_webhook(webhook_url, body)


async def _send_discord_application(
    webhook_url: str,
    message: str,
    job: JobListing,
    application: Application,
    screenshot_url: str | None,
) -> dict:
    """Send application receipt to Discord with embed."""
    fields_filled = json.loads(application.fields_filled_json or "[]")
    color = 0x36A64F if application.status == "submitted" else 0xFF4444

    embed = {
        "title": f"Applied to {job.company} — {job.title}",
        "color": color,
        "fields": [
            {"name": "Status", "value": application.status, "inline": True},
            {"name": "ATS", "value": job.ats_type or "unknown", "inline": True},
            {"name": "Fields Filled", "value": str(len(fields_filled)), "inline": True},
            {"name": "Trigger", "value": application.trigger, "inline": True},
        ],
    }

    if application.error_message:
        embed["fields"].append({
            "name": "Error",
            "value": application.error_message[:200],
        })

    if screenshot_url:
        embed["image"] = {"url": screenshot_url}

    body = {"content": message, "embeds": [embed]}
    return await _post_webhook(webhook_url, body)


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


async def send_daily_digest(
    db: AsyncSession, user_id: str
) -> dict:
    """Send end-of-day summary to a user.

    "Today's applications (5):
     - Anthropic — Research Engineer (92% match) — Submitted
     - Stripe — Backend Engineer (87% match) — Submitted
     - Meta — SRE (81% match) — Failed (CAPTCHA)
     3 new matches above your 75% threshold for tomorrow."
    """
    # Get profile
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.notify_daily_digest:
        return {"skipped": "digest disabled or no profile"}

    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    # Get today's applications
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    app_result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(
            Application.user_id == user_id,
            Application.created_at >= today_start,
        )
        .order_by(Application.created_at.desc())
    )
    todays_apps = app_result.all()

    # Count new high-score matches
    threshold = profile.autopilot_threshold or 75
    new_matches_result = await db.execute(
        select(func.count())
        .select_from(JobMatch)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.match_score >= threshold,
            JobMatch.user_action == "none",
            JobMatch.disqualified == False,
            JobMatch.created_at >= today_start,
        )
    )
    new_match_count = new_matches_result.scalar() or 0

    # Build digest message
    lines = [f"Foxhound Daily Digest — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"]
    lines.append("")

    if todays_apps:
        lines.append(f"Today's applications ({len(todays_apps)}):")
        for app, job in todays_apps[:10]:
            status_label = app.status.replace("_", " ").title()
            if app.error_type:
                status_label = f"Failed ({app.error_type})"
            lines.append(f"  - {job.company} — {job.title} — {status_label}")
    else:
        lines.append("No applications today.")

    lines.append("")
    if new_match_count > 0:
        lines.append(f"{new_match_count} new matches above your {threshold}% threshold.")
    else:
        lines.append("No new high-score matches today.")

    # Stats
    submitted = sum(1 for app, _ in todays_apps if app.status == "submitted")
    failed = sum(1 for app, _ in todays_apps if app.status == "failed")
    if todays_apps:
        lines.append(f"\nSubmitted: {submitted} | Failed: {failed} | Remaining today: {max(0, profile.daily_apply_limit - len(todays_apps))}")

    message = "\n".join(lines)

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "sms":
            # SMS gets compact version
            sms = f"Foxhound: {len(todays_apps)} apps today ({submitted} submitted). {new_match_count} new matches."
            results["sms"] = await _post_webhook(webhook_url, {"text": sms, "to": profile.phone or ""})
        else:
            results[channel] = await _post_webhook(webhook_url, _format_digest(channel, message))

    return results


def _format_digest(channel: str, message: str) -> dict:
    if channel == "slack":
        return {
            "text": message,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            ],
        }
    elif channel == "discord":
        return {
            "content": message[:2000],
            "embeds": [{"title": "Daily Digest", "description": message[:4000]}],
        }
    return {"text": message}


# ---------------------------------------------------------------------------
# Conversation question notification
# ---------------------------------------------------------------------------


async def send_conversation_question(
    profile: UserProfile,
    application_id: str,
    job: JobListing,
    questions: list[dict],
) -> dict:
    """Send interactive question(s) to user via their preferred channel.

    Batches all questions into a single message to avoid spam.

    Each question dict has: {question, suggested_answer (optional), field_type}
    """
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    # Build message with all questions
    lines = [
        f"Foxhound needs your input for {job.company} — {job.title}",
        "",
    ]

    for i, q in enumerate(questions, 1):
        lines.append(f"Q{i}: {q['question']}")
        options = q.get("options", [])
        if options:
            lines.append(f"   Options: {' | '.join(str(o) for o in options)}")
        if q.get("suggested_answer"):
            lines.append(f"   Suggested: {q['suggested_answer']}")
            lines.append(f"   Reply 'approve {i}' to accept, or send your answer")
        elif not options:
            lines.append(f"   Please reply with your answer")
        lines.append("")

    lines.append(f"Reply within 2 hours or this application will expire.")
    lines.append(f"Reply 'cancel' to cancel this application.")

    message = "\n".join(lines)

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            results["slack"] = await _send_slack_question(
                webhook_url, message, job, questions, application_id
            )
        elif channel == "discord":
            results["discord"] = await _post_webhook(webhook_url, {
                "content": message[:2000],
                "embeds": [{
                    "title": f"Input needed: {job.company} — {job.title}",
                    "description": message[:4000],
                    "color": 0xFFA500,
                }],
            })
        elif channel == "sms":
            # SMS gets first question only
            first_q = questions[0]["question"] if questions else ""
            sms = f"Foxhound ({job.company}): {first_q} Reply with your answer."
            results["sms"] = await _post_webhook(webhook_url, {"text": sms, "to": profile.phone or ""})

    return results


async def _send_slack_question(
    webhook_url: str,
    message: str,
    job: JobListing,
    questions: list[dict],
    application_id: str,
) -> dict:
    """Send interactive questions to Slack with action buttons."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Foxhound needs your input for {job.company} — {job.title}*",
            },
        },
        {"type": "divider"},
    ]

    for i, q in enumerate(questions, 1):
        q_text = f"*Q{i}:* {q['question']}"
        if q.get("suggested_answer"):
            q_text += f"\n_Suggested:_ {q['suggested_answer']}"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": q_text},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "Reply in thread | Expires in 2 hours | Say 'cancel' to stop"},
        ],
    })

    body = {"text": message, "blocks": blocks}
    return await _post_webhook(webhook_url, body)


# ---------------------------------------------------------------------------
# Status update notifications
# ---------------------------------------------------------------------------


async def send_status_update(
    profile: UserProfile,
    job: JobListing,
    old_status: str,
    new_status: str,
) -> dict:
    """Notify user when an application status changes (e.g., needs_manual, confirmed)."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    message = f"Foxhound: {job.company} — {job.title} status changed: {old_status} -> {new_status}"

    if new_status == "needs_manual":
        message += "\nThis application needs manual completion (CAPTCHA or certification required)."
        message += f"\nApply here: {job.apply_url}"

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "sms":
            results["sms"] = await _post_webhook(webhook_url, {"text": message, "to": profile.phone or ""})
        else:
            results[channel] = await _post_webhook(webhook_url, {"text": message})

    return results


# ---------------------------------------------------------------------------
# New match alerts
# ---------------------------------------------------------------------------


async def send_new_match_alert(
    profile: UserProfile,
    new_matches: list[tuple],
) -> dict:
    """Alert user about new jobs above their threshold."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    threshold = profile.autopilot_threshold or 80
    lines = [
        f"{len(new_matches)} new job{'s' if len(new_matches) != 1 else ''} above your {threshold}% threshold:"
    ]
    for match, job in new_matches[:5]:
        lines.append(f"  - {job.company} — {job.title} ({match.match_score}% match)")
    if len(new_matches) > 5:
        lines.append(f"  + {len(new_matches) - 5} more")
    lines.append("Open Foxhound to review.")

    message = "\n".join(lines)
    results = {}
    for channel, webhook_url in channels.items():
        results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


# ---------------------------------------------------------------------------
# Follow-up messages (day 3, 7, 14)
# ---------------------------------------------------------------------------


async def send_followup_day3(
    profile: UserProfile, job: JobListing
) -> dict:
    """Day 3: normal timeline status update."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    message = f"Foxhound: Your {job.company} — {job.title} application was 3 days ago. Normal timeline for {job.ats_type or 'this company'}."

    results = {}
    for channel, webhook_url in channels.items():
        results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


async def send_followup_day7(
    profile: UserProfile, job: JobListing
) -> dict:
    """Day 7: offer to draft a follow-up."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    message = (
        f"Foxhound: It's been a week since your {job.company} — {job.title} application. "
        f"Want me to draft a follow-up to the hiring manager? Reply in the app."
    )

    results = {}
    for channel, webhook_url in channels.items():
        results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


async def send_followup_day14(
    profile: UserProfile, job: JobListing
) -> dict:
    """Day 14: suggest moving on."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    message = (
        f"Foxhound: Still no response from {job.company} after 14 days. "
        f"This is common — most rejections are silent. "
        f"Open Foxhound to see similar roles."
    )

    results = {}
    for channel, webhook_url in channels.items():
        results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results
