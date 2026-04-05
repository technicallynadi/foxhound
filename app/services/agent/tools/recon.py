"""Brief Report tool: quick company research via the agent chat."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.services.agent.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="recon_company",
    description=(
        "Generate a Brief Report on a company before applying. Scrapes the "
        "company's careers page and about page, then synthesizes a quick brief "
        "with hiring velocity, tech stack, and an insider tip. Use when the user "
        "says 'research this company', 'tell me about [company]', or "
        "'brief report on [company]'. Specify by job_id or company_name."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Job ID to recon (looks up company from posting)"},
            "company_name": {"type": "string", "description": "Company name to research (fuzzy match)"},
        },
    },
    permissions=["read"],
    side_effects=False,
    cost_estimate="medium",
)
async def recon_company(db: AsyncSession, user_id: str, params: dict) -> dict:
    """Run recon and return the dossier as a structured dict for the agent."""
    job_id = params.get("job_id")
    company_name = params.get("company_name", "").strip().lower()

    # If company_name looks like a URL, extract company from it
    if company_name and ("http://" in company_name or "https://" in company_name or "." in company_name):
        from app.services.apply.ats_url_parser import parse_ats_url
        url_info = parse_ats_url(company_name)
        if url_info:
            # board_token is usually the company slug
            company_name = url_info.board_token.replace("-", " ").replace("_", " ")
            logger.info("Extracted company '%s' from URL", company_name)

    # Resolve job_id if only company_name given
    if not job_id and company_name:
        result = await db.execute(
            select(JobListing)
            .where(JobListing.status == "active")
            .order_by(JobListing.discovered_at.desc())
        )
        for job in result.scalars():
            if company_name in (job.company or "").lower():
                job_id = job.id
                break

    if not job_id:
        return {
            "error": "no_job_found",
            "message": "Could not find a job listing for that company. Try searching first.",
            "suggestion": "Use search_jobs to find the company, then run a brief report with the job_id.",
        }

    # Run the recon engine synchronously (collects all results)
    from app.services.recon.engine import ReconEngine

    engine = ReconEngine(db=db, job_id=job_id, user_id=user_id)
    dossier = await engine.run_sync()

    # Format for agent response
    synthesis = dossier.get("synthesis") or {}
    posting = dossier.get("posting") or {}

    response: dict = {
        "company": posting.get("company", company_name or "Unknown"),
        "dossier_id": dossier.get("dossier_id"),
        "cached": dossier.get("cached", False),
        "duration_ms": dossier.get("duration_ms", 0),
    }

    if synthesis:
        response["summary"] = synthesis.get("summary", "")
        response["hiring_velocity"] = synthesis.get("hiring_velocity", "")
        response["tech_stack"] = synthesis.get("tech_stack", [])
        response["team_insight"] = synthesis.get("team_insight", "")
        response["insider_tip"] = synthesis.get("insider_tip", "")
        response["confidence"] = synthesis.get("confidence", "low")
        response["message"] = (
            f"Company intel for {response['company']}:\n"
            f"{synthesis.get('summary', '')}\n\n"
            f"Hiring: {synthesis.get('hiring_velocity', 'Unknown')}\n"
            f"Tech: {', '.join(synthesis.get('tech_stack', []))}\n"
            f"Insider tip: {synthesis.get('insider_tip', 'N/A')}"
        )
    else:
        response["message"] = f"Brief Report completed for {response['company']} but synthesis failed."
        response["confidence"] = "low"

    if dossier.get("errors"):
        response["warnings"] = [e.get("reason", "unknown") for e in dossier["errors"]]

    return response
