"""Brief assembler: creates/updates FoxhoundBrief from research results."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from app.db.models.foxhound_brief import FoxhoundBrief
from app.db.session import async_session
from app.services.application_guidance import (
    build_recommended_next_action,
    serialize_recommended_next_action,
)

logger = logging.getLogger(__name__)


async def assemble_brief(
    user_id: str,
    application_id: str,
    data: dict,
) -> FoxhoundBrief | None:
    """Create or update the FoxhoundBrief from research cascade results."""
    try:
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(FoxhoundBrief).where(
                    FoxhoundBrief.application_id == application_id
                )
            )
            brief = result.scalar_one_or_none()

            if not brief:
                brief = FoxhoundBrief(
                    id=str(uuid4()),
                    user_id=user_id,
                    application_id=application_id,
                )
                db.add(brief)

            # Populate sections from data
            if "company_brief" in data and not isinstance(data["company_brief"], str):
                cb = data["company_brief"]
                if not cb.get("error"):
                    brief.company_brief_json = json.dumps(cb)

            if "pathfinder" in data and not isinstance(data["pathfinder"], str):
                pf = data["pathfinder"]
                if not pf.get("error"):
                    brief.pathfinder_json = json.dumps(pf)

            if "network_map" in data:
                nm = data["network_map"]
                if isinstance(nm, dict) and not nm.get("error"):
                    brief.network_map_json = json.dumps(nm)

            if "dossier" in data:
                d = data["dossier"]
                if isinstance(d, dict) and not d.get("error"):
                    brief.dossier_json = json.dumps(d)

            brief.watchdog_status = "active"

            # Generate recommended next action
            brief.recommended_next_action = serialize_recommended_next_action(
                _generate_recommendation(data)
            )

            # Determine completeness
            sections = [brief.company_brief_json, brief.pathfinder_json]
            filled = sum(1 for s in sections if s)
            brief.status = "ready" if filled >= 2 else "partial" if filled >= 1 else "assembling"

            await db.commit()
            logger.info(
                "Brief assembled for application %s: status=%s",
                application_id, brief.status,
            )
            return brief

    except Exception:
        logger.exception("Failed to assemble brief for %s", application_id)
        return None


def _generate_recommendation(data: dict) -> dict:
    """Generate a recommended next action based on research results."""
    parts = []

    pathfinder = data.get("pathfinder", {})
    if isinstance(pathfinder, dict) and pathfinder.get("search_urls"):
        manager_title = pathfinder.get("manager_signals", {}).get("likely_title", "the hiring manager")
        parts.append(
            f"Send a LinkedIn connection request to {manager_title}. "
            "Best window: within 24 hours of application."
        )

    company_brief = data.get("company_brief", {})
    if isinstance(company_brief, dict) and company_brief.get("summary"):
        parts.append("Review the company brief before any interview.")

    parts.append("Foxhound will send a follow-up reminder in 7 days if no response.")

    action = build_recommended_next_action(None, module="brief")
    action["detail"] = " ".join(parts)
    return action
