"""Daily watchdog sweep orchestrator.

Loads all eligible applications, groups them by domain to avoid
hammering a single job board, and runs TinyFish checks with bounded
concurrency (semaphore of 3).

Called by ``execute_watchdog_sweep`` in the scheduling executors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.session import async_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_APPLICATION_AGE_DAYS = 30
DEFAULT_DOMAIN_DELAY_SECONDS = 5
DEFAULT_MAX_CONCURRENT = 3


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_watchdog_sweep(
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    domain_delay_seconds: int = DEFAULT_DOMAIN_DELAY_SECONDS,
) -> dict:
    """Main entry point called by the scheduler executor.

    Returns a summary dict: {checked, active, removed, edited, failed, changed}.
    """
    start = time.monotonic()

    async with async_session() as db:
        applications = await _get_eligible_applications(db)

    if not applications:
        logger.info("Watchdog sweep: no eligible applications")
        return {"checked": 0, "active": 0, "removed": 0, "edited": 0, "failed": 0}

    logger.info("Watchdog sweep: %d applications to check", len(applications))

    # Group by domain for rate limiting
    by_domain: dict[str, list[tuple[Application, JobListing]]] = {}
    for app, job in applications:
        domain = urlparse(job.apply_url or "").netloc or "unknown"
        by_domain.setdefault(domain, []).append((app, job))

    # Bounded concurrency across all domains
    semaphore = asyncio.Semaphore(max_concurrent)
    results = {
        "checked": 0,
        "active": 0,
        "removed": 0,
        "edited": 0,
        "failed": 0,
        "changed": 0,
    }

    async def _check_domain_group(
        domain: str, items: list[tuple[Application, JobListing]]
    ) -> None:
        for idx, (app, job) in enumerate(items):
            async with semaphore:
                try:
                    # Lazy import to avoid tinyfish at module level
                    from app.services.watchdog.checker import check_application

                    outcome = await check_application(
                        app, job, triggered_by="scheduled"
                    )
                    status = outcome.get("status", "check_failed")
                    results["checked"] += 1

                    if status == "active":
                        results["active"] += 1
                    elif status == "removed":
                        results["removed"] += 1
                    elif status == "edited":
                        results["edited"] += 1
                    else:
                        results["failed"] += 1

                    if outcome.get("changed"):
                        results["changed"] += 1

                    # Update ghost score after each check
                    try:
                        from app.services.ghost_detector import score_job
                        async with async_session() as ghost_db:
                            ghost_result = await score_job(ghost_db, job.id)
                            if "error" not in ghost_result:
                                ghost_job = await ghost_db.get(JobListing, job.id)
                                if ghost_job:
                                    ghost_job.ghost_score = ghost_result["score"]
                                    ghost_job.ghost_risk = ghost_result["risk"]
                                    ghost_job.ghost_factors_json = json.dumps(ghost_result["factors"])
                                    ghost_job.ghost_checked_at = datetime.now(timezone.utc)
                                    if status == "reposted":
                                        ghost_job.repost_count = (ghost_job.repost_count or 0) + 1
                                    await ghost_db.commit()
                    except Exception as e:
                        logger.warning("Ghost score update failed for %s: %s", job.id, e)

                except Exception:
                    logger.exception(
                        "Watchdog check failed: app=%s domain=%s", app.id, domain
                    )
                    results["checked"] += 1
                    results["failed"] += 1

            # Rate limit between checks on the same domain
            if idx < len(items) - 1:
                await asyncio.sleep(domain_delay_seconds)

    # Launch all domain groups concurrently; the semaphore gates parallelism
    tasks = [
        _check_domain_group(domain, items)
        for domain, items in by_domain.items()
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.monotonic() - start
    logger.info(
        "Watchdog sweep complete: checked=%d active=%d removed=%d "
        "edited=%d failed=%d elapsed=%.1fs",
        results["checked"],
        results["active"],
        results["removed"],
        results["edited"],
        results["failed"],
        elapsed,
    )
    return results


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def _get_eligible_applications(
    db: AsyncSession,
) -> list[tuple[Application, JobListing]]:
    """Return (Application, JobListing) pairs eligible for watchdog checks.

    Criteria:
    - watchdog_enabled is True
    - application status is not terminal (failed, canceled)
    - created within the last 30 days
    - not already checked in the last 20 hours (handles manual mid-day checks)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_APPLICATION_AGE_DAYS)
    recheck_cutoff = datetime.now(timezone.utc) - timedelta(hours=20)

    result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(
            Application.watchdog_enabled.is_(True),
            Application.status.notin_(["failed", "canceled"]),
            Application.created_at >= cutoff,
            (
                Application.last_watchdog_check_at.is_(None)
                | (Application.last_watchdog_check_at < recheck_cutoff)
            ),
        )
        .order_by(Application.last_watchdog_check_at.asc().nullsfirst())
    )
    return list(result.all())
