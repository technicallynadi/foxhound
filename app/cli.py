#!/usr/bin/env python3
"""Foxhound CLI — Opportunity intelligence from the command line."""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import logging

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(override=True)

# Show TinyFish progress in CLI
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler()],
)
# Quiet noisy loggers
for _name in ("httpx", "httpcore", "sqlalchemy", "asyncio"):
    logging.getLogger(_name).setLevel(logging.WARNING)

from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_out(data, compact=False):
    """Print JSON to stdout."""
    indent = None if compact else 2
    print(json.dumps(data, indent=indent, default=str))


def _print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def _print_funnel(debug: dict):
    """Print the pipeline funnel from debug data."""
    stages = [
        ("Ingested", "total_ingested"),
        ("After relevance gate", "after_relevance_gate"),
        ("After workflow gate", "after_workflow_gate"),
        ("NLP signals extracted", "nlp_signals_extracted"),
        ("Total signals", "total_signals"),
        ("Total candidates", "total_candidates"),
        ("Total clusters", "total_clusters"),
        ("After eligibility gate", "after_eligibility_gate"),
        ("After validity gate", "after_validity_gate"),
    ]
    print("  Pipeline Funnel:")
    for label, key in stages:
        val = debug.get(key)
        if val is not None:
            print(f"    {label:<30} {val}")

    tf_runs = debug.get("tinyfish_runs", {})
    if tf_runs:
        total = tf_runs.get("total", 0)
        completed = tf_runs.get("completed", 0)
        failed = tf_runs.get("failed", 0)
        print(f"\n  TinyFish Runs: {total} total, {completed} completed, {failed} failed")


