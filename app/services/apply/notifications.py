"""Foxhound application notification service.

Extends the existing notification infrastructure with application-specific
message types: application receipts, daily digests, conversation questions,
and status updates.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from urllib.parse import quote_plus

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.services.notification_service import (
    _post_webhook,
    send_slack_blocks,
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
# Block Kit helpers
# ---------------------------------------------------------------------------

DASHBOARD_BASE = "https://usefoxhound.com"


def _research_href(
    tab: str,
    *,
    company: str | None = None,
    role: str | None = None,
    application_id: str | None = None,
) -> str:
    params: list[str] = [f"tab={quote_plus(tab)}"]
    if company:
        params.append(f"company={quote_plus(company)}")
    if role:
        params.append(f"role={quote_plus(role)}")
    if application_id:
        params.append(f"applicationId={quote_plus(application_id)}")
    return f"{DASHBOARD_BASE}/intelligence?{'&'.join(params)}"


async def _send_slack_profile_message(
    profile: UserProfile,
    webhook_url: str,
    text: str,
    blocks: list[dict],
) -> dict:
    """Prefer a direct Slack DM so the user can reply in-channel."""
    if settings.slack_bot_token and getattr(profile, "slack_user_id", None):
        try:
            from app.services.slack.client import send_message

            result = await send_message(
                channel=profile.slack_user_id,
                text=text,
                blocks=blocks,
            )
            if result.get("ok"):
                return result
        except Exception:
            logger.exception("Slack bot DM failed; falling back to webhook")

    return await send_slack_blocks(webhook_url, blocks, fallback_text=text)


def _screenshot_public_url(storage_path: str | None) -> str | None:
    """Build a Supabase public-storage URL from a relative storage path.

    Returns ``None`` when there is no path or Supabase is not configured.
    """
    if not storage_path or not settings.supabase_url:
        return None
    base = settings.supabase_url.rstrip("/")
    path = storage_path.lstrip("/")
    return f"{base}/storage/v1/object/public/{path}"


def _build_submitted_blocks(
    job: JobListing,
    application: Application,
    screenshot_url: str | None,
) -> list[dict]:
    """Block Kit blocks for a successfully submitted application."""
    fields_filled = json.loads(application.fields_filled_json or "[]")
    scan_fields = json.loads(application.scan_result_json or "[]")
    total_fields = len(scan_fields) if scan_fields else len(fields_filled)
    resume_status = "Uploaded" if application.resume_version_path else "None"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Application Submitted"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Company:*\n{job.company}"},
                {"type": "mrkdwn", "text": f"*Role:*\n{job.title}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Fields filled:*\n{len(fields_filled)}/{total_fields}"},
                {"type": "mrkdwn", "text": f"*Resume:*\n{resume_status}"},
            ],
        },
    ]

    if application.tinyfish_duration_ms:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Completed in {application.tinyfish_duration_ms / 1000:.1f}s | ATS: {job.ats_type or 'unknown'}",
                    },
                ],
            }
        )

    # Screenshot thumbnail
    public_url = _screenshot_public_url(screenshot_url)
    if public_url:
        blocks.append(
            {
                "type": "image",
                "image_url": public_url,
                "alt_text": f"Application screenshot for {job.company}",
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Applications"},
                    "url": f"{DASHBOARD_BASE}/applications",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Research"},
                    "url": _research_href(
                        "people",
                        company=job.company,
                        role=job.title,
                        application_id=application.id,
                    ),
                },
            ],
        }
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Reply in this DM if you want Foxhound to queue the next follow-up or open more Research.",
                }
            ],
        }
    )

    return blocks


def _build_failed_blocks(
    job: JobListing,
    application: Application,
) -> list[dict]:
    """Block Kit blocks for a failed application."""
    error_reason = application.error_message or application.error_type or "Unknown error"
    if len(error_reason) > 200:
        error_reason = error_reason[:197] + "..."

    # Map common error types to actionable suggestions
    suggestion_map = {
        "captcha": "This form has a CAPTCHA. Try applying manually.",
        "login_required": "The ATS requires a login. Create an account first, then retry.",
        "timeout": "The form took too long to load. Try again during off-peak hours.",
        "network": "Network issue during submission. Retry when the ATS is available.",
    }
    suggestion = suggestion_map.get(
        (application.error_type or "").lower(),
        "Check the job posting and try again, or complete the application manually.",
    )

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Application Failed"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Company:*\n{job.company}"},
                {"type": "mrkdwn", "text": f"*Role:*\n{job.title}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reason:*\n{error_reason}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Suggestion:*\n{suggestion}"},
        },
    ]

    if job.apply_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Apply Manually"},
                        "url": job.apply_url,
                    },
                ],
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Reply here if you want Foxhound to keep tracking the role or look for better fits.",
                }
            ],
        }
    )

    return blocks


def _build_questions_blocks(
    job: JobListing,
    questions: list[dict],
    application_id: str,
) -> list[dict]:
    """Block Kit blocks for questions that need user input."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Questions for {job.company} Application",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Foxhound needs your input on *{len(questions)} "
                    f"question{'s' if len(questions) != 1 else ''}* before submitting."
                ),
            },
        },
    ]

    # Show a preview of each question (max 5 to avoid huge messages)
    for i, q in enumerate(questions[:5], 1):
        q_text = f"*Q{i}:* {q['question']}"
        if q.get("suggested_answer"):
            q_text += f"\n_Suggested:_ {q['suggested_answer']}"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": q_text},
            }
        )

    if len(questions) > 5:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"+ {len(questions) - 5} more questions"},
                ],
            }
        )

    # Tell user to reply right here in Slack
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Reply with your answers:*\n"
                + "\n".join(f"{i}. [your answer]" for i in range(1, min(len(questions) + 1, 6))),
            },
        }
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Reply in this thread and Foxhound will keep the application moving.",
                }
            ],
        }
    )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Applications"},
                    "url": f"{DASHBOARD_BASE}/applications",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Research"},
                    "url": _research_href(
                        "people",
                        company=job.company,
                        role=job.title,
                        application_id=application_id,
                    ),
                },
            ],
        }
    )

    return blocks


