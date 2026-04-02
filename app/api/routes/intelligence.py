"""Intelligence Hub API — direct endpoints for all intelligence tools.

These bypass the agent chat and return results directly to the UI.
The agent chat can still call the same underlying tools via the agent tool registry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.rate_limit import rate_limit
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Run people research: likely hiring manager plus broader contacts."""
    from app.services.agent.tools.pathfinder import find_hiring_manager
    from app.services.agent.tools.network import network_map as run_network

    context = await _load_application_context(db, user["user_id"], body.application_id)
    company_name = body.company_name.strip() or (context.get("company") if context else "")
    role_context = body.role.strip() or (context.get("role") if context else "")
    if not company_name:
        raise HTTPException(400, "company_name is required")

    manager_payload: dict = {"company_name": company_name}
    if context and context.get("job_id"):
        manager_payload["job_id"] = context["job_id"]

    result = await find_hiring_manager(
        db,
        user["user_id"],
        manager_payload,
    )

    # If we could not resolve a relevant job posting, fall back to broad network mapping.
    if result.get("error"):
        network_only = await run_network(
            db,
            user["user_id"],
            {"company_name": company_name, "role_context": role_context},
        )
        return _augment_result("people", network_only, context)

    # Augment focused manager intel with broader company contacts when available.
    network_result = await run_network(
        db,
        user["user_id"],
        {"company_name": company_name, "role_context": role_context},
    )
    if network_result.get("contacts"):
        result["contacts"] = network_result["contacts"]
        result["contacts_count"] = network_result.get("count", len(network_result["contacts"]))

    return _augment_result("people", result, context)


@router.post("/discover")
async def discover_jobs(
    body: DiscoverRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("intelligence", 10, 60)),
):
    """Search for jobs matching criteria. Returns results directly."""
    from app.services.agent.tools.discover import discover_jobs as run_discover

    context = await _load_application_context(db, user["user_id"], body.application_id)

    result = await run_discover(
        db, user["user_id"],
        {
            "query": body.query,
            "role": body.role or (context.get("role") if context else ""),
            "location": body.location,
            "industry": body.industry,
        },
    )
    return _augment_result("discovery", result, context)
