"""Foxhound MCP Server.

Exposes Foxhound's marketplace, execution artifacts, skill bundles,
and async search capabilities as MCP tools and resources.

Run with: foxhound mcp
Or:       .venv/bin/python -m app.mcp_server
"""

from mcp.server.fastmcp import FastMCP

from app.db.session import init_db

mcp = FastMCP("Foxhound")

_db_initialized = False


async def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        await init_db()
        _db_initialized = True


# --- Marketplace Tools ---


@mcp.tool()
async def search_marketplace(
    query: str = "",
    vertical: str = "",
    limit: int = 10,
    min_score: float = 0.0,
) -> dict:
    """Search the Foxhound marketplace for validated opportunities.

    Returns opportunities sorted by execution readiness and score.
    Filter by vertical, minimum score, or leave empty to browse top results.
    """
    await _ensure_db()
    from app.services.marketplace_service import list_marketplace_opportunities

    opportunities = await list_marketplace_opportunities(
        limit=limit,
        vertical=vertical or None,
        workflow=query or None,
    )
    if min_score > 0:
        opportunities = [o for o in opportunities if o.get("opportunity_score", 0) >= min_score]
    return {
        "count": len(opportunities),
        "opportunities": [
            {
                "opportunity_id": o["opportunity_id"],
                "title": o["title"],
                "workflow": o["workflow"],
                "wedge": o["wedge"],
                "score": o["opportunity_score"],
                "confidence": o["confidence"],
                "listing_status": o["listing_status"],
                "execution_ready_score": o["execution_ready_score"],
            }
            for o in opportunities
        ],
    }


@mcp.tool()
async def get_opportunity(opportunity_id: str) -> dict:
    """Get full details for a marketplace opportunity including evidence and scoring."""
    await _ensure_db()
    from app.services.marketplace_service import get_marketplace_opportunity

    opportunity = await get_marketplace_opportunity(opportunity_id)
    if not opportunity:
        return {"error": "Opportunity not found", "opportunity_id": opportunity_id}
    return opportunity


@mcp.tool()
async def get_execution_artifact(opportunity_id: str) -> dict:
    """Get or generate the execution artifact for an opportunity.

    The artifact includes: workflow, wedge, broken step, form factor,
    wedge MVP, expanded build, implementation guidance, and execution evidence.
    """
    await _ensure_db()
    from app.services.execution_artifact_service import (
        generate_artifact_for_opportunity,
        get_artifact_for_opportunity,
    )

    artifact = await get_artifact_for_opportunity(opportunity_id)
    if not artifact:
        artifact = await generate_artifact_for_opportunity(opportunity_id)
    if not artifact:
        return {"error": "Could not generate artifact", "opportunity_id": opportunity_id}
    return artifact


@mcp.tool()
async def get_build_plans(opportunity_id: str) -> dict:
    """Get build plans for an opportunity. Includes wedge MVP and expanded plans.

    Each plan has: mvp_scope, build_order, risks, estimated_effort, form_factor.
    """
    await _ensure_db()
    from app.services.execution_artifact_service import (
        generate_artifact_for_opportunity,
        get_build_plans_for_opportunity,
    )

    plans = await get_build_plans_for_opportunity(opportunity_id)
    if not plans:
        await generate_artifact_for_opportunity(opportunity_id)
        plans = await get_build_plans_for_opportunity(opportunity_id)
    return {
        "opportunity_id": opportunity_id,
        "count": len(plans),
        "plans": plans,
    }


@mcp.tool()
async def get_skill_bundle(opportunity_id: str) -> dict:
    """Get or generate the skill bundle for an opportunity.

    A skill bundle includes: operating instructions, task decomposition,
    API contracts, safe shortcuts, danger zones, and build guidance.
    """
    await _ensure_db()
    from app.services.execution_artifact_service import (
        generate_artifact_for_opportunity,
        get_artifact_for_opportunity,
    )
    from app.services.skill_bundle_service import (
        generate_skill_bundle,
        get_skill_bundle_for_opportunity,
    )

    bundle = await get_skill_bundle_for_opportunity(opportunity_id)
    if bundle:
        return bundle

    # ensure artifact exists first
    artifact = await get_artifact_for_opportunity(opportunity_id)
    if not artifact:
        artifact = await generate_artifact_for_opportunity(opportunity_id)
    if not artifact:
        return {"error": "Could not generate artifact for skill bundle", "opportunity_id": opportunity_id}

    bundle = await generate_skill_bundle(artifact["artifact_id"])
    if not bundle:
        return {"error": "Could not generate skill bundle", "opportunity_id": opportunity_id}
    return bundle


# --- Run Tools ---


