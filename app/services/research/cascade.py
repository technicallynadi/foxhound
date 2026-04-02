"""Post-apply research cascade.

Simplified for demo: runs Company Brief + Pathfinder as async tasks
after a successful application, then assembles a FoxhoundBrief.

Production version will use the full workflow DAG engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

from app.db.session import async_session
from app.services.activity.logger import log_activity

logger = logging.getLogger(__name__)


async def start_research_cascade(
    user_id: str,
    application_id: str,
    job_id: str,
    match_score: int | None = None,
) -> None:
    """Launch post-apply research as a background task.

    Runs asynchronously so it doesn't block the apply response.
    """
    asyncio.create_task(
        _run_cascade(user_id, application_id, job_id, match_score)
    )
    logger.info("Research cascade started for application %s", application_id)


async def _run_cascade(
    user_id: str,
    application_id: str,
    job_id: str,
    match_score: int | None,
) -> None:
    """Execute the research cascade steps sequentially."""
    try:
        async with async_session() as db:
            from app.db.models.job_listing import JobListing
            job = await db.get(JobListing, job_id)
            if not job:
                logger.warning("Research cascade: job %s not found", job_id)
                return

            company = job.company or "Unknown"
            brief_data: dict = {
                "application_id": application_id,
                "job_id": job_id,
                "company": company,
                "title": job.title,
            }

            await log_activity(
                user_id=user_id,
                event_type="research_started",
                title=f"Research started: {company} — {job.title}",
                description="Researching company context, finding the best contact, and assembling your brief.",
                metadata={
                    "application_id": application_id,
                    "job_id": job_id,
                    "company": company,
                    "title": job.title,
                    "match_score": match_score,
                },
            )

            # Step 1: Company Brief (uses TinyFish via ReconEngine)
            try:
                from app.services.agent.tools.recon import recon_company
                recon_result = await recon_company(db, user_id, {"job_id": job_id})
                brief_data["company_brief"] = recon_result
                await log_activity(
                    user_id=user_id,
                    event_type="research_completed",
                    title=f"Company Brief ready: {company}",
                    description="Foxhound summarized the company, hiring context, and role signals.",
                    metadata={
                        "application_id": application_id,
                        "job_id": job_id,
                        "company": company,
                        "title": job.title,
                        "section": "company_brief",
                    },
                )
                logger.info("Research cascade: company brief done for %s", company)
            except Exception as e:
                logger.warning("Research cascade: company brief failed: %s", e)
                brief_data["company_brief"] = {"error": str(e)}

            # Step 2: Pathfinder — find hiring manager (LLM only, no TinyFish)
            try:
                from app.services.agent.tools.pathfinder import find_hiring_manager
                pathfinder_result = await find_hiring_manager(db, user_id, {"job_id": job_id})
                brief_data["pathfinder"] = pathfinder_result
                await log_activity(
                    user_id=user_id,
                    event_type="research_completed",
                    title=f"People Research ready: {company}",
                    description="Best contact, outreach angles, and search links were added to your brief.",
                    metadata={
                        "application_id": application_id,
                        "job_id": job_id,
                        "company": company,
                        "title": job.title,
                        "section": "people_research",
                    },
                )
                logger.info("Research cascade: pathfinder done for %s", company)
            except Exception as e:
                logger.warning("Research cascade: pathfinder failed: %s", e)
                brief_data["pathfinder"] = {"error": str(e)}

        # Step 3: Assemble and save the FoxhoundBrief
        from app.services.research.brief_assembler import assemble_brief
        brief = await assemble_brief(user_id, application_id, brief_data)

        # Step 4: Emit research.completed event
        from app.services.events import emit, FoxhoundEvent
        await emit(FoxhoundEvent(
            name="research.completed",
            data={
                "user_id": user_id,
                "application_id": application_id,
                "brief_id": brief.id if brief else None,
                "company": brief_data.get("company", "Unknown"),
                "title": brief_data.get("title"),
            },
        ))

    except Exception:
        logger.exception("Research cascade failed for application %s", application_id)
