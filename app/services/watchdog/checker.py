"""Watchdog checker: navigates to a job posting URL via TinyFish LITE
and determines whether the listing is still live, removed, or edited.

TinyFish imports are LAZY (inside functions) because system Python
does not have the tinyfish package installed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.watchdog_check import WatchdogCheck
from app.db.session import async_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TINYFISH_TIMEOUT_SECONDS = 60
RETRY_DELAY_SECONDS = 2

WATCHDOG_CHECK_GOAL = """Navigate to this URL and determine if a specific job posting is still live.

Check these signals IN ORDER:
1. If the page shows a 404 error, "page not found", or "this page doesn't exist" -> the posting is REMOVED.
2. If the page says "no longer accepting applications", "position has been filled", "this role has been filled", "this job is no longer available" -> the posting is REMOVED.
3. If the page redirected to a generic careers/jobs page with no specific job listing -> the posting is REMOVED.
4. If a specific job posting IS visible with a title and description -> the posting is ACTIVE.

If the posting is ACTIVE, extract the full visible job description text (title, requirements, responsibilities, qualifications). Include everything visible on the posting page. Do not navigate away from the page.

If a cookie/consent banner appears, close it first.
Do not click any Apply buttons.
Do not fill any forms.

Return as JSON:
{"status": "active" | "removed", "page_title": "string", "current_url": "string", "description_text": "string or null", "removal_signal": "null if active, otherwise the signal text"}"""

# Status transitions that trigger user notifications
NOTIFY_TRANSITIONS = {
    ("unknown", "removed"),
    ("active", "removed"),
    ("edited", "removed"),
    ("active", "edited"),
    ("removed", "reposted"),
    ("reposted", "removed"),
    ("edited", "edited"),
    ("check_failed", "removed"),
}


# ---------------------------------------------------------------------------
# Public: check a single application
# ---------------------------------------------------------------------------


async def check_application(
    application: Application,
    job: JobListing,
    triggered_by: str = "scheduled",
) -> dict:
    """Navigate to *apply_url* via TinyFish LITE, determine posting status.

    Returns a dict with keys:
        status        – "active" | "removed" | "edited" | "check_failed"
        description_text – full posting text (if active)
        changed       – whether posting_status transitioned
        check_id      – id of the WatchdogCheck row
    """
    # --- Lazy TinyFish import ---
    from app.services.ingest.tinyfish_adapter import _get_client

    start_ms = time.monotonic()
    client = _get_client()

    # --- First attempt: LITE, no proxy ---
    from tinyfish import BrowserProfile

    result = await client.agent.run(
        goal=WATCHDOG_CHECK_GOAL,
        url=job.apply_url,
        browser_profile=BrowserProfile.LITE,
    )

    profile_used = "LITE"

    # If empty result (possible bot detection), retry with STEALTH
    if result.status.value == "COMPLETED" and not result.result:
        logger.warning("Watchdog: empty result for %s, retrying STEALTH", job.apply_url)
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        from tinyfish import ProxyConfig, ProxyCountryCode

        result = await client.agent.run(
            goal=WATCHDOG_CHECK_GOAL,
            url=job.apply_url,
            browser_profile=BrowserProfile.STEALTH,
            proxy_config=ProxyConfig(enabled=True, country_code=ProxyCountryCode.US),
        )
        profile_used = "STEALTH"

    elapsed_ms = int((time.monotonic() - start_ms) * 1000)

    # --- Parse result ---
    if result.status.value != "COMPLETED" or not result.result:
        return await _record_check_failed(application, result, elapsed_ms, profile_used, triggered_by)

    import json as _json

    raw = result.result
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            logger.warning("Watchdog: could not parse result as JSON: %s", raw[:200])
            data = {"status": "active", "description_text": raw}
    else:
        data = {}
    check_status = data.get("status", "active")
    description_text = data.get("description_text")
    removal_signal = data.get("removal_signal")
    current_url = data.get("current_url")

    # --- Compute new posting_status ---
    old_status = application.posting_status or "unknown"
    new_status = _compute_new_status(old_status, check_status, description_text, application.posting_last_text)
    status_changed = old_status != new_status
    posting_changed = _text_changed(application.posting_last_text, description_text)

    # --- Diff summary ---
    diff_summary = None
    if posting_changed and description_text and application.posting_last_text:
        from app.services.watchdog.differ import summarize_diff

        diff_summary = summarize_diff(application.posting_last_text, description_text)

    # --- Persist check record + update application ---
    check_id = str(uuid4())
    async with async_session() as db:
        check = WatchdogCheck(
            id=check_id,
            application_id=application.id,
            user_id=application.user_id,
            check_status=check_status,
            posting_changed=posting_changed,
            status_changed=status_changed,
            previous_status=old_status,
            new_status=new_status,
            description_text=description_text,
            diff_summary=diff_summary,
            removal_signal=removal_signal,
            tinyfish_run_id=result.run_id,
            tinyfish_steps=result.num_of_steps,
            check_duration_ms=elapsed_ms,
            browser_profile=profile_used,
            current_url=current_url,
            triggered_by=triggered_by,
        )
        db.add(check)

        app_row = await db.get(Application, application.id)
        app_row.posting_status = new_status
        app_row.last_watchdog_check_at = datetime.now(UTC)
        if description_text and check_status == "active":
            app_row.posting_last_text = description_text
        if diff_summary:
            app_row.posting_diff_summary = diff_summary

        await db.commit()

    # --- Notify on meaningful transitions ---
    if (old_status, new_status) in NOTIFY_TRANSITIONS:
        await _send_watchdog_notification(application, job, old_status, new_status, diff_summary)

    # --- Log to activity feed + emit event ---
    from app.services.activity.logger import log_activity

    if status_changed:
        recommendation = _watchdog_recommendation(old_status, new_status)
        await log_activity(
            user_id=application.user_id,
            event_type="watchdog_check" if new_status == "active" else "ghost_alert",
            title=f"Watchdog: {job.company} posting {new_status}",
            description=recommendation,
            metadata={
                "application_id": application.id,
                "job_id": job.id,
                "company": job.company,
                "title": job.title,
                "old_status": old_status,
                "new_status": new_status,
                "diff_summary": diff_summary,
            },
        )

        from app.services.events import FoxhoundEvent, emit

        await emit(
            FoxhoundEvent(
                name="watchdog.change",
                data={
                    "user_id": application.user_id,
                    "application_id": application.id,
                    "job_id": job.id,
                    "company": job.company,
                    "title": job.title,
                    "old_status": old_status,
                    "new_status": new_status,
                    "recommendation": recommendation,
                },
            )
        )

    return {
        "status": new_status,
        "description_text": description_text,
        "changed": status_changed,
        "check_id": check_id,
    }


def _watchdog_recommendation(old_status: str, new_status: str) -> str:
    """Generate a recommendation based on posting status transition."""
    if new_status == "removed":
        return (
            "Posting taken down. This usually means the role is filled or paused. "
            "Check your Foxhound Brief for contact info to follow up directly."
        )
    if new_status == "edited":
        return (
            "Job description was updated. This often means the team is refining "
            "requirements — the role is likely still active."
        )
    if new_status == "reposted":
        return (
            "Posting was reposted. Previous round may not have yielded the right "
            "candidates. Could be a second chance if you already applied."
        )
    if new_status == "active":
        return "Posting confirmed active. No changes detected."
    return "Status changed. Monitoring continues."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_new_status(
    old_status: str,
    check_result: str,
    new_text: str | None,
    old_text: str | None,
) -> str:
    """Determine the new posting_status from the check result and history."""
    if check_result == "removed":
        return "removed"

    # check_result == "active"
    if old_status == "removed":
        return "reposted"

    if old_text and new_text and _text_changed(old_text, new_text):
        return "edited"

    return "active"


def _text_changed(old_text: str | None, new_text: str | None) -> bool:
    """Detect meaningful text changes (ignoring whitespace noise)."""
    if not old_text or not new_text:
        return False
    old_norm = _normalize_text(old_text)
    new_norm = _normalize_text(new_text)
    if old_norm == new_norm:
        return False

    from difflib import SequenceMatcher

    ratio = SequenceMatcher(None, old_norm, new_norm).ratio()
    return ratio < 0.98  # less than 98% similar = meaningful change


def _normalize_text(text: str) -> str:
    """Normalize whitespace for comparison."""
    return " ".join(text.split()).strip().lower()


async def _record_check_failed(
    application: Application,
    result: object,
    elapsed_ms: int,
    profile_used: str,
    triggered_by: str,
) -> dict:
    """Record a failed check without changing posting_status."""
    check_id = str(uuid4())
    async with async_session() as db:
        check = WatchdogCheck(
            id=check_id,
            application_id=application.id,
            user_id=application.user_id,
            check_status="check_failed",
            posting_changed=False,
            status_changed=False,
            previous_status=application.posting_status,
            new_status=application.posting_status,
            tinyfish_run_id=getattr(result, "run_id", None),
            tinyfish_steps=getattr(result, "num_of_steps", None),
            check_duration_ms=elapsed_ms,
            browser_profile=profile_used,
            error_message=getattr(result, "error", None) or "empty result",
            triggered_by=triggered_by,
        )
        db.add(check)

        app_row = await db.get(Application, application.id)
        app_row.last_watchdog_check_at = datetime.now(UTC)
        await db.commit()

    return {
        "status": "check_failed",
        "description_text": None,
        "changed": False,
        "check_id": check_id,
    }


async def _send_watchdog_notification(
    application: Application,
    job: JobListing,
    old_status: str,
    new_status: str,
    diff_summary: str | None,
) -> None:
    """Send notification via existing channel infrastructure."""
    from app.services.watchdog.notifications import send_watchdog_alert

    try:
        await send_watchdog_alert(application, job, old_status, new_status, diff_summary)
    except Exception:
        logger.exception("Watchdog notification failed: app=%s", application.id)
