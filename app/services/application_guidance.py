"""Canonical contract builders for application context and next actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

ActionPriority = Literal["high", "normal", "low"]


class ApplicationContext(TypedDict):
    application_id: str
    job_id: str | None
    company: str
    role: str
    status: str
    posting_status: str
    submitted_at: str | None
    days_since_applied: int
    followup_day3_sent: bool
    followup_day7_sent: bool
    followup_day14_sent: bool
    brief_ready: bool
    brief_status: str | None


class RecommendedNextAction(TypedDict):
    label: str
    detail: str
    href: str | None
    href_label: str | None
    priority: ActionPriority


def _days_since_applied(
    submitted_at: datetime | None,
    created_at: datetime | None,
) -> int:
    ref = submitted_at or created_at
    if not ref:
        return 0
    return max(0, (datetime.now(timezone.utc) - ref).days)


def build_application_context(
    app: Any,
    job: Any | None,
    *,
    brief_ready: bool = False,
    brief_status: str | None = None,
) -> ApplicationContext:
    return {
        "application_id": str(getattr(app, "id", "")),
        "job_id": str(getattr(job, "id", "")) if job and getattr(job, "id", None) else None,
        "company": str(getattr(job, "company", "") or "Unknown"),
        "role": str(getattr(job, "title", "") or "Unknown"),
        "status": str(getattr(app, "status", "") or "unknown"),
        "posting_status": str(getattr(app, "posting_status", "") or "unknown"),
        "submitted_at": app.submitted_at.isoformat() if getattr(app, "submitted_at", None) else None,
        "days_since_applied": _days_since_applied(
            getattr(app, "submitted_at", None),
            getattr(app, "created_at", None),
        ),
        "followup_day3_sent": bool(getattr(app, "followup_day3_sent", False)),
        "followup_day7_sent": bool(getattr(app, "followup_day7_sent", False)),
        "followup_day14_sent": bool(getattr(app, "followup_day14_sent", False)),
        "brief_ready": bool(brief_ready),
        "brief_status": brief_status,
    }


def _next_followup(context: ApplicationContext) -> str | None:
    days = int(context.get("days_since_applied") or 0)
    if days >= 14 and not context.get("followup_day14_sent"):
        return "day14"
    if days >= 7 and not context.get("followup_day7_sent"):
        return "day7"
    if days >= 3 and not context.get("followup_day3_sent"):
        return "day3"
    return None


def _action(
    label: str,
    detail: str,
    *,
    href: str | None = None,
    href_label: str | None = None,
    priority: ActionPriority = "normal",
) -> RecommendedNextAction:
    return {
        "label": label,
        "detail": detail,
        "href": href,
        "href_label": href_label,
        "priority": priority,
    }


def _module_default_action(module: str | None) -> RecommendedNextAction:
    module_defaults: dict[str, RecommendedNextAction] = {
        "brief": _action(
            "Use this research to sharpen your next outreach",
            "Pull one concrete company signal into your follow-up note or application narrative.",
        ),
        "people": _action(
            "Start with the highest-relevance contact",
            "Send one focused outreach note and keep the other contacts as fallback paths.",
        ),
        "interview": _action(
            "Turn this into a rehearsal plan",
            "Practice likely questions and align your strongest examples to this role.",
        ),
        "discovery": _action(
            "Move top matches into your active pipeline",
            "Track the strongest roles in Foxhound so monitoring, briefing, and follow-up can run automatically.",
        ),
        "status": _action(
            "Keep Foxhound monitoring your active applications",
            "Use this status view to decide where to follow up next while Foxhound handles routine checks.",
        ),
    }
    return module_defaults.get(
        module or "",
        _action(
            "Keep Foxhound running",
            "Let Foxhound keep monitoring while you focus on the highest-upside opportunities.",
            priority="low",
        ),
    )


def build_recommended_next_action(
    context: ApplicationContext | None,
    *,
    module: str | None = None,
) -> RecommendedNextAction:
    if not context:
        return _module_default_action(module)

    app_id = context["application_id"]
    status = context.get("status")
    posting_status = context.get("posting_status") or "unknown"
    days = int(context.get("days_since_applied") or 0)
    followup_due = _next_followup(context)

    if status == "waiting_user_input":
        return _action(
            "Answer pending application questions now",
            "Foxhound is blocked waiting for your answers before it can complete this application workflow.",
            href="/applications",
            href_label="Open Applications",
            priority="high",
        )

    if posting_status == "removed":
        return _action(
            "Archive this role and redirect effort",
            "The posting appears removed. Stop spending follow-up effort here unless you already have direct recruiter traction.",
            href="/applications",
            href_label="Manage Application",
            priority="high",
        )

    if followup_due == "day14":
        return _action(
            "Send your final follow-up touch",
            "You are at day 14. Send a concise final follow-up and then deprioritize if no response.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="high",
        )

    if followup_due == "day7":
        return _action(
            "Send the day-7 follow-up",
            "This is the highest-leverage follow-up window. Use your updated research and people context now.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="high",
        )

    if followup_due == "day3":
        return _action(
            "Prepare your first follow-up draft",
            "Day 3 is approaching. Lock in your outreach angle so Foxhound can send at the right window.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="normal",
        )

    if module == "interview":
        return _action(
            "Convert this into your interview prep checklist",
            "Use this research to prep your first-round stories and revisit after each stage update.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="normal",
        )

    if posting_status == "edited":
        return _action(
            "Review posting changes before next outreach",
            "The role changed after you applied. Recalibrate your follow-up and interview narrative with the updated requirements.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="normal",
        )

    if days >= 7:
        return _action(
            "Refresh outreach and keep monitoring",
            "You are in the waiting window. Keep status tracking active and use people research for the next touch.",
            href=f"/brief/{app_id}",
            href_label="Open Brief",
            priority="normal",
        )

    return _action(
        "Let Foxhound continue the post-apply workflow",
        "Research is underway and monitoring is active. Act only on new signals while Foxhound handles routine checks.",
        href=f"/brief/{app_id}" if context.get("brief_ready") else "/applications",
        href_label="Open Pipeline",
        priority="low",
    )


def normalize_recommended_next_action(
    raw: Any,
    *,
    fallback: RecommendedNextAction | None = None,
) -> RecommendedNextAction:
    if isinstance(raw, dict):
        label = raw.get("label")
        detail = raw.get("detail")
        if isinstance(label, str) and label and isinstance(detail, str) and detail:
            priority = raw.get("priority")
            return _action(
                label.strip(),
                detail.strip(),
                href=raw.get("href") if isinstance(raw.get("href"), str) else None,
                href_label=raw.get("href_label") if isinstance(raw.get("href_label"), str) else None,
                priority=priority if priority in {"high", "normal", "low"} else "normal",
            )
    if isinstance(raw, str) and raw.strip():
        return _action("Recommended next action", raw.strip())
    if fallback:
        return fallback
    return _module_default_action(None)


def serialize_recommended_next_action(action: RecommendedNextAction) -> str:
    return json.dumps(action)


def parse_serialized_recommended_next_action(
    raw: str | None,
    *,
    fallback: RecommendedNextAction | None = None,
) -> RecommendedNextAction:
    if not raw:
        return normalize_recommended_next_action(None, fallback=fallback)
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = raw
    return normalize_recommended_next_action(parsed, fallback=fallback)