def _build_needs_manual_blocks(
    job: JobListing,
    application: Application,
    reason: str | None = None,
) -> list[dict]:
    """Block Kit blocks for an application that needs manual completion."""
    fields_filled = json.loads(application.fields_filled_json or "[]")
    display_reason = reason or application.error_message or "CAPTCHA or verification required"
    if len(display_reason) > 200:
        display_reason = display_reason[:197] + "..."

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Manual Completion Needed"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Company:*\n{job.company}"},
                {"type": "mrkdwn", "text": f"*Role:*\n{job.title}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Reason:*\n{display_reason}"},
                {"type": "mrkdwn", "text": f"*Fields filled:*\n{len(fields_filled)}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Foxhound filled what it could. Please complete the remaining steps manually.",
            },
        },
    ]

    apply_url = job.apply_url or f"{DASHBOARD_BASE}/applications"
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Complete Application"},
                    "url": apply_url,
                    "style": "primary",
                },
            ],
        }
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Reply here if you want Foxhound to help you find a better-fit role instead.",
                }
            ],
        }
    )

    return blocks


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
    status_emoji = (
        "Submitted" if application.status == "submitted" else f"Failed ({application.error_type or 'unknown'})"
    )
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
                profile, webhook_url, message, job, application, screenshot_url
            )
        elif channel == "discord":
            results["discord"] = await _send_discord_application(webhook_url, message, job, application, screenshot_url)
        elif channel == "sms":
            # SMS gets a shorter message
            sms_msg = f"Foxhound: Applied to {job.company} — {job.title}. Status: {status_emoji}"
            results["sms"] = await _post_webhook(webhook_url, {"text": sms_msg, "to": profile.phone or ""})

    return results


async def _send_slack_application(
    profile: UserProfile,
    webhook_url: str,
    message: str,
    job: JobListing,
    application: Application,
    screenshot_url: str | None,
) -> dict:
    """Send application receipt to Slack with Block Kit formatting."""
    if application.status == "submitted":
        blocks = _build_submitted_blocks(job, application, screenshot_url)
    else:
        blocks = _build_failed_blocks(job, application)

    return await _send_slack_profile_message(profile, webhook_url, message, blocks)


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
        embed["fields"].append(
            {
                "name": "Error",
                "value": application.error_message[:200],
            }
        )

    if screenshot_url:
        embed["image"] = {"url": screenshot_url}

    body = {"content": message, "embeds": [embed]}
    return await _post_webhook(webhook_url, body)


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


async def send_daily_digest(db: AsyncSession, user_id: str) -> dict:
    """Send end-of-day summary to a user.

    "Today's applications (5):
     - Anthropic — Research Engineer (92% match) — Submitted
     - Stripe — Backend Engineer (87% match) — Submitted
     - Meta — SRE (81% match) — Failed (CAPTCHA)
     3 new matches above your 75% threshold for tomorrow."
    """
    # Get profile
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.notify_daily_digest:
        return {"skipped": "digest disabled or no profile"}

    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels configured"}

    # Get today's applications
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
    threshold = profile.autopilot_threshold or 70
    new_matches_result = await db.execute(
        select(func.count())
        .select_from(JobMatch)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.match_score >= threshold,
            JobMatch.user_action == "none",
            JobMatch.disqualified.is_(False),
            JobMatch.created_at >= today_start,
        )
    )
    new_match_count = new_matches_result.scalar() or 0

    # Build digest message
    lines = [f"Foxhound Daily Digest — {datetime.now(UTC).strftime('%b %d, %Y')}"]
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
        lines.append(
            f"\nSubmitted: {submitted} | Failed: {failed} | Remaining today: {max(0, profile.daily_apply_limit - len(todays_apps))}"
        )

    message = "\n".join(lines)

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Foxhound Daily Brief"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to research a role, draft follow-up, or keep tracking a posting.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Applications"},
                            "url": f"{DASHBOARD_BASE}/applications",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": f"{DASHBOARD_BASE}/intelligence",
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
            continue
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
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here and Foxhound will keep the search moving.",
                        }
                    ],
                },
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
            lines.append("   Please reply with your answer")
        lines.append("")

    lines.append("Reply within 2 hours or this application will expire.")
    lines.append("Reply 'cancel' to cancel this application.")

    message = "\n".join(lines)

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            results["slack"] = await _send_slack_question(profile, webhook_url, message, job, questions, application_id)
        elif channel == "discord":
            results["discord"] = await _post_webhook(
                webhook_url,
                {
                    "content": message[:2000],
                    "embeds": [
                        {
                            "title": f"Input needed: {job.company} — {job.title}",
                            "description": message[:4000],
                            "color": 0xFFA500,
                        }
                    ],
                },
            )
        elif channel == "sms":
            # SMS gets first question only
            first_q = questions[0]["question"] if questions else ""
            sms = f"Foxhound ({job.company}): {first_q} Reply with your answer."
            results["sms"] = await _post_webhook(webhook_url, {"text": sms, "to": profile.phone or ""})

    return results


