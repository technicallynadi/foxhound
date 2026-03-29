"""Preview cleanup job — destroys expired Fly.io preview machines.

Runs periodically to tear down sandbox previews that have exceeded their TTL.
Prevents cost accumulation from forgotten or abandoned previews.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.config import settings
from app.db.session import async_session

logger = logging.getLogger(__name__)


async def cleanup_expired_previews() -> dict:
    """Find and destroy sandbox previews past their TTL.

    Returns summary: {"checked": N, "destroyed": N, "errors": N, "details": [...]}
    """
    from app.db.models.sandbox_project import SandboxProject
    from app.services.fly_client import teardown_preview

    if not settings.fly_api_token:
        return {"checked": 0, "destroyed": 0, "errors": 0, "details": ["No FLY_API_TOKEN"]}

    now = datetime.now(timezone.utc)
    destroyed = 0
    errors = 0
    details = []

    async with async_session() as session:
        # Find all live previews with Fly metadata
        result = await session.execute(
            select(SandboxProject).where(
                SandboxProject.status.in_(["live", "unhealthy"]),
                SandboxProject.fly_app_name.isnot(None),
            )
        )
        projects = result.scalars().all()

        for project in projects:
            ttl_hours = project.preview_ttl_hours or settings.preview_ttl_hours
            expires_at = project.created_at + timedelta(hours=ttl_hours)

            if now >= expires_at:
                try:
                    success = await teardown_preview(
                        app_name=project.fly_app_name,
                        machine_id=project.fly_machine_id,
                    )
                    if success:
                        project.status = "expired"
                        project.preview_url = None
                        project.updated_at = now
                        destroyed += 1
                        details.append(f"Destroyed {project.fly_app_name} (age: {now - project.created_at})")
                    else:
                        errors += 1
                        details.append(f"Failed to destroy {project.fly_app_name}")
                except Exception as e:
                    errors += 1
                    details.append(f"Error destroying {project.fly_app_name}: {e}")
                    logger.error("Cleanup error for %s: %s", project.fly_app_name, e)

        await session.commit()

    summary = {
        "checked": len(projects),
        "destroyed": destroyed,
        "errors": errors,
        "details": details,
    }
    logger.info("Preview cleanup: %d checked, %d destroyed, %d errors", len(projects), destroyed, errors)
    return summary