@mcp.tool()
async def start_search_run(
    query: str,
    priority: int = 50,
    notify_discord: bool = False,
    notify_slack: bool = False,
) -> dict:
    """Start an async search run for a query. Returns a run_id to track progress.

    The run discovers opportunities from web sources asynchronously.
    Use get_run_status to check progress and results.
    """
    await _ensure_db()
    from app.services.run_service import create_run

    notify = {}
    if notify_discord:
        notify["discord"] = True
    if notify_slack:
        notify["slack"] = True

    run = await create_run(
        query=query,
        mode="pipeline_run",
        priority=priority,
        notify=notify or None,
    )
    return {
        "run_id": run["run_id"],
        "status": run.get("status", "queued"),
        "query": query,
        "message": "Run queued. Use get_run_status to check progress.",
    }


@mcp.tool()
async def get_run_status(run_id: str) -> dict:
    """Get the current status of a search run including progress and results."""
    await _ensure_db()
    from app.services.run_service import get_run_status as _get_run

    run = await _get_run(run_id)
    if not run:
        return {"error": "Run not found", "run_id": run_id}
    return {
        "run_id": run["run_id"],
        "status": run.get("status", "unknown"),
        "query": run.get("query", ""),
        "result_count": run.get("result_count", 0),
        "steps": run.get("steps", []),
        "marketplace_ids": run.get("marketplace_ids", []),
    }


@mcp.tool()
async def get_run_events(run_id: str) -> dict:
    """Get the event log for a search run. Useful for tracking detailed progress."""
    await _ensure_db()
    from app.services.run_service import get_run_status as _get_run

    run = await _get_run(run_id)
    if not run:
        return {"error": "Run not found", "run_id": run_id}
    return {
        "run_id": run_id,
        "events": run.get("events", []),
    }


# --- Sandbox Tools ---


@mcp.tool()
async def run_sandbox_build(opportunity_id: str) -> dict:
    """Generate a runnable project scaffold from an opportunity's execution artifact.

    Writes a complete project (React + FastAPI or Python CLI) to ~/.foxhound/sandboxes/.
    Returns the project path, file list, and instructions to run it.
    """
    await _ensure_db()
    from app.services.execution_artifact_service import (
        generate_artifact_for_opportunity,
        get_artifact_for_opportunity,
    )
    from app.services.sandbox_service import create_sandbox

    artifact = await get_artifact_for_opportunity(opportunity_id)
    if not artifact:
        artifact = await generate_artifact_for_opportunity(opportunity_id)
    if not artifact:
        return {"error": "Could not generate artifact", "opportunity_id": opportunity_id}

    result = await create_sandbox(
        opportunity_id=opportunity_id,
        artifact_id=artifact["artifact_id"],
    )
    return result


# --- Export Tools ---


@mcp.tool()
async def export_repo(project_id: str) -> dict:
    """Export a sandbox project as a zip file. Returns the zip path and size."""
    await _ensure_db()
    from app.services.export_service import export_sandbox_zip

    result = await export_sandbox_zip(project_id)
    return result


@mcp.tool()
async def publish_to_github(
    project_id: str,
    repo_name: str = "",
    private: bool = True,
) -> dict:
    """Publish a sandbox project to GitHub. Creates a new repo and pushes the code.

    Requires `gh` CLI to be authenticated. Returns the GitHub repo URL.
    """
    await _ensure_db()
    from app.services.export_service import publish_to_github as _publish

    result = await _publish(
        project_id=project_id,
        repo_name=repo_name or None,
        private=private,
    )
    return result


# --- Corpus Tools ---


@mcp.tool()
async def search_similar_solutions(query: str, top_k: int = 5) -> dict:
    """Search the solution corpus for existing products similar to a query.

    Useful for checking if an opportunity has existing competitors.
    """
    await _ensure_db()
    from app.services.solution_corpus_service import find_similar_solutions as _find

    results = await _find(query, top_k=top_k)
    return {
        "query": query,
        "count": len(results),
        "solutions": results,
    }


# --- Resources ---


@mcp.resource("foxhound://opportunities/{opportunity_id}")
async def opportunity_resource(opportunity_id: str) -> str:
    """Get a marketplace opportunity as a resource."""
    await _ensure_db()
    import json
    from app.services.marketplace_service import get_marketplace_opportunity

    opportunity = await get_marketplace_opportunity(opportunity_id)
    if not opportunity:
        return json.dumps({"error": "Not found"})
    return json.dumps(opportunity, default=str)


@mcp.resource("foxhound://artifacts/{artifact_id}")
async def artifact_resource(artifact_id: str) -> str:
    """Get an execution artifact as a resource."""
    await _ensure_db()
    import json
    from app.services.execution_artifact_service import get_artifact

    artifact = await get_artifact(artifact_id)
    if not artifact:
        return json.dumps({"error": "Not found"})
    return json.dumps(artifact, default=str)


@mcp.resource("foxhound://skills/{bundle_id}")
async def skill_resource(bundle_id: str) -> str:
    """Get a skill bundle as a resource."""
    await _ensure_db()
    import json
    from app.services.skill_bundle_service import get_skill_bundle

    bundle = await get_skill_bundle(bundle_id)
    if not bundle:
        return json.dumps({"error": "Not found"})
    return json.dumps(bundle, default=str)


def main():
    """Entry point for `foxhound mcp` command."""
    mcp.run()


if __name__ == "__main__":
    main()
