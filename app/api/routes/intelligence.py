"""Intelligence Hub API — direct endpoints for all intelligence tools.

These bypass the agent chat and return results directly to the UI.
The agent chat can still call the same underlying tools via the agent tool registry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import rate_limit
from app.db.models.application import Application
from app.db.models.foxhound_brief import FoxhoundBrief
from app.db.models.job_listing import JobListing
from app.db.session import get_db
from app.services.application_guidance import (
    build_application_context,
    build_recommended_next_action,
)
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class CompanyRequest(BaseModel):
    company_name: str = ""
    role: str = ""
    application_id: str | None = None


class DiscoverRequest(BaseModel):
    query: str
    role: str = ""
    location: str = ""
    industry: str = ""
    application_id: str | None = None


async def _load_application_context(
    db: AsyncSession,
    user_id: str,
    application_id: str | None,
) -> dict | None:
    if not application_id:
        return None

    result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Application not found")

    app, job = row
    brief_row = await db.execute(
        select(FoxhoundBrief.id, FoxhoundBrief.status).where(
            FoxhoundBrief.user_id == user_id,
            FoxhoundBrief.application_id == application_id,
        )
    )
    brief_info = brief_row.first()

    return build_application_context(
        app,
        job,
        brief_ready=bool(brief_info),
        brief_status=brief_info[1] if brief_info else None,
    )


def _augment_result(module: str, result: dict, context: dict | None) -> dict:
    response = dict(result)
    response["application_context"] = context
    response["recommended_next_action"] = build_recommended_next_action(
        context,
        module=module,
    )
    return response


@router.post("/interview-prep")
async def interview_prep(
    body: CompanyRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("intelligence", 10, 60)),
):
    """Run interview prep for a company. Returns results directly."""
    from app.services.agent.tools.interview_prep import interview_prep_search

    context = await _load_application_context(db, user["user_id"], body.application_id)
    company_name = body.company_name.strip() or (context.get("company") if context else "")
    role = body.role.strip() or (context.get("role") if context else "")
    if not company_name:
        raise HTTPException(400, "company_name is required")

    payload = {"company_name": company_name, "role": role}
    if context and context.get("job_id"):
        payload["job_id"] = context["job_id"]

    result = await interview_prep_search(
        db, user["user_id"], payload
    )
    return _augment_result("interview", result, context)


@router.post("/company-brief")
async def company_brief(
    body: CompanyRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("intelligence", 10, 60)),
):
    """Run a company brief. Returns results directly."""
    from app.services.agent.tools.recon import recon_company

    context = await _load_application_context(db, user["user_id"], body.application_id)
    company_name = body.company_name.strip() or (context.get("company") if context else "")
    if not company_name:
        raise HTTPException(400, "company_name is required")

    payload = {"company_name": company_name}
    if context and context.get("job_id"):
        payload["job_id"] = context["job_id"]

    result = await recon_company(
        db, user["user_id"], payload
    )
    return _augment_result("brief", result, context)


@router.post("/people-research")
@router.post("/hiring-manager")
@router.post("/network-map")
async def people_research(
    body: CompanyRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("intelligence", 10, 60)),
):
    """Start people research in background. Returns immediately."""
    import asyncio
    user_id = user["user_id"]

    context = await _load_application_context(db, user_id, body.application_id)
    company_name = body.company_name.strip() or (context.get("company") if context else "")
    role_context = body.role.strip() or (context.get("role") if context else "")
    if not company_name:
        raise HTTPException(400, "company_name is required")

    logger.info("People research requested: company=%s role=%s", company_name, role_context)

    from app.services.activity.logger import log_activity
    await log_activity(
        user_id=user_id,
        event_type="people_research_started",
        title=f"People research started: {company_name}",
        description=f"Foxhound is finding contacts at {company_name}. You'll be notified when results are ready.",
        metadata={"company": company_name, "role": role_context},
    )

    job_id = context.get("job_id") if context else None
    asyncio.create_task(_run_people_research_background(
        user_id, company_name, role_context, job_id,
    ))

    return {
        "status": "started",
        "message": f"Foxhound is researching contacts at {company_name}. You'll be notified when results are ready.",
        "company": company_name,
    }


async def _run_people_research_background(
    user_id: str, company_name: str, role_context: str, job_id: str | None,
) -> None:
    """Run people research in background and notify when done."""
    try:
        from app.db.session import async_session
        from app.services.activity.logger import log_activity
        from app.services.agent.tools.network import network_map as run_network
        from app.services.agent.tools.pathfinder import find_hiring_manager

        async with async_session() as db:
            manager_payload: dict = {"company_name": company_name}
            if job_id:
                manager_payload["job_id"] = job_id

            result = await find_hiring_manager(db, user_id, manager_payload)

            if result.get("error"):
                network_only = await run_network(
                    db, user_id,
                    {"company_name": company_name, "role_context": role_context},
                )
                result = network_only
            else:
                network_result = await run_network(
                    db, user_id,
                    {"company_name": company_name, "role_context": role_context},
                )
                if network_result.get("contacts"):
                    result["contacts"] = network_result["contacts"]
                    result["contacts_count"] = network_result.get("count", len(network_result["contacts"]))

        # Merge real contacts into best contact — don't use LLM guess
        contacts = result.get("contacts", [])
        high_contacts = [c for c in contacts if isinstance(c, dict) and c.get("relevance") == "high"]
        top = high_contacts[0] if high_contacts else (contacts[0] if contacts else None)
        if top and top.get("name") and top.get("title"):
            result.setdefault("manager_signals", {})
            result["manager_signals"]["likely_title"] = top["title"]
            result["manager_signals"]["likely_name"] = top["name"]
            result["manager_signals"]["department"] = ""
            if top.get("linkedin_url"):
                result.setdefault("search_urls", {})
                result["search_urls"]["linkedin"] = top["linkedin_url"]

        manager = top["title"] if top else result.get("manager_signals", {}).get("likely_title", "")
        await log_activity(
            user_id=user_id,
            event_type="people_research_completed",
            title=f"People research ready: {company_name}",
            description=f"Found {len(contacts)} contacts{' — best contact: ' + manager if manager else ''} at {company_name}.",
            metadata={"company": company_name, "contacts_count": len(contacts), "result": result},
            dedup_minutes=0,
        )
        logger.info("People research background complete: company=%s contacts=%d", company_name, len(contacts))

    except Exception as e:
        logger.exception("People research background failed: company=%s error=%s", company_name, e)


@router.post("/discover")
async def discover_jobs(
    body: DiscoverRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("intelligence", 10, 60)),
):
    """Start job discovery in background. Returns immediately."""
    import asyncio
    user_id = user["user_id"]
    logger.info("Discovery requested: query=%s role=%s location=%s industry=%s", body.query, body.role, body.location, body.industry)

    from app.services.activity.logger import log_activity
    await log_activity(
        user_id=user_id,
        event_type="discovery_started",
        title=f"Job discovery started: {body.query}",
        description=f"Foxhound is searching for {body.role or body.query} jobs{' in ' + body.location if body.location else ''}{' (' + body.industry + ')' if body.industry else ''}. You'll be notified when results are ready.",
        metadata={"query": body.query, "role": body.role, "location": body.location, "industry": body.industry},
    )

    asyncio.create_task(_run_discovery_background(
        user_id, body.query, body.role, body.location, body.industry, body.application_id,
    ))

    return {
        "status": "started",
        "message": "Foxhound is searching for jobs. You'll be notified when results are ready.",
        "query": body.query,
    }


async def _run_discovery_background(
    user_id: str, query: str, role: str, location: str, industry: str, application_id: str | None,
) -> None:
    """Run job discovery in background and notify when done."""
    try:
        from app.db.session import async_session
        from app.services.activity.logger import log_activity
        from app.services.agent.tools.discover import discover_jobs as run_discover

        async with async_session() as db:
            result = await run_discover(
                db, user_id,
                {"query": query, "role": role, "location": location, "industry": industry},
            )

        jobs = result.get("jobs", [])
        if jobs:
            await log_activity(
                user_id=user_id,
                event_type="discovery_completed",
                title=f"Found {len(jobs)} jobs for {query}",
                description=f"Foxhound found {len(jobs)} matching opportunities. Check the Discovery tab to review them.",
                metadata={"query": query, "count": len(jobs), "jobs": jobs[:10]},
                dedup_minutes=0,
            )
        else:
            await log_activity(
                user_id=user_id,
                event_type="discovery_completed",
                title=f"No jobs found for {query}",
                description="Foxhound searched but couldn't find matching jobs. Try broadening your search.",
                metadata={"query": query, "count": 0},
                dedup_minutes=0,
            )
        logger.info("Discovery background complete: query=%s found=%d", query, len(jobs))

    except Exception as e:
        logger.exception("Discovery background failed: query=%s error=%s", query, e)