def _print_opportunity(i, opp):
    """Print a single opportunity result."""
    print(f"\n  [{i+1}] {opp.get('title', 'Untitled')}")
    print(f"      Score: {opp.get('opportunity_score', 0):.2f}  |  Confidence: {opp.get('confidence', 'low')}")
    if opp.get("workflow"):
        print(f"      Workflow: {opp['workflow']}")
    if opp.get("breakpoint"):
        print(f"      Breakpoint: {opp['breakpoint']}")
    if opp.get("gap"):
        print(f"      Gap: {opp['gap']}")
    if opp.get("build_wedge"):
        print(f"      Wedge: {opp['build_wedge']}")
    if opp.get("summary"):
        print(f"      Summary: {opp['summary'][:200]}")
    if opp.get("persona"):
        personas = opp["persona"] if isinstance(opp["persona"], list) else [opp["persona"]]
        print(f"      Personas: {', '.join(personas)}")
    if opp.get("current_solutions"):
        print(f"      Current tools: {', '.join(opp['current_solutions'][:5])}")
    # Buildability
    ba = opp.get("buildability")
    if ba:
        print(f"\n      Buildability: {ba.get('score', '?')}/1.0  |  Narrowness: {ba.get('scope_narrowness', '?')}/1.0  |  User clarity: {ba.get('clarity_of_user', '?')}/1.0")
        if ba.get("monetization_path"):
            print(f"      Monetization: {ba['monetization_path']}")
        if ba.get("why_now"):
            print(f"      Why now: {ba['why_now']}")

    # Wedge
    w = opp.get("wedge")
    if w:
        print(f"\n      --- WEDGE (narrow entry point) ---")
        if w.get("what_it_does"):
            print(f"      {w['what_it_does']}")
        if w.get("broken_step"):
            print(f"      Broken step: {w['broken_step']}")
        for step in w.get("core_flow", [])[:5]:
            print(f"        {step}")
        for entity in w.get("data_model", [])[:3]:
            fields = ", ".join(entity.get("fields", [])[:6])
            print(f"        Entity: {entity.get('entity', '?')} ({fields})")
        for ep in w.get("api_endpoints", [])[:6]:
            print(f"        {ep.get('method', '?')} {ep.get('path', '?')} — {ep.get('purpose', '')}")
        for screen in w.get("ui_screens", [])[:3]:
            print(f"        Screen: {screen.get('name', '?')} — {screen.get('purpose', '')}")
        if w.get("why_this_works"):
            print(f"      Why: {w['why_this_works']}")

    # System Design
    sd = opp.get("system_design")
    if sd:
        print(f"\n      --- SYSTEM DESIGN (full product) ---")
        if sd.get("what_it_becomes"):
            print(f"      {sd['what_it_becomes']}")
        for entity in sd.get("data_model", [])[:6]:
            fields = ", ".join(entity.get("fields", [])[:6])
            print(f"        Entity: {entity.get('entity', '?')} ({fields})")
        for ep in sd.get("api_endpoints", [])[:8]:
            print(f"        {ep.get('method', '?')} {ep.get('path', '?')} — {ep.get('purpose', '')}")
        for screen in sd.get("ui_screens", [])[:5]:
            print(f"        Screen: {screen.get('name', '?')} — {screen.get('purpose', '')}")
        if sd.get("integrations"):
            print(f"        Integrations: {', '.join(sd['integrations'][:5])}")

    # MVP Plan
    if opp.get("mvp_plan"):
        print(f"\n      MVP plan:")
        for step in opp["mvp_plan"][:6]:
            print(f"        - {step}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_search(args):
    """Search for opportunities."""
    t0 = time.monotonic()
    def _ts():
        return f"[{time.monotonic() - t0:.1f}s]"

    print(f"{_ts()} Starting...", flush=True)

    print(f"{_ts()} Importing pipeline...", flush=True)
    from app.services.pipeline import run_pipeline
    print(f"{_ts()} Pipeline imported", flush=True)

    print(f"{_ts()} DB init...", flush=True)
    try:
        from app.db.session import init_db
        await init_db()
    except Exception as e:
        print(f"{_ts()} DB init skipped: {e}", flush=True)
    print(f"{_ts()} Ready", flush=True)

    # None = TinyFish search-first (default). Explicit list = API fallback.
    sources = args.sources.split(",") if args.sources else None

    discovery_config = {"budget_limit": args.budget}

    _print_header(f"Searching: {args.query}")
    if sources:
        print(f"  Mode: API fallback ({', '.join(sources)})")
    else:
        print(f"  Mode: TinyFish search-first (budget={args.budget})")
    print(f"  TinyFish: {'enabled' if bool(settings.tinyfish_api_key) else 'no API key'}")
    print(f"  Limit: {args.limit}")
    print(flush=True)

    start = time.monotonic()
    report = await run_pipeline(
        topic=args.query,
        sources=sources,
        min_score=args.min_score,
        limit=args.limit,
        debug=True,
        premium=args.premium,
        discovery_config=discovery_config,
    )
    elapsed = round(time.monotonic() - start, 1)

    results = report.get("results", [])
    debug = report.get("debug", {})

    _print_funnel(debug)

    print(f"\n  Found {len(results)} opportunities in {elapsed}s")

    if not results:
        print("  No opportunities found. Try broader sources or enable --discovery.")
        return

    for i, opp in enumerate(results):
        _print_opportunity(i, opp)

    if args.json:
        print("\n--- JSON Output ---")
        _json_out(report)


async def cmd_inspect(args):
    """Inspect the pipeline trace."""
    from app.services.pipeline import run_pipeline
    from app.db.session import init_db
    await init_db()

    sources = args.sources.split(",") if args.sources else ["reddit", "github"]

    _print_header(f"Inspecting: {args.query}")

    report = await run_pipeline(
        topic=args.query,
        sources=sources,
        limit=args.limit,
        debug=True,
    )

    debug = report.get("debug", {})
    _print_funnel(debug)

    # Validity decisions
    validity = debug.get("validity_results", [])
    if validity:
        print("\n  Validity Decisions:")
        for v in validity[:10]:
            status = "VALID" if v.get("valid") else "REJECTED"
            reasons = ", ".join(v.get("fail_reasons", [])) or "passed"
            print(f"    [{status}] score={v.get('validity_score', 0):.2f} — {reasons}")

    # Rankings
    rankings = debug.get("rankings", [])
    if rankings:
        print("\n  Rankings:")
        for r in rankings[:10]:
            print(f"    #{r.get('rank', '?')} cluster={r.get('cluster_id', '?')[:8]}... score={r.get('score', 0):.3f}")

    if args.json:
        _json_out(debug)


async def cmd_resolve(args):
    """Resolve a query to a vertical."""
    from app.core.vertical_config import resolve_vertical, load_verticals

    key, match_type, confidence, matched_terms = resolve_vertical(args.query)

    _print_header(f"Resolving: {args.query}")
    print(f"  Vertical: {key or 'none'}")
    print(f"  Match type: {match_type}")
    print(f"  Confidence: {confidence}")
    if matched_terms:
        print(f"  Matched terms: {', '.join(matched_terms)}")

    if key:
        verticals = load_verticals()
        config = verticals.get(key, {})
        communities = config.get("communities", {})
        if communities:
            print(f"\n  Communities:")
            for tier, subs in communities.items():
                if subs:
                    if isinstance(subs, str):
                        subs = [subs]
                    print(f"    {tier}: {', '.join(subs)}")


async def cmd_verticals(args):
    """List all verticals."""
    from app.core.vertical_config import load_verticals

    verticals = load_verticals()
    _print_header("Verticals")
    for key, config in verticals.items():
        aliases = config.get("aliases", [])
        tools = config.get("tool_terms", [])
        print(f"  {key}")
        if aliases:
            print(f"    Aliases: {', '.join(aliases[:5])}")
        if tools:
            print(f"    Tools: {', '.join(tools[:5])}")
        print()



async def cmd_analyze(args):
    """Analyze a query (NLP)."""
    from app.services.ingest.query_analyzer import analyze_query

    profile = analyze_query(args.query)

    _print_header(f"Query Analysis: {args.query}")
    print(f"  Intent: {profile.get('intent', 'unknown')}")
    print(f"  Tools mentioned: {profile.get('tools_mentioned', [])}")
    print(f"  Domains: {profile.get('domains', [])}")
    print(f"  Search queries:")
    for q in profile.get("search_queries", []):
        print(f"    - {q}")

    if args.json:
        _json_out(profile)


async def cmd_tinyfish_job(args):
    """Run a TinyFish job."""
    from app.jobs.base import run_job
    from app.db.session import init_db
    await init_db()

    _print_header(f"TinyFish Job: {args.job_type}")
    print(f"  URL: {args.url}")
    if args.topic:
        print(f"  Topic: {args.topic}")
    print()

    start = time.monotonic()
    result = await run_job(args.job_type, args.url, args.topic)
    elapsed = round(time.monotonic() - start, 1)

    if result.get("error"):
        print(f"  Error: {result['error']}")
        return

    items = result.get("items", [])
    print(f"  Extracted {len(items)} items in {elapsed}s")

    for i, item in enumerate(items[:10]):
        title = item.get("title", item.get("workflow_name", ""))[:60]
        print(f"    [{i+1}] {title}")
        if item.get("text"):
            print(f"         {item['text'][:100]}")

    if args.json:
        _json_out(result)


async def cmd_tinyfish_jobs(args):
    """List available TinyFish jobs."""
    from app.jobs.tinyfish_jobs import get_job_registry

    _print_header("TinyFish Jobs")
    for job in get_job_registry().values():
        batch = "batch" if job.supports_batch else ""
        stream = "stream" if job.supports_stream else ""
        profile = f"  profile={job.default_profile}" if job.default_profile else ""
        modes = ", ".join(filter(None, [batch, stream]))
        print(f"  {job.job_type:<35} {job.description}")
        print(f"    modes: {modes}{profile}")
        print()


async def cmd_tinyfish_runs(args):
    """List TinyFish runs from DB."""
    from sqlalchemy import select
    from app.db.models.tinyfish_run import TinyFishRun
    from app.db.session import async_session, init_db
    await init_db()

    async with async_session() as session:
        stmt = select(TinyFishRun).order_by(TinyFishRun.created_at.desc())
        if args.job_type:
            stmt = stmt.where(TinyFishRun.job_type == args.job_type)
        if args.status:
            stmt = stmt.where(TinyFishRun.status == args.status)
        stmt = stmt.limit(args.limit)
        result = await session.execute(stmt)
        runs = result.scalars().all()

    _print_header(f"TinyFish Runs ({len(runs)})")
    for run in runs:
        status_icon = "OK" if run.status == "completed" else "FAIL"
        duration = f"{run.duration_ms}ms" if run.duration_ms else "?"
        profile = f"  [{run.browser_profile}]" if run.browser_profile else ""
        retry = f"  retries={run.retry_count}" if run.retry_count else ""
        error = f"  error={run.error_type}" if run.error_type else ""
        print(f"  [{status_icon}] {run.job_type:<25} {run.items_extracted} items  {duration}{profile}{retry}{error}")
        print(f"         {run.url[:70]}")
        if run.topic:
            print(f"         topic={run.topic}")

    if args.json:
        _json_out([{
            "id": r.id, "job_type": r.job_type, "status": r.status,
            "items_extracted": r.items_extracted, "duration_ms": r.duration_ms,
            "error_type": r.error_type, "url": r.url, "topic": r.topic,
        } for r in runs])


async def cmd_preview(args):
    """Generate a preview for an opportunity."""
    from app.services.pipeline import run_pipeline
    from app.services.preview.preview_service import generate_preview
    from app.db.session import init_db
    await init_db()

    sources = args.sources.split(",") if args.sources else ["reddit", "github"]

    _print_header(f"Preview: {args.query}")

    report = await run_pipeline(topic=args.query, sources=sources, limit=args.index + 1)
    results = report.get("results", [])

    if not results or args.index >= len(results):
        print("  No opportunities found for preview.")
        return

    opp = results[args.index]
    guidance = opp.get("implementation_guidance") or {}

    print(f"  Generating preview for: {opp.get('title', 'Untitled')}")
    result = await generate_preview(artifact=opp, guidance=guidance)
    print(f"  Status: {result.get('status', 'unknown')}")

    if result.get("preview_spec"):
        spec = result["preview_spec"]
        print(f"  App: {spec.get('app_name', '?')}")
        print(f"  Screens: {len(spec.get('screens', []))}")
        print(f"  Entities: {len(spec.get('entities', []))}")
        print(f"  Endpoints: {len(spec.get('api_endpoints', []))}")

    if result.get("generated_files"):
        files = result["generated_files"]
        print(f"\n  Generated {len(files)} files:")
        for f in files[:15]:
            print(f"    {f.get('path', '')}")

    if args.json:
        _json_out(result)


async def cmd_ml_status(args):
    """Show ML model status."""
    from app.ml.model_registry import get_status

    status = get_status()
    _print_header("ML Model Status")
    for model, info in status.items():
        available = "loaded" if info.get("available") else "not available"
        print(f"  {model}: {available}")
        for k, v in info.items():
            if k != "available":
                print(f"    {k}: {v}")


async def cmd_ml_train(args):
    """Train an ML model."""
    from app.ml.training_pipeline import train_relevance_model
    from app.db.session import init_db
    await init_db()

    _print_header(f"Training: {args.component}")
    if args.component == "relevance":
        result = train_relevance_model()
        print(f"  Status: {result.get('status', 'unknown')}")
        if result.get("metrics"):
            for label, score in result["metrics"].items():
                print(f"    {label}: F1={score:.3f}")
    else:
        print(f"  Unknown component: {args.component}")


async def cmd_dataset(args):
    """Generate a training dataset."""
    from app.services.pipeline import run_pipeline
    from app.services.dataset.dataset_generator import generate_dataset_from_docs
    from app.services.normalize.normalize_service import normalize_documents
    from app.services.ingest.ingest_service import ingest_topic
    from app.db.session import init_db
    await init_db()

    sources = args.sources.split(",") if args.sources else ["reddit"]

    _print_header(f"Dataset Generation: {args.query}")

    raw_docs = await ingest_topic(args.query, sources)
    normalized = normalize_documents(raw_docs)
    labeled = generate_dataset_from_docs(args.query, normalized)

    print(f"  Total examples: {len(labeled)}")
    if labeled:
        domain = sum(1 for d in labeled if d.get("domain_relevant"))
        workflow = sum(1 for d in labeled if d.get("workflow_relevant"))
        opp = sum(1 for d in labeled if d.get("opportunity_relevant"))
        print(f"  Domain relevant: {domain}/{len(labeled)} ({100*domain/len(labeled):.0f}%)")
        print(f"  Workflow relevant: {workflow}/{len(labeled)} ({100*workflow/len(labeled):.0f}%)")
        print(f"  Opportunity relevant: {opp}/{len(labeled)} ({100*opp/len(labeled):.0f}%)")

    if args.json:
        _json_out(labeled[:5])


async def cmd_server(args):
    """Start the Foxhound API server."""
    import uvicorn
    print(f"Starting Foxhound on port {args.port}...")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


async def cmd_reprocess(args):
    """Re-process persisted signals from a failed run through Pipeline V2."""
    from app.db.session import init_db
    from app.services.run_service import load_persisted_signals
    from app.services.pipeline_v2 import run_pipeline_v2_from_documents

    await init_db()
    signals = load_persisted_signals(args.run_id)
    if not signals:
        print(f"No persisted signals found for {args.run_id}")
        print(f"Check data/signals/{args.run_id}.json")
        return

    print(f"Found {len(signals)} persisted signals for {args.run_id}")

    # Extract topic from the saved data
    import json, pathlib
    signals_path = pathlib.Path(__file__).resolve().parents[1] / "data" / "signals" / f"{args.run_id}.json"
    data = json.loads(signals_path.read_text())
    topic = data.get("topic", "unknown")

    print(f"Topic: {topic}")
    print(f"Re-processing through Pipeline V2...")

    report = await run_pipeline_v2_from_documents(
        topic=topic,
        raw_docs=signals,
        min_score=0.0,
        limit=10,
        debug=True,
        premium=args.premium,
    )

    results = report.get("results", [])
    print(f"\nPipeline V2 completed: {len(results)} opportunities")
    for r in results:
        tier = r.get("effort_tier", "?")
        score = r.get("opportunity_score", 0)
        title = r.get("title", "Untitled")
        print(f"  [{tier}] {title} (score={score:.2f})")
        if r.get("one_liner"):
            print(f"    {r['one_liner']}")

    # Save report
    report_path = pathlib.Path(__file__).resolve().parents[1] / "data" / "signals" / f"{args.run_id}_report.json"
    report_path.write_text(json.dumps(report, default=str, indent=2))
    print(f"\nReport saved to {report_path}")


async def cmd_worker(args):
    """Run the Foxhound async job worker."""
    from app.db.session import init_db
    from app.services.run_service import worker_loop

    await init_db()
    print(f"Starting Foxhound worker (poll={args.poll}s, once={args.once}, run_id={args.run_id or 'any'})...")
    await worker_loop(
        poll_interval=args.poll,
        worker_id=args.worker_id,
        once=args.once,
        run_id=args.run_id,
    )


async def cmd_jobs(args):
    """List Foxhound async jobs and optionally requeue stale ones."""
    from app.db.session import init_db
    from app.services.run_service import list_jobs, requeue_stale_jobs

    await init_db()
    if args.requeue_stale:
        reclaimed = await requeue_stale_jobs()
        print(f"Requeued {reclaimed} stale jobs")

    jobs = await list_jobs(limit=args.limit, status=args.status)
    _print_header(f"Foxhound Jobs ({len(jobs)})")
    for job in jobs:
        lease = f" lease={job['lease_owner']}" if job.get("lease_owner") else ""
        err = f" error={job['error_message']}" if job.get("error_message") else ""
        print(
            f"  [{job['status']}] prio={job.get('priority')} origin={job.get('origin')} "
            f"{job['job_id']} run={job['run_id']} "
            f"attempts={job['attempts']}/{job['max_attempts']}{lease}{err}"
        )
    if args.json:
        _json_out(jobs)


async def cmd_janitor(args):
    """Run janitor maintenance for stale jobs and queue health."""
    from app.db.session import init_db
    from app.services.run_service import get_queue_health, janitor_loop

    await init_db()
    print(f"Starting Foxhound janitor (poll={args.poll}s, once={args.once})...")
    await janitor_loop(poll_interval=args.poll, once=args.once, log_health=not args.quiet)
    if args.json:
        _json_out(await get_queue_health())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="foxhound",
        description="Foxhound — Opportunity Intelligence CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- search ---
    p = sub.add_parser("search", help="Search for opportunities")
    p.add_argument("query", help="Search query (e.g. 'property management')")
    p.add_argument("--sources", default=None, help="API fallback sources (e.g. reddit,github). Omit for TinyFish search-first mode")
    p.add_argument("--limit", type=int, default=5, help="Max results")
    p.add_argument("--min-score", type=float, default=0.0, help="Min opportunity score")
    p.add_argument("--budget", type=int, default=10, help="TinyFish extraction budget")
    p.add_argument("--premium", action="store_true", help="Use premium LLM model")
    p.add_argument("--json", action="store_true")

    # --- inspect ---
    p = sub.add_parser("inspect", help="Inspect pipeline trace (debug)")
    p.add_argument("query", help="Search query")
    p.add_argument("--sources", default="reddit,github")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")

    # --- resolve ---
    p = sub.add_parser("resolve", help="Resolve query to vertical")
    p.add_argument("query", help="Query to resolve")

    # --- verticals ---
    sub.add_parser("verticals", help="List all verticals")

    # --- analyze ---
    p = sub.add_parser("analyze", help="Analyze a query (NLP)")
    p.add_argument("query", help="Query to analyze")
    p.add_argument("--json", action="store_true")

    # --- tinyfish job ---
    p = sub.add_parser("tf-run", help="Run a TinyFish extraction job")
    p.add_argument("job_type", help="Job type (e.g. review_harvest)")
    p.add_argument("url", help="URL to extract from")
    p.add_argument("--topic", help="Topic context")
    p.add_argument("--json", action="store_true")

    # --- tinyfish jobs list ---
    sub.add_parser("tf-jobs", help="List available TinyFish job types")

    # --- tinyfish runs ---
    p = sub.add_parser("tf-runs", help="List TinyFish runs from DB")
    p.add_argument("--job-type", help="Filter by job type")
    p.add_argument("--status", help="Filter by status (completed/failed)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")

    # --- preview ---
    p = sub.add_parser("preview", help="Generate app preview for an opportunity")
    p.add_argument("query", help="Search query")
    p.add_argument("--sources", default="reddit,github")
    p.add_argument("--index", type=int, default=0, help="Opportunity index")
    p.add_argument("--json", action="store_true")

    # --- ml ---
    p = sub.add_parser("ml-status", help="Show ML model status")
    p = sub.add_parser("ml-train", help="Train ML model")
    p.add_argument("component", choices=["relevance", "ranker"], help="Model to train")

    # --- dataset ---
    p = sub.add_parser("dataset", help="Generate training dataset")
    p.add_argument("query", help="Topic for dataset")
    p.add_argument("--sources", default="reddit")
    p.add_argument("--json", action="store_true")

    # --- server ---
    p = sub.add_parser("server", help="Start the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")

    # --- worker ---
    p = sub.add_parser("worker", help="Run the Foxhound async job worker")
    p.add_argument("--poll", type=float, default=2.0, help="Seconds between queue polls")
    p.add_argument("--worker-id", default=None, help="Optional worker identifier")
    p.add_argument("--once", action="store_true", help="Claim and process a single job, then exit")
    p.add_argument("--run-id", default=None, help="Optionally process a specific run_id")

    # --- jobs ---
    p = sub.add_parser("jobs", help="List Foxhound async jobs")
    p.add_argument("--status", default=None, help="Filter by job status")
    p.add_argument("--limit", type=int, default=20, help="Max jobs to show")
    p.add_argument("--requeue-stale", action="store_true", help="Requeue stale leased jobs before listing")
    p.add_argument("--json", action="store_true")

    # --- janitor ---
    p = sub.add_parser("janitor", help="Run Foxhound queue maintenance")
    p.add_argument("--poll", type=float, default=15.0, help="Seconds between maintenance passes")
    p.add_argument("--once", action="store_true", help="Run one maintenance pass and exit")
    p.add_argument("--quiet", action="store_true", help="Suppress health logs")
    p.add_argument("--json", action="store_true")

    # --- reprocess ---
    p = sub.add_parser("reprocess", help="Re-process persisted signals from a failed run")
    p.add_argument("run_id", help="Run ID to reprocess")
    p.add_argument("--premium", action="store_true", help="Use premium LLM model")

    # --- mcp ---
    sub.add_parser("mcp", help="Run the Foxhound MCP server (stdio transport)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "search": cmd_search,
        "inspect": cmd_inspect,
        "resolve": cmd_resolve,
        "verticals": cmd_verticals,
        "analyze": cmd_analyze,
        "tf-run": cmd_tinyfish_job,
        "tf-jobs": cmd_tinyfish_jobs,
        "tf-runs": cmd_tinyfish_runs,
        "preview": cmd_preview,
        "ml-status": cmd_ml_status,
        "ml-train": cmd_ml_train,
        "dataset": cmd_dataset,
        "server": cmd_server,
        "worker": cmd_worker,
        "jobs": cmd_jobs,
        "janitor": cmd_janitor,
        "reprocess": cmd_reprocess,
    }

    if args.command == "mcp":
        from app.mcp_server import main as mcp_main
        mcp_main()
        return

    handler = commands.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    if args.command == "server":
        asyncio.run(handler(args))
    else:
        asyncio.run(handler(args))


if __name__ == "__main__":
    main()