async def _send_slack_question(
    profile: UserProfile,
    webhook_url: str,
    message: str,
    job: JobListing,
    questions: list[dict],
    application_id: str,
) -> dict:
    """Send interactive questions to Slack with Block Kit formatting."""
    blocks = _build_questions_blocks(job, questions, application_id)
    return await _send_slack_profile_message(profile, webhook_url, message, blocks)


# ---------------------------------------------------------------------------
# Status update notifications
# ---------------------------------------------------------------------------


async def send_status_update(
    profile: UserProfile,
    job: JobListing,
    old_status: str,
    new_status: str,
    application: Application | None = None,
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
        elif channel == "slack" and new_status == "needs_manual" and application:
            blocks = _build_needs_manual_blocks(job, application)
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
        elif channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Application Status Update"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Company:*\n{job.company}"},
                        {"type": "mrkdwn", "text": f"*Role:*\n{job.title}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Status changed from *{old_status}* to *{new_status}*",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to draft the next step or keep tracking the role.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Applications"},
                            "url": f"{DASHBOARD_BASE}/applications",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": _research_href("status", company=job.company, role=job.title),
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
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

    threshold = profile.autopilot_threshold or 70
    lines = [f"{len(new_matches)} new job{'s' if len(new_matches) != 1 else ''} above your {threshold}% threshold:"]
    for match, job in new_matches[:5]:
        lines.append(f"  - {job.company} — {job.title} ({match.match_score}% match)")
    if len(new_matches) > 5:
        lines.append(f"  + {len(new_matches) - 5} more")
    lines.append("Open Foxhound to review.")

    message = "\n".join(lines)
    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "New Matches Ready"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to open Research on a match or queue an application.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Jobs"},
                            "url": f"{DASHBOARD_BASE}/jobs",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": f"{DASHBOARD_BASE}/intelligence",
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
        else:
            results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


# ---------------------------------------------------------------------------
# Follow-up messages (day 3, 7, 14)
# ---------------------------------------------------------------------------


async def send_followup_day3(profile: UserProfile, job: JobListing) -> dict:
    """Day 3: normal timeline status update."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    message = f"Foxhound: Your {job.company} — {job.title} application was 3 days ago. Normal timeline for {job.ats_type or 'this company'}."

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Follow-up Window"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to keep tracking this role or prepare the next follow-up.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Applications"},
                            "url": f"{DASHBOARD_BASE}/applications",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": _research_href("status", company=job.company, role=job.title),
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
        else:
            results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


async def send_followup_day7(profile: UserProfile, job: JobListing) -> dict:
    """Day 7: offer to draft a follow-up."""
    channels = _get_user_channels(profile)
    if not channels:
        return {"skipped": "no channels"}

    message = (
        f"Foxhound: It's been a week since your {job.company} — {job.title} application. "
        f"Want me to draft a follow-up to the hiring manager? Reply here or in Foxhound."
    )

    results = {}
    for channel, webhook_url in channels.items():
        if channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Follow-up Ready"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to draft the note, open Research, or keep waiting.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Applications"},
                            "url": f"{DASHBOARD_BASE}/applications",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": _research_href("people", company=job.company, role=job.title),
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
        else:
            results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results


async def send_followup_day14(profile: UserProfile, job: JobListing) -> dict:
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
        if channel == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Time To Re-evaluate"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Reply here if you want Foxhound to find stronger matches or keep monitoring this one.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Jobs"},
                            "url": f"{DASHBOARD_BASE}/jobs",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Research"},
                            "url": _research_href("people", company=job.company, role=job.title),
                        },
                    ],
                },
            ]
            results["slack"] = await _send_slack_profile_message(profile, webhook_url, message, blocks)
        else:
            results[channel] = await _post_webhook(webhook_url, {"text": message})
    return results
