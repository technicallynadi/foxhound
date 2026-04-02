"""Event handler registrations.

Import this module at startup to register all handlers.
Each handler is a thin dispatcher — real logic stays in its own service.
"""

from __future__ import annotations

import logging

from app.services.events.bus import FoxhoundEvent, on_event

logger = logging.getLogger(__name__)


@on_event("application.submitted")
async def on_application_submitted(event: FoxhoundEvent) -> None:
    """Post-submit cascade: schedule follow-ups + log activity + start research."""
    user_id = event.data["user_id"]
    application_id = event.data["application_id"]
    job_id = event.data["job_id"]
    company = event.data.get("company", "Unknown")
    title = event.data.get("title", "Unknown")
    match_score = event.data.get("match_score")
    trigger = event.data.get("trigger", "manual")

    logger.info(
        "application.submitted: app=%s job=%s user=%s trigger=%s",
        application_id, job_id, user_id, trigger,
    )

    # 1. Schedule follow-up jobs (day 3, 7, 14)
    from app.services.scheduling.followup import schedule_followups
    await schedule_followups(user_id, application_id, job_id)

    # 2. Log activity event
    from app.services.activity.logger import log_activity
    await log_activity(
        user_id=user_id,
        event_type="application_submitted",
        title=f"Applied to {company} — {title}",
        description=f"{'Autopilot' if trigger == 'autopilot' else 'Manual'} application submitted"
        + (f" ({match_score}% match)" if match_score else ""),
        metadata={
            "application_id": application_id,
            "job_id": job_id,
            "company": company,
            "title": title,
            "match_score": match_score,
            "trigger": trigger,
        },
    )

    # 3. Start post-apply research cascade (simplified for demo)
    from app.services.research.cascade import start_research_cascade
    await start_research_cascade(user_id, application_id, job_id, match_score)


@on_event("match.strong")
async def on_strong_match(event: FoxhoundEvent) -> None:
    """Log strong match discovery."""
    from app.services.activity.logger import log_activity

    company = event.data.get("company", "Unknown")
    title = event.data.get("title", "Unknown")
    score = event.data.get("score", 0)

    await log_activity(
        user_id=event.data["user_id"],
        event_type="matches_discovered",
        title=f"Strong match: {company} — {title} ({score}%)",
        description="Above your autopilot threshold",
        metadata=event.data,
    )


@on_event("watchdog.change")
async def on_watchdog_change(event: FoxhoundEvent) -> None:
    """Log watchdog status change."""
    from app.services.activity.logger import log_activity

    company = event.data.get("company", "Unknown")
    new_status = event.data.get("new_status", "changed")

    await log_activity(
        user_id=event.data["user_id"],
        event_type="watchdog_check",
        title=f"Watchdog: {company} posting {new_status}",
        description=event.data.get("recommendation", ""),
        metadata=event.data,
    )


@on_event("research.completed")
async def on_research_completed(event: FoxhoundEvent) -> None:
    """Log research completion and notify about brief."""
    from app.services.activity.logger import log_activity

    company = event.data.get("company", "Unknown")

    await log_activity(
        user_id=event.data["user_id"],
        event_type="dossier_ready",
        title=f"Foxhound Brief ready: {company}",
        description="Company research, contacts, and outreach drafts assembled",
        metadata=event.data,
    )
