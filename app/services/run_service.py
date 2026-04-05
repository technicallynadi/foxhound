import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, or_, select

from app.db.models.foxhound_job import FoxhoundJob
from app.db.models.foxhound_run import FoxhoundRun
from app.db.session import async_session

logger = logging.getLogger(__name__)

PAGE_TYPE_TO_SOURCE_CLASS = {
    "forum": "pain_source",
    "reddit": "pain_source",
    "stackoverflow": "pain_source",
    "review": "incumbent_failure_source",
    "directory": "incumbent_failure_source",
    "product": "incumbent_failure_source",
    "comparison": "incumbent_failure_source",
    "alternatives": "incumbent_failure_source",
    "workflow": "workflow_description_source",
    "github": "workflow_description_source",
}

EVIDENCE_CLASS_TO_SOURCE_CLASS = {
    "pain": "pain_source",
    "workaround": "workflow_description_source",
    "request": "pain_source",
    "migration": "incumbent_failure_source",
    "workflow": "workflow_description_source",
    "reliability": "workflow_description_source",
    "operator_practice": "workflow_description_source",
    "market_pull": "incumbent_failure_source",
}


async def create_run(request: dict) -> str:
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC)
    created_event = _event(run_id, "run.created", {"query": request["query"], "mode": request.get("mode", "pipeline_run")}, timestamp=now)
    destination_ids = request.get("notification_destination_ids", [])
    destination_config = await resolve_notification_destinations(destination_ids)
    destination_config = _merge_direct_notification_destinations(
        destination_config,
        request.get("notification_destinations", {}) or {},
    )
    row = FoxhoundRun(
        id=run_id,
        query=request["query"],
        mode=request.get("mode", "pipeline_run"),
        status="queued",
        progress_percent=0,
        current_step="queued",
        premium=bool(request.get("premium")),
        notify_config_json=json.dumps(request.get("notify", {})),
        notification_destination_ids_json=json.dumps(destination_ids),
        notification_destinations_json=json.dumps(destination_config),
        notification_status_json=json.dumps(default_notification_status(request.get("notify", {}))),
        steps_json=json.dumps([_step("queued", "completed", "Run created")]),
        workers_json="[]",
        events_json=json.dumps([created_event]),
        created_at=now,
    )
    job = FoxhoundJob(
        id=job_id,
        run_id=run_id,
        origin=request.get("origin", "interactive"),
        priority=int(request.get("priority", 50)),
        payload_json=json.dumps(request),
        status="queued",
        created_at=now,
        updated_at=now,
    )
    async with async_session() as session:
        session.add(row)
        session.add(job)
        await session.commit()
    return run_id


async def get_run_status(run_id: str) -> dict | None:
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return None
    resource_counts = await _get_resource_counts(run_id)
    return {
        "run_id": row.id,
        "query": row.query,
        "mode": row.mode,
        "status": row.status,
        "progress_percent": row.progress_percent,
        "current_step": row.current_step,
        "steps": _load_json(row.steps_json, []),
        "workers": _load_json(row.workers_json, []),
        "resource_counts": resource_counts,
        "notify": _load_json(row.notify_config_json, {}),
        "notification_destination_ids": _load_json(row.notification_destination_ids_json, []),
        "notification_destinations": _mask_notification_destinations(_load_json(row.notification_destinations_json, {})),
        "notification_status": _load_json(row.notification_status_json, default_notification_status()),
        "output": _build_run_output(row.query, _load_json(row.result_json, None)),
        "events": _load_json(row.events_json, []),
        "result": _load_json(row.result_json, None),
        "error_message": row.error_message,
    }


async def list_jobs(limit: int = 50, status: str | None = None) -> list[dict]:
    async with async_session() as session:
        stmt = select(FoxhoundJob).order_by(FoxhoundJob.priority.desc(), FoxhoundJob.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(FoxhoundJob.status == status)
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [_job_to_dict(row) for row in rows]


async def get_job(job_id: str) -> dict | None:
    async with async_session() as session:
        row = await session.get(FoxhoundJob, job_id)
        if not row:
            return None
    return _job_to_dict(row)


async def cancel_run(run_id: str) -> bool:
    now = datetime.now(UTC)
    async with async_session() as session:
        run = await session.get(FoxhoundRun, run_id)
        if not run:
            return False
        result = await session.execute(
            select(FoxhoundJob).where(FoxhoundJob.run_id == run_id, FoxhoundJob.status.in_(("queued", "running")))
        )
        jobs = result.scalars().all()
        for job in jobs:
            job.status = "canceled"
            job.canceled_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = now
        run.status = "canceled"
        run.current_step = "canceled"
        run.completed_at = now
        steps = _load_json(run.steps_json, [])
        steps.append(_step("canceled", "canceled", "Run canceled"))
        run.steps_json = json.dumps(steps)
        events = _load_json(run.events_json, [])
        events.append(_event(run_id, "run.canceled", {"job_count": len(jobs)}, timestamp=now))
        run.events_json = json.dumps(events, default=str)
        await session.commit()
    return True


async def get_queue_health() -> dict:
    now = datetime.now(UTC)
    async with async_session() as session:
        result = await session.execute(
            select(FoxhoundJob.status, func.count(FoxhoundJob.id)).group_by(FoxhoundJob.status)
        )
        counts = {row[0]: row[1] for row in result.all()}

        stale_result = await session.execute(
            select(func.count(FoxhoundJob.id)).where(
                (FoxhoundJob.status == "running") & (FoxhoundJob.lease_expires_at < now)
            )
        )
        stale_jobs = stale_result.scalar_one() or 0

        oldest_result = await session.execute(
            select(FoxhoundJob.created_at)
            .where(FoxhoundJob.status == "queued")
            .order_by(FoxhoundJob.created_at.asc())
            .limit(1)
        )
        oldest_queued_at = oldest_result.scalar_one_or_none()

        avg_queue_result = await session.execute(
            select(func.avg(FoxhoundJob.queued_duration_ms)).where(FoxhoundJob.queued_duration_ms.is_not(None))
        )
        avg_run_result = await session.execute(
            select(func.avg(FoxhoundJob.run_duration_ms)).where(FoxhoundJob.run_duration_ms.is_not(None))
        )
        average_queue_duration_ms = avg_queue_result.scalar_one()
        average_run_duration_ms = avg_run_result.scalar_one()

    return {
        "total_jobs": sum(counts.values()),
        "queued_jobs": counts.get("queued", 0),
        "running_jobs": counts.get("running", 0),
        "completed_jobs": counts.get("completed", 0),
        "failed_jobs": counts.get("failed", 0),
        "stale_jobs": stale_jobs,
        "average_queue_duration_ms": round(float(average_queue_duration_ms), 2) if average_queue_duration_ms is not None else None,
        "average_run_duration_ms": round(float(average_run_duration_ms), 2) if average_run_duration_ms is not None else None,
        "oldest_queued_at": oldest_queued_at.isoformat() if oldest_queued_at else None,
    }


async def list_run_resources(run_id: str) -> list[dict]:
    async with async_session() as session:
        stmt = (
            select(ResourceCandidate)
            .where(ResourceCandidate.run_id == run_id)
            .order_by(ResourceCandidate.priority.desc(), ResourceCandidate.confidence.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [
        {
            "resource_id": row.id,
            "url": row.url,
            "source_class": row.source_class,
            "evidence_class": (_load_json(row.provenance_json, {}) or {}).get("evidence_class"),
            "page_type": row.page_type,
            "discovered_by": row.discovered_by,
            "confidence": row.confidence,
            "priority": row.priority,
            "status": row.status,
            "discovery_reason": row.discovery_reason,
            "routing_tags": _load_json(row.routing_tags_json, []),
            "provenance": _load_json(row.provenance_json, {}),
        }
        for row in rows
    ]


async def list_run_events(run_id: str) -> list[dict]:
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return []
    return _load_json(row.events_json, [])


async def _execute_run(run_id: str, request: dict) -> None:
    from app.services.ingest.community_router import route_query
    from app.services.ingest.ingest_service import (
        _dispatch_workers,
        _navigate_seed_urls,
        _save_discovered_sources,
        _to_raw_document,
        build_source_family_candidates,
        get_learned_sources,
    )
    from app.services.ingest.query_analyzer import analyze_query
    from app.services.ingest.query_translator import is_conversational, translate_query
    from app.services.ingest.tinyfish_adapter import search_multiple_queries
    from app.services.pipeline_v2 import run_pipeline_v2_from_documents
    from app.services.query_memory_service import get_query_memory_seed

    query = request["query"]
    config = request.get("discovery") or {}
    is_quick_scan = request.get("mode") == "quick_scan"
    if is_quick_scan:
        # Quick scan: reduced budget for faster results
        config.setdefault("max_extractions", 4)
        config.setdefault("budget_limit", 4)
        config.setdefault("max_discovered_urls", 4)
        request["premium"] = False
    minimal_tinyfish_only = bool(config.get("minimal_tinyfish_only"))
    try:
        await _append_run_event(run_id, "run.started", {"mode": request.get("mode", "pipeline_run")})

        # translate conversational queries into research queries
        translation = None
        if is_conversational(query) and not minimal_tinyfish_only:
            await _update_run(run_id, status="translating", progress=3, current_step="translating", message="Understanding your request")
            translation = await translate_query(query)
            await _append_run_event(run_id, "run.query_translated", {
                "original": query,
                "intent": translation.get("intent", {}),
                "research_queries": translation.get("research_queries", []),
            })
            # use the first research query as the primary pipeline query
            research_queries = translation.get("research_queries", [])
            if research_queries:
                query = research_queries[0]
                # store additional queries for expanded search
                config["expanded_queries"] = research_queries[1:]
                config["translation"] = translation
                logger.info("Translated conversational query to: %s (+ %d expanded)", query, len(research_queries) - 1)

        await _update_run(run_id, status="routing", progress=5, current_step="routing", message="Building routing plan")
        routing_plan = route_query(query)
        if minimal_tinyfish_only:
            routing_plan = {
                "raw_query": query,
                "normalized_query": query,
                "resolved_vertical": None,
                "match_type": "minimal_tinyfish_only",
                "confidence": 1.0,
                "matched_terms": [],
                "main": [],
                "primary": [],
                "secondary": [],
                "fallback": [],
                "strategy": "tinyfish_search_only",
            }
        debug_query_first = bool(config.get("debug_query_first"))
        memory_seed = None if (debug_query_first or minimal_tinyfish_only) else await get_query_memory_seed(query, routing_plan.get("resolved_vertical"))
        if memory_seed:
            config["memory_search_queries"] = [str(item) for item in (memory_seed.get("search_queries", []) or [])[:5] if item]
        discovery_plan = _build_discovery_plan(query, routing_plan, config)
        if memory_seed:
            prior_workers = set(memory_seed.get("source_families", []))
            discovery_plan["learned_query_memory"] = {
                "query_memory_id": memory_seed.get("query_memory_id"),
                "priority_score": memory_seed.get("priority_score", 0.0),
            }
            discovery_plan["workers"] = [
                worker for worker in discovery_plan["workers"]
                if worker.get("worker") in prior_workers or worker.get("worker") == "learned_sources"
            ] + [
                worker for worker in discovery_plan["workers"]
                if worker.get("worker") not in prior_workers and worker.get("worker") != "learned_sources"
            ]
        worker_names = [worker["worker"] for worker in discovery_plan["workers"]]
        await _update_run(
            run_id,
            routing_plan=routing_plan,
            discovery_plan=discovery_plan,
            workers=[_worker_state(name, "pending") for name in worker_names],
        )
        await _append_run_event(run_id, "run.routing.completed", {"routing_plan": routing_plan, "discovery_plan": discovery_plan})
        if memory_seed:
            await _append_run_event(run_id, "run.query_memory.reused", {
                "query_memory_id": memory_seed.get("query_memory_id"),
                "search_query_count": len(memory_seed.get("search_queries", [])),
                "source_family_count": len(memory_seed.get("source_families", [])),
            })
        if minimal_tinyfish_only:
            logger.info("Minimal TinyFish-only raw mode enabled for query: %s", query)
            await _append_run_event(run_id, "run.minimal_tinyfish_only", {
                "query": query,
                "raw_mode": True,
            })

        await _update_run(run_id, status="discovering_sources", progress=20, current_step="discovering_sources", message="Finding sources")

        # ─── Focused Extraction Flow (default) ───
        use_focused = not minimal_tinyfish_only and not debug_query_first
        if use_focused:
            extraction_budget = int(config.get("max_extractions", 6))
            await _update_run(run_id, status="extracting", progress=30, current_step="extracting", message="Extracting signals from sources")
            raw_docs = await _focused_extraction_flow(
                run_id=run_id,
                query=query,
                vertical=routing_plan.get("resolved_vertical"),
                budget=extraction_budget,
                event_callback=lambda event_type, payload: _append_run_event(run_id, event_type, payload),
            )
            if not raw_docs:
                await _complete_run(run_id, status="partial_success", progress=100, result={"query": query, "results": [], "reason": "no_signals_extracted"})
                return

            await _update_run(run_id, status="validating", progress=65, current_step="validating", message=f"Analyzing {len(raw_docs)} signals")
            # Persist signals to disk before pipeline — recovery point if pipeline crashes
            _persist_raw_signals(run_id, query, raw_docs)
            report = await run_pipeline_v2_from_documents(
                topic=query,
                raw_docs=raw_docs,
                min_score=0.0,
                limit=10,
                debug=True,
                premium=bool(request.get("premium")),
                event_callback=lambda event_type, payload: _append_run_event(run_id, event_type, payload),
            )
            await _append_pipeline_events(run_id, report, skip_existing=True)
            await _complete_run(run_id, status="completed", progress=100, result=report)
            return

        # ─── Minimal TinyFish-only mode ───
        if minimal_tinyfish_only:
            max_results_per = int(config.get("max_results_per_query", config.get("max_discovered_urls", 10)))
            search_results = await search_multiple_queries([query], max_results_per=max_results_per)
            discovered = [_to_resource_candidate_input(item, "tinyfish_search", routing_plan) for item in search_results]
            await _replace_resources(run_id, discovered)
            await _append_run_event(run_id, "resources.discovered", {"count": len(discovered)})
            await _complete_run(
                run_id,
                status="completed",
                progress=100,
                result={
                    "query": query,
                    "results": [],
                    "minimal_tinyfish_only": True,
                    "tinyfish_results": search_results,
                    "discovered_resources": [
                        {
                            "url": item["url"],
                            "title": item.get("title", ""),
                            "page_type": item.get("page_type", ""),
                            "discovered_by": item.get("discovered_by", ""),
                            "reason": item.get("discovery_reason", ""),
                        }
                        for item in discovered
                    ],
                },
            )
            return
        vertical = routing_plan.get("resolved_vertical")
        profile = analyze_query(query)
        learned_sources = [] if debug_query_first else await get_learned_sources(query, vertical, limit=8)
        family_candidates = {} if debug_query_first else build_source_family_candidates(query, routing_plan, profile, vertical)
        tasks = {}
        if learned_sources:
            tasks["learned_sources"] = asyncio.create_task(_wrap_sync(learned_sources))
        for family_name, family_items in family_candidates.items():
            if family_items:
                tasks[f"{family_name}_family"] = asyncio.create_task(_wrap_sync(family_items))
        if discovery_plan.get("seed_urls") and vertical:
            tasks["seed_navigation"] = asyncio.create_task(_navigate_seed_urls(query, vertical))
        if discovery_plan.get("enable_web_search") and _should_use_broad_search(learned_sources, family_candidates, discovery_plan):
            tasks["web_search"] = asyncio.create_task(search_multiple_queries(profile.get("evidence_queries", []) or profile.get("search_queries", []), max_results_per=6))
        if discovery_plan.get("expanded_queries") and _should_use_broad_search(learned_sources, family_candidates, discovery_plan):
            tasks["source_expansion"] = asyncio.create_task(search_multiple_queries(discovery_plan["expanded_queries"], max_results_per=5))
        # translated query expansion: search additional research queries from conversational translation
        translated_queries = [str(item) for item in (config.get("expanded_queries", []) or []) if item]
        memory_queries = [str(item) for item in (config.get("memory_search_queries", []) or []) if item]
        combined_queries = list(dict.fromkeys(translated_queries + memory_queries))
        if combined_queries and "translated_search" not in tasks:
            tasks["translated_search"] = asyncio.create_task(search_multiple_queries(combined_queries, max_results_per=5))

        await _update_run(run_id, workers=[_worker_state(name, "running") for name in tasks.keys()])
        for name in tasks.keys():
            await _append_run_event(run_id, "worker.started", {"worker": name})
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        discovered: list[dict] = []
        worker_states = []
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Discovery worker %s failed: %s", name, result)
                worker_states.append(_worker_state(name, "failed", message=str(result)))
                await _append_run_event(run_id, "worker.failed", {"worker": name, "error": str(result)})
                continue
            items = result if isinstance(result, list) else []
            worker_states.append(_worker_state(name, "completed", discovered_count=len(items)))
            await _append_run_event(run_id, "worker.completed", {"worker": name, "discovered_count": len(items)})
            discovered.extend(_to_resource_candidate_input(item, name, routing_plan) for item in items)

        merged_resources = _merge_and_rank_resources(discovered, query, max_per_domain=discovery_plan["max_per_domain"])
        await _replace_resources(run_id, merged_resources)
        await _append_run_event(run_id, "resources.discovered", {"count": len(merged_resources)})

        selected_resources = merged_resources[: discovery_plan["max_discovered_urls"]]
        await _mark_selected_resources(run_id, {item["normalized_url"] for item in selected_resources})
        await _append_run_event(
            run_id,
            "resources.selected",
            {"count": len(selected_resources), "top_urls": [item["url"] for item in selected_resources[:5]]},
        )

        await _update_run(
            run_id,
            status="extracting",
            progress=45,
            current_step="extracting",
            message=f"Selected {len(selected_resources)} resources for extraction",
            workers=_apply_selected_counts(worker_states, selected_resources),
        )

        if not selected_resources:
            await _complete_run(run_id, status="partial_success", progress=100, result={"query": query, "results": [], "reason": "no_resources_selected"})
            return

        extraction_budget = min(discovery_plan["max_extractions"], len(selected_resources))
        selected_pages = [
            {
                "url": item["url"],
                "page_type": item["page_type"],
                "title": item.get("title", ""),
                "source": item["discovered_by"],
                "source_class": item.get("source_class"),
                "reason": item.get("discovery_reason", ""),
                "search_query": item.get("provenance", {}).get("search_query", ""),
                "quality_score": item.get("provenance", {}).get("quality_score"),
                "learned_score": item.get("provenance", {}).get("learned_score"),
            }
            for item in selected_resources[:extraction_budget]
        ]
        extracted = await _dispatch_workers(
            selected_pages,
            query,
            extraction_budget,
            vertical,
            event_callback=lambda event_type, payload: _append_run_event(run_id, event_type, payload),
        )
        await _mark_extracted_resources(run_id, extracted)
        await _save_discovered_sources(selected_pages, extracted, query, vertical)
        await _append_run_event(run_id, "extraction.completed", {"count": len(extracted)})

        if request.get("mode") == "discovery_only":
            await _complete_run(
                run_id,
                status="completed",
                progress=100,
                result={"query": query, "results": [], "discovery_only": True, "extracted_count": len(extracted)},
            )
            return

        await _update_run(run_id, status="validating", progress=65, current_step="validating", message="Running downstream pipeline")
        raw_docs = [_to_raw_document(doc, "tinyfish", query) for doc in extracted]
        _persist_raw_signals(run_id, query, raw_docs)
        report = await run_pipeline_v2_from_documents(
            topic=query,
            raw_docs=raw_docs,
            min_score=0.0,
            limit=10,
            debug=True,
            premium=bool(request.get("premium")),
            event_callback=lambda event_type, payload: _append_run_event(run_id, event_type, payload),
        )
        await _append_pipeline_events(run_id, report, skip_existing=True)
        await _complete_run(run_id, status="completed", progress=100, result=report)
    except Exception as exc:
        logger.exception("Async run failed: %s", exc)
        await _complete_run(run_id, status="failed", progress=100, error_message=str(exc), result={"query": query, "results": []})


async def _focused_extraction_flow(
    run_id: str,
    query: str,
    vertical: str | None,
    budget: int = 10,
    event_callback=None,
) -> list[dict]:
    """New extraction flow using focused prompts and direct source targets.

    Uses client.agent.run() (blocking) with short, single-purpose prompts.
    Returns raw documents ready for the pipeline."""
    from app.services.ingest.extraction_parser import signals_to_raw_documents
    from app.services.ingest.extraction_prompts import get_prompts_for_source
    from app.services.ingest.source_targets import get_source_targets
    from app.services.ingest.tinyfish_adapter import run_focused_extraction

    targets = get_source_targets(query, vertical, budget=budget)
    await _append_run_event(run_id, "focused.targets_generated", {
        "count": len(targets),
        "sources": [t["source_type"] for t in targets],
    })

    all_docs = []
    calls_made = 0

    for target in targets:
        if calls_made >= budget:
            break

        url = target["url"]
        source_type = target["source_type"]
        profile = target.get("browser_profile", "lite")
        prompt_names = target.get("prompt_names") or get_prompts_for_source(source_type)

        # run first prompt for this target
        primary_prompt = prompt_names[0] if prompt_names else "pain"
        await _append_run_event(run_id, "focused.extracting", {
            "url": url, "prompt": primary_prompt, "source_type": source_type,
        })

        items = await run_focused_extraction(
            url=url,
            prompt_name=primary_prompt,
            topic=query,
            browser_profile=profile,
            event_callback=event_callback,
        )
        calls_made += 1

        if items:
            docs = signals_to_raw_documents(items, query, source_type)
            all_docs.extend(docs)
            await _append_run_event(run_id, "focused.extracted", {
                "url": url, "prompt": primary_prompt, "items": len(items),
            })

            # if first prompt yielded results and budget allows, run secondary prompts
            for secondary_prompt in prompt_names[1:]:
                if calls_made >= budget:
                    break
                secondary_items = await run_focused_extraction(
                    url=url,
                    prompt_name=secondary_prompt,
                    topic=query,
                    browser_profile=profile,
                    event_callback=event_callback,
                )
                calls_made += 1
                if secondary_items:
                    secondary_docs = signals_to_raw_documents(secondary_items, query, source_type)
                    all_docs.extend(secondary_docs)
        else:
            await _append_run_event(run_id, "focused.empty", {
                "url": url, "prompt": primary_prompt, "source_type": source_type,
            })

    logger.info("Focused extraction: %d docs from %d TinyFish calls across %d targets",
                len(all_docs), calls_made, len(targets))
    return all_docs


def _build_discovery_plan(query: str, routing_plan: dict, config: dict) -> dict:
    max_discovered_urls = config.get("max_discovered_urls", 12)
    max_extractions = config.get("max_extractions", 6)
    max_per_domain = config.get("max_per_domain", 2)
    debug_query_first = bool(config.get("debug_query_first"))
    communities = routing_plan.get("primary", [])[:3] + routing_plan.get("secondary", [])[:2]
    routing_confidence = float(routing_plan.get("confidence", 0.0) or 0.0)
    expanded_queries = [
        {"query": f"{query} manual workflow workaround", "evidence_class": "workaround"},
        {"query": f"{query} feature requests missing capability", "evidence_class": "request"},
        {"query": f"{query} wish there was a tool for this", "evidence_class": "request"},
        {"query": f"{query} we built an internal tool for this", "evidence_class": "operator_practice"},
        {"query": f"{query} reliability incidents failures", "evidence_class": "reliability"},
        {"query": f"{query} how teams run workflow stack", "evidence_class": "operator_practice"},
        {"query": f"{query} how teams handle this today", "evidence_class": "operator_practice"},
        {"query": f"{query} alternatives migration switch", "evidence_class": "migration"},
    ]
    if communities:
        expanded_queries.append({
            "query": f"{query} {' '.join(communities[:2])} what do teams use",
            "evidence_class": "market_pull",
        })
    workers = (
        [
            {"worker": "web_search"},
            {"worker": "source_expansion"},
            {"worker": "translated_search"},
        ]
        if debug_query_first
        else [
            {"worker": "learned_sources"},
            {"worker": "community_family"},
            {"worker": "forums_family"},
            {"worker": "reviews_family"},
            {"worker": "code_family"},
            {"worker": "workflow_family"},
            {"worker": "seed_navigation"},
            {"worker": "web_search"},
            {"worker": "source_expansion"},
        ]
    )
    return {
        "max_discovered_urls": max_discovered_urls,
        "max_extractions": max_extractions,
        "max_per_domain": max_per_domain,
        "enable_web_search": config.get("enable_web_search", True),
        "seed_urls": bool(routing_plan.get("resolved_vertical")) and routing_confidence >= 0.6,
        "expanded_queries": expanded_queries[:7],
        "workers": workers,
    }


def _build_community_resources(query: str, routing_plan: dict) -> list[dict]:
    communities = routing_plan.get("primary", [])[:3] + routing_plan.get("fallback", [])[:2]
    pages = []
    for community in communities:
        slug = community.strip().replace(" ", "")
        if not slug:
            continue
        pages.append({
            "url": f"https://www.reddit.com/r/{slug}/search/?q={query.replace(' ', '%20')}&restrict_sr=1&sort=top",
            "title": f"Reddit community search: {community}",
            "page_type": "reddit",
            "reason": f"Community-targeted search for {community}",
            "source": "community_router",
        })
    return pages


def _should_use_broad_search(
    learned_sources: list[dict],
    family_candidates: dict[str, list[dict]],
    discovery_plan: dict,
) -> bool:
    family_total = sum(len(items) for items in family_candidates.values())
    learned_total = len(learned_sources)
    enough_direct = family_total + learned_total >= max(discovery_plan.get("max_extractions", 6), 4)
    return not enough_direct


def _merge_and_rank_resources(items: list[dict], query: str, max_per_domain: int = 2) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in items:
        key = item["normalized_url"]
        current = merged.get(key)
        if current is None or item["priority"] > current["priority"]:
            merged[key] = item
        else:
            current["provenance"]["merged_from"].append(item["discovered_by"])
    ranked = list(merged.values())
    ranked.sort(key=lambda x: (x["priority"], x["confidence"]), reverse=True)
    domain_counts: dict[str, int] = {}
    filtered: list[dict] = []
    for item in ranked:
        domain = urlparse(item["url"]).netloc.lower().replace("www.", "")
        if domain_counts.get(domain, 0) >= max_per_domain:
            continue
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        filtered.append(item)
    return filtered


def _to_resource_candidate_input(item: dict, discovered_by: str, routing_plan: dict) -> dict:
    url = item.get("url", "")
    normalized_url = _normalize_url(url)
    page_type = item.get("page_type", "workflow")
    evidence_class = item.get("evidence_class")
    source_class = (
        item.get("source_class")
        or EVIDENCE_CLASS_TO_SOURCE_CLASS.get(evidence_class)
        or PAGE_TYPE_TO_SOURCE_CLASS.get(page_type, "workflow_description_source")
    )
    confidence = _resource_confidence(page_type, discovered_by, item)
    priority = _resource_priority(page_type, discovered_by, item)
    return {
        "url": url,
        "normalized_url": normalized_url,
        "source_class": source_class,
        "page_type": page_type,
        "discovery_reason": item.get("reason", ""),
        "discovered_by": discovered_by,
        "routing_tags": [
            routing_plan.get("resolved_vertical") or "unresolved",
            page_type,
            discovered_by,
            evidence_class or "unspecified_evidence",
        ],
        "confidence": confidence,
        "priority": priority,
        "provenance": {
            "source": item.get("source", discovered_by),
            "title": item.get("title", ""),
            "search_query": item.get("search_query", ""),
            "evidence_class": evidence_class,
            "merged_from": [discovered_by],
            "quality_score": item.get("quality_score"),
            "learned_score": item.get("learned_score"),
        },
        "raw_metadata": item,
        "title": item.get("title", ""),
    }


def _resource_confidence(page_type: str, discovered_by: str, item: dict | None = None) -> float:
    base = {
        "reddit": 0.9,
        "forum": 0.85,
        "github": 0.8,
        "workflow": 0.75,
        "comparison": 0.7,
        "alternatives": 0.7,
        "review": 0.65,
        "directory": 0.6,
        "product": 0.55,
    }.get(page_type, 0.5)
    item = item or {}
    if discovered_by == "learned_sources" or item.get("source") == "learned":
        base += 0.08
    base += min(float(item.get("quality_score", 0.0) or 0.0) / 20.0, 0.15)
    base += min(float(item.get("learned_score", 0.0) or 0.0) / 25.0, 0.12)
    if discovered_by == "source_expansion":
        base -= 0.05
    return round(min(max(base, 0.1), 0.99), 3)


def _resource_priority(page_type: str, discovered_by: str, item: dict | None = None) -> float:
    item = item or {}
    priority = _resource_confidence(page_type, discovered_by, item) * 10
    if discovered_by == "learned_sources" or item.get("source") == "learned":
        priority += 1.0
    priority += min(float(item.get("last_signal_count", 0) or 0), 3.0)
    return round(priority, 3)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc.lower()}{path}"


def _event(run_id: str, event_type: str, payload: dict, timestamp: datetime | None = None) -> dict:
    ts = timestamp or datetime.now(UTC)
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "event_type": event_type,
        "timestamp": ts.isoformat(),
        "run_id": run_id,
        "payload": payload,
    }


def _build_build_plans(results: list[dict]) -> list[dict]:
    plans = []
    for index, opp in enumerate(results):
        guidance = opp.get("implementation_guidance") or {}
        risks = list(guidance.get("technical_risks", [])) + list(guidance.get("product_risks", []))
        plans.append({
            "plan_id": f"plan_{index + 1}",
            "opportunity_title": opp.get("title", ""),
            "wedge": opp.get("build_wedge", ""),
            "workflow": opp.get("workflow", ""),
            "target_personas": opp.get("persona", []),
            "mvp_scope": opp.get("mvp_plan", []),
            "build_order": guidance.get("recommended_build_order", []) or opp.get("mvp_plan", []),
            "risks": risks[:8],
        })
    return plans


def _build_report_sections(query: str, results: list[dict], build_plans: list[dict]) -> list[dict]:
    top_titles = [item.get("title", "") for item in results[:5] if item.get("title")]
    return [
        {
            "section_id": "summary",
            "title": "Summary",
            "status": "completed",
            "content": {"query": query, "opportunity_count": len(results), "top_titles": top_titles},
        },
        {
            "section_id": "opportunities",
            "title": "Opportunities",
            "status": "completed",
            "content": {"items": results},
        },
        {
            "section_id": "build_plans",
            "title": "Build Plans",
            "status": "completed",
            "content": {"items": build_plans},
        },
    ]


def _build_run_output(query: str, result: dict | None) -> dict | None:
    if not result:
        return None
    opportunities = result.get("results", [])
    build_plans = _build_build_plans(opportunities)
    return {
        "query": result.get("query", query),
        "generated_at": result.get("generated_at"),
        "opportunities": opportunities,
        "build_plans": build_plans,
        "report_sections": _build_report_sections(result.get("query", query), opportunities, build_plans),
        "debug": result.get("debug", {}),
    }


def _coerce_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _load_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _step(step: str, status: str, message: str | None = None) -> dict:
    return {
        "step": step,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "message": message,
    }


def _worker_state(worker: str, status: str, discovered_count: int = 0, selected_count: int = 0, message: str | None = None) -> dict:
    return {
        "worker": worker,
        "status": status,
        "discovered_count": discovered_count,
        "selected_count": selected_count,
        "message": message,
    }


def _apply_selected_counts(workers: list[dict], selected_resources: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for item in selected_resources:
        counts[item["discovered_by"]] = counts.get(item["discovered_by"], 0) + 1
    updated = []
    for worker in workers:
        worker["selected_count"] = counts.get(worker["worker"], 0)
        updated.append(worker)
    return updated


NOTIFICATION_MILESTONE_STEPS = {
    "discovering_sources": "Discovering sources",
    "extracting": "Extracting evidence",
    "validating": "Validating opportunities",
}


async def _update_run(
    run_id: str,
    status: str | None = None,
    progress: int | None = None,
    current_step: str | None = None,
    message: str | None = None,
    routing_plan: dict | None = None,
    discovery_plan: dict | None = None,
    workers: list[dict] | None = None,
) -> None:
    query = ""
    notify_config = {}
    notification_destinations = {}
    milestone_payload = None
    should_notify_milestone = False
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return
        query = row.query
        notify_config = _load_json(row.notify_config_json, {})
        notification_destinations = _load_json(row.notification_destinations_json, {})
        if status is not None:
            row.status = status
        if progress is not None:
            row.progress_percent = progress
        if current_step is not None:
            row.current_step = current_step
        if routing_plan is not None:
            row.routing_plan_json = json.dumps(routing_plan)
        if discovery_plan is not None:
            row.discovery_plan_json = json.dumps(discovery_plan)
        if workers is not None:
            row.workers_json = json.dumps(workers)
        if current_step or status:
            steps = _load_json(row.steps_json, [])
            steps.append(_step(current_step or row.current_step, status or row.status, message))
            row.steps_json = json.dumps(steps)
        if current_step in NOTIFICATION_MILESTONE_STEPS:
            events = _load_json(row.events_json, [])
            seen_step = any(
                event.get("event_type") == "run.milestone" and (event.get("payload", {}) or {}).get("step") == current_step
                for event in events
            )
            if not seen_step:
                milestone_payload = {
                    "step": current_step,
                    "title": NOTIFICATION_MILESTONE_STEPS[current_step],
                    "message": message,
                    "progress_percent": progress if progress is not None else row.progress_percent,
                }
                events.append(_event(run_id, "run.milestone", milestone_payload))
                row.events_json = json.dumps(events, default=str)
                should_notify_milestone = True
        await session.commit()
    if should_notify_milestone and any(bool(notify_config.get(channel)) for channel in ("discord", "slack", "sms")):
        await _deliver_and_record_notifications(
            run_id,
            query,
            "run.milestone",
            notify_config,
            notification_destinations,
            milestone_payload or {},
            None,
        )


async def _complete_run(
    run_id: str,
    status: str,
    progress: int,
    result: dict | None = None,
    error_message: str | None = None,
) -> None:
    query = ""
    notify_config = {}
    notification_destinations = {}
    output = None
    routing_plan = None
    discovery_plan = None
    mode = None
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return
        query = row.query
        mode = row.mode
        notify_config = _load_json(row.notify_config_json, {})
        notification_destinations = _load_json(row.notification_destinations_json, {})
        routing_plan = _load_json(row.routing_plan_json, {})
        discovery_plan = _load_json(row.discovery_plan_json, {})
        row.status = status
        row.progress_percent = progress
        row.current_step = status
        row.completed_at = datetime.now(UTC)
        row.error_message = error_message
        if result is not None:
            row.result_json = json.dumps(result, default=str)
        output = _build_run_output(row.query, result)
        steps = _load_json(row.steps_json, [])
        steps.append(_step(status, "completed" if status == "completed" else status, error_message))
        row.steps_json = json.dumps(steps)
        events = _load_json(row.events_json, [])
        events.append(_event(run_id, "run.completed" if status in {"completed", "partial_success"} else "run.failed", {
            "status": status,
            "error_message": error_message,
            "output": output,
        }))
        row.events_json = json.dumps(events, default=str)
        await session.commit()
    if status in {"completed", "partial_success"}:
        try:
            from app.services.query_memory_service import record_query_memory

            await record_query_memory(
                run_id=run_id,
                query=query,
                status=status,
                result=result or _load_json(getattr(row, "result_json", None), None),
                routing_plan=routing_plan,
                discovery_plan=discovery_plan,
                mode=mode,
            )
        except Exception as exc:
            logger.debug("Query memory persistence skipped for %s: %s", run_id, exc)
    await _deliver_and_record_notifications(
        run_id,
        query,
        "run.completed" if status in {"completed", "partial_success"} else "run.failed",
        notify_config,
        notification_destinations,
        {"status": status},
        output,
    )


async def _append_run_event(run_id: str, event_type: str, payload: dict) -> None:
    query = ""
    notify_config = {}
    notification_destinations = {}
    should_notify = False
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return
        query = row.query
        notify_config = _load_json(row.notify_config_json, {})
        notification_destinations = _load_json(row.notification_destinations_json, {})
        events = _load_json(row.events_json, [])
        if event_type == "run.milestone":
            is_first_of_type = not any(
                event.get("event_type") == event_type and (event.get("payload", {}) or {}).get("step") == payload.get("step")
                for event in events
            )
        else:
            is_first_of_type = not any(event.get("event_type") == event_type for event in events)
        existing_count = sum(1 for event in events if event.get("event_type") == event_type)
        events.append(_event(run_id, event_type, payload))
        row.events_json = json.dumps(events, default=str)
        await session.commit()
        should_notify = False
        if event_type == "run.started":
            should_notify = True
        elif event_type == "run.milestone":
            should_notify = is_first_of_type
        elif event_type in {"opportunity.created", "build_plan.created"}:
            should_notify = existing_count < 3
    if should_notify and any(bool(notify_config.get(channel)) for channel in ("discord", "slack", "sms")):
        await _deliver_and_record_notifications(run_id, query, event_type, notify_config, notification_destinations, payload, None)


async def _append_pipeline_events(run_id: str, report: dict, skip_existing: bool = False) -> None:
    existing_events = set()
    if skip_existing:
        existing = await list_run_events(run_id)
        existing_events = {
            (
                event.get("event_type"),
                json.dumps(event.get("payload", {}), sort_keys=True, default=str),
            )
            for event in existing
        }
    output = _build_run_output(report.get("query", ""), report)
    for section in output.get("report_sections", []):
        event_key = ("report.section.completed", json.dumps(section, sort_keys=True, default=str))
        if event_key not in existing_events:
            await _append_run_event(run_id, "report.section.completed", section)
    for opportunity in output.get("opportunities", []):
        payload = {
            "title": opportunity.get("title", ""),
            "score": opportunity.get("opportunity_score", 0.0),
            "workflow": opportunity.get("workflow", ""),
        }
        event_key = ("opportunity.created", json.dumps(payload, sort_keys=True, default=str))
        if event_key not in existing_events:
            await _append_run_event(run_id, "opportunity.created", payload)
    for plan in output.get("build_plans", []):
        event_key = ("build_plan.created", json.dumps(plan, sort_keys=True, default=str))
        if event_key not in existing_events:
            await _append_run_event(run_id, "build_plan.created", plan)


async def _deliver_and_record_notifications(
    run_id: str,
    query: str,
    event_type: str,
    notify_config: dict,
    notification_destinations: dict,
    payload: dict,
    output: dict | None,
) -> None:
    if not any(bool(notify_config.get(channel)) for channel in ("discord", "slack", "sms")):
        return

    source_event = event_type
    if source_event in {"run.completed", "run.failed"}:
        notification_state = await deliver_run_notifications(
            run_id,
            query,
            payload.get("status", source_event),
            notify_config,
            notification_destinations,
            output,
        )
    else:
        notification_state = await deliver_event_notifications(
            run_id,
            query,
            notify_config,
            notification_destinations,
            source_event,
            payload,
            output,
        )
    retry_attempts: list[dict] = []
    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return
        final_state = dict(notification_state)
        events = _load_json(row.events_json, [])
        for channel, state in notification_state.items():
            if not state.get("enabled") or state.get("status") == "disabled":
                continue
            notification_event_type = "notification.sent" if state.get("status") == "sent" else "notification.skipped"
            if state.get("status") == "failed":
                notification_event_type = "notification.failed"
            delivery_id = f"nd_{uuid.uuid4().hex[:10]}"
            session.add(NotificationDelivery(
                id=delivery_id,
                run_id=run_id,
                channel=channel,
                source_event=source_event,
                status=state.get("status", "unknown"),
                message=state.get("message"),
                http_status=state.get("http_status"),
            ))
            events.append(_event(run_id, notification_event_type, {"channel": channel, "source_event": source_event, **state}))
            if is_retryable_notification_failure(state):
                retry_attempts.append({
                    "channel": channel,
                    "retry_of_delivery_id": delivery_id,
                    "attempt_number": 2,
                })
        row.notification_status_json = json.dumps(final_state)
        row.events_json = json.dumps(events, default=str)
        await session.commit()

    if not retry_attempts:
        return

    await asyncio.sleep(0.5)
    retry_notify_config = {item["channel"]: True for item in retry_attempts}
    if source_event in {"run.completed", "run.failed"}:
        retry_state = await deliver_run_notifications(
            run_id,
            query,
            payload.get("status", source_event),
            retry_notify_config,
            notification_destinations,
            output,
        )
    else:
        retry_state = await deliver_event_notifications(
            run_id,
            query,
            retry_notify_config,
            notification_destinations,
            source_event,
            payload,
            output,
        )

    async with async_session() as session:
        row = await session.get(FoxhoundRun, run_id)
        if not row:
            return
        existing_status = _load_json(row.notification_status_json, {})
        events = _load_json(row.events_json, [])
        for attempt in retry_attempts:
            channel = attempt["channel"]
            state = retry_state.get(channel, {})
            if not state:
                continue
            existing_status[channel] = state
            retry_event_type = "notification.sent" if state.get("status") == "sent" else "notification.failed"
            if state.get("status") == "skipped":
                retry_event_type = "notification.skipped"
            session.add(NotificationDelivery(
                id=f"nd_{uuid.uuid4().hex[:10]}",
                run_id=run_id,
                channel=channel,
                source_event=source_event,
                status=state.get("status", "unknown"),
                retry_of_delivery_id=attempt["retry_of_delivery_id"],
                attempt_number=attempt["attempt_number"],
                message=state.get("message"),
                http_status=state.get("http_status"),
            ))
            events.append(_event(run_id, retry_event_type, {
                "channel": channel,
                "source_event": source_event,
                "auto_retry": True,
                "attempt_number": attempt["attempt_number"],
                **state,
            }))
        row.notification_status_json = json.dumps(existing_status)
        row.events_json = json.dumps(events, default=str)
        await session.commit()


def _mask_notification_destinations(destinations: dict) -> dict:
    return {
        "discord_configured": bool(destinations.get("discord_webhook_url")),
        "discord_audience_type": destinations.get("discord_audience_type", "human"),
        "discord_event_types": destinations.get("discord_event_types", []),
        "slack_configured": bool(destinations.get("slack_webhook_url")),
        "slack_audience_type": destinations.get("slack_audience_type", "human"),
        "slack_event_types": destinations.get("slack_event_types", []),
        "sms_phone_number": _mask_phone_number(destinations.get("sms_phone_number", "")),
        "sms_audience_type": destinations.get("sms_audience_type", "human"),
        "sms_event_types": destinations.get("sms_event_types", []),
    }


def _mask_phone_number(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return ""
    return f"***{digits[-4:]}"


def _merge_direct_notification_destinations(base: dict, direct: dict) -> dict:
    merged = dict(base or {})
    if direct.get("discord_webhook_url"):
        merged["discord_webhook_url"] = direct["discord_webhook_url"]
        merged["discord_audience_type"] = direct.get("discord_audience_type", merged.get("discord_audience_type", "human"))
        merged["discord_event_types"] = list(direct.get("discord_event_types") or merged.get("discord_event_types", []))
    if direct.get("slack_webhook_url"):
        merged["slack_webhook_url"] = direct["slack_webhook_url"]
        merged["slack_audience_type"] = direct.get("slack_audience_type", merged.get("slack_audience_type", "human"))
        merged["slack_event_types"] = list(direct.get("slack_event_types") or merged.get("slack_event_types", []))
    if direct.get("sms_phone_number"):
        merged["sms_phone_number"] = direct["sms_phone_number"]
        merged["sms_audience_type"] = direct.get("sms_audience_type", merged.get("sms_audience_type", "human"))
        merged["sms_event_types"] = list(direct.get("sms_event_types") or merged.get("sms_event_types", []))
    return merged


async def worker_loop(
    poll_interval: float = 2.0,
    worker_id: str | None = None,
    once: bool = False,
    run_id: str | None = None,
) -> None:
    worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
    target_run_id = run_id
    logger.info("Foxhound worker started: %s", worker_id)
    while True:
        claimed = await claim_next_job(worker_id, run_id=target_run_id)
        if not claimed:
            if once:
                return
            await asyncio.sleep(poll_interval)
            continue

        job_id, claimed_run_id, job_type, payload = claimed
        heartbeat_task = asyncio.create_task(_heartbeat_job(job_id, worker_id))
        try:
            await _execute_job(job_id, claimed_run_id, job_type, payload)
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            await complete_job(job_id, worker_id)
        except Exception as exc:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            logger.exception("Worker job failed: %s", exc)
            await fail_job(job_id, worker_id, str(exc))
        if once:
            return


async def janitor_loop(
    poll_interval: float = 15.0,
    once: bool = False,
    log_health: bool = True,
) -> None:
    logger.info("Foxhound janitor started")
    while True:
        reclaimed = await requeue_stale_jobs()
        health = await get_queue_health()
        if log_health:
            logger.info(
                "Queue health: total=%d queued=%d running=%d completed=%d failed=%d stale=%d reclaimed=%d",
                health["total_jobs"],
                health["queued_jobs"],
                health["running_jobs"],
                health["completed_jobs"],
                health["failed_jobs"],
                health["stale_jobs"],
                reclaimed,
            )
        if once:
            return
        await asyncio.sleep(poll_interval)


async def claim_next_job(
    worker_id: str,
    lease_seconds: int = 120,
    run_id: str | None = None,
) -> tuple[str, str, str, dict] | None:
    now = datetime.now(UTC)
    lease_expires_at = now.timestamp() + lease_seconds
    async with async_session() as session:
        stmt = (
            select(FoxhoundJob)
            .where(
                or_(
                    FoxhoundJob.status == "queued",
                    (FoxhoundJob.status == "running") & (FoxhoundJob.lease_expires_at < now),
                )
            )
            .where(FoxhoundJob.status != "canceled")
            .where(
                or_(
                    FoxhoundJob.next_scheduled_at.is_(None),
                    FoxhoundJob.next_scheduled_at <= now,
                )
            )
            .order_by(FoxhoundJob.priority.desc(), FoxhoundJob.created_at.asc())
            .limit(1)
        )
        if run_id:
            stmt = stmt.where(FoxhoundJob.run_id == run_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            return None

        job.status = "running"
        job.attempts += 1
        job.lease_owner = worker_id
        job.lease_expires_at = datetime.fromtimestamp(lease_expires_at, tz=UTC)
        created_at = _coerce_utc(job.created_at) or now
        job.queued_duration_ms = max((now - created_at).total_seconds() * 1000, 0)
        job.updated_at = now
        await session.commit()
        payload = _load_json(job.payload_json, {})
        return job.id, job.run_id, job.job_type or payload.get("job_type", "run_execution"), payload


async def _execute_job(job_id: str, run_id: str, job_type: str, payload: dict) -> None:
    normalized_job_type = (job_type or payload.get("job_type") or "run_execution").strip().lower()

    # --- Foxhound scheduling jobs ---
    foxhound_job_types = {
        "job_discovery", "autopilot_apply", "single_apply",
        "daily_digest", "stale_cleanup", "followup_check",
        "watchdog_sweep", "tinyfish_discovery",
    }
    if normalized_job_type in foxhound_job_types:
        from app.services.scheduling.executors import (
            execute_autopilot_apply,
            execute_daily_digest,
            execute_followup,
            execute_job_discovery,
            execute_single_apply,
            execute_stale_cleanup,
            execute_tinyfish_discovery,
            execute_watchdog_sweep,
        )
        from app.services.scheduling.scheduler import reschedule_completed_job

        async with async_session() as session:
            job = await session.get(FoxhoundJob, job_id)
            if not job:
                raise RuntimeError(f"Job not found: {job_id}")

        executor_map = {
            "job_discovery": execute_job_discovery,
            "autopilot_apply": execute_autopilot_apply,
            "single_apply": execute_single_apply,
            "daily_digest": execute_daily_digest,
            "stale_cleanup": execute_stale_cleanup,
            "followup_check": execute_followup,
            "watchdog_sweep": execute_watchdog_sweep,
            "tinyfish_discovery": execute_tinyfish_discovery,
        }
        await executor_map[normalized_job_type](job)

        # Reschedule if recurring
        await reschedule_completed_job(job)
        return

    raise RuntimeError(f"Unsupported job type: {job_type}")


async def renew_job_lease(job_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
    now = datetime.now(UTC)
    async with async_session() as session:
        job = await session.get(FoxhoundJob, job_id)
        if not job or job.status != "running" or job.lease_owner != worker_id:
            return False
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        await session.commit()
        return True


async def complete_job(job_id: str, worker_id: str) -> None:
    now = datetime.now(UTC)
    async with async_session() as session:
        job = await session.get(FoxhoundJob, job_id)
        if not job or job.lease_owner != worker_id:
            return
        job.status = "completed"
        job.completed_at = now
        job.updated_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        if job.completed_at and job.created_at:
            queue_ms = job.queued_duration_ms or 0.0
            created_at = _coerce_utc(job.created_at) or now
            total_ms = max((now - created_at).total_seconds() * 1000, 0)
            job.run_duration_ms = max(total_ms - queue_ms, 0.0)
        await session.commit()


async def fail_job(job_id: str, worker_id: str, error_message: str) -> None:
    now = datetime.now(UTC)
    async with async_session() as session:
        job = await session.get(FoxhoundJob, job_id)
        if not job or job.lease_owner != worker_id:
            return
        job.error_message = error_message
        job.updated_at = now
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.completed_at = now
            queue_ms = job.queued_duration_ms or 0.0
            created_at = _coerce_utc(job.created_at) or now
            total_ms = max((now - created_at).total_seconds() * 1000, 0)
            job.run_duration_ms = max(total_ms - queue_ms, 0.0)
            job.lease_owner = None
            job.lease_expires_at = None
        else:
            job.status = "queued"
            job.lease_owner = None
            job.lease_expires_at = None
        await session.commit()


async def requeue_stale_jobs() -> int:
    now = datetime.now(UTC)
    async with async_session() as session:
        stmt = select(FoxhoundJob).where(
            (FoxhoundJob.status == "running") & (FoxhoundJob.lease_expires_at < now)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        for job in rows:
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.completed_at = now
                job.error_message = job.error_message or "Lease expired and max attempts exceeded"
                job.lease_owner = None
                job.lease_expires_at = None
            else:
                job.status = "queued"
                job.lease_owner = None
                job.lease_expires_at = None
                job.error_message = "Lease expired; requeued"
            job.updated_at = now
        await session.commit()
    return len(rows)


async def _replace_resources(run_id: str, resources: list[dict]) -> None:
    now = datetime.now(UTC)
    async with async_session() as session:
        await session.execute(ResourceCandidate.__table__.delete().where(ResourceCandidate.run_id == run_id))
        for item in resources:
            session.add(ResourceCandidate(
                id=f"res_{uuid.uuid4().hex[:10]}",
                run_id=run_id,
                url=item["url"],
                normalized_url=item["normalized_url"],
                source_class=item["source_class"],
                page_type=item["page_type"],
                discovery_reason=item.get("discovery_reason", ""),
                discovered_by=item["discovered_by"],
                routing_tags_json=json.dumps(item.get("routing_tags", [])),
                confidence=item["confidence"],
                priority=item["priority"],
                status="discovered",
                provenance_json=json.dumps(item.get("provenance", {})),
                raw_metadata_json=json.dumps(item.get("raw_metadata", {}), default=str),
                created_at=now,
                updated_at=now,
            ))
        await session.commit()


async def _mark_selected_resources(run_id: str, normalized_urls: set[str]) -> None:
    async with async_session() as session:
        stmt = select(ResourceCandidate).where(ResourceCandidate.run_id == run_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            row.status = "selected" if row.normalized_url in normalized_urls else "deduped_out"
        await session.commit()


async def _mark_extracted_resources(run_id: str, extracted: list[dict]) -> None:
    urls = {_normalize_url(item.get("url", "")) for item in extracted if item.get("url")}
    async with async_session() as session:
        stmt = select(ResourceCandidate).where(ResourceCandidate.run_id == run_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            if row.normalized_url in urls:
                row.status = "extracted"
        await session.commit()


async def _get_resource_counts(run_id: str) -> dict:
    async with async_session() as session:
        stmt = (
            select(ResourceCandidate.status, func.count(ResourceCandidate.id))
            .where(ResourceCandidate.run_id == run_id)
            .group_by(ResourceCandidate.status)
        )
        result = await session.execute(stmt)
        counts = {row[0]: row[1] for row in result.all()}
    return {"total": sum(counts.values()), **counts}


async def _wrap_sync(value):
    return value


async def _heartbeat_job(job_id: str, worker_id: str, interval_seconds: int = 30) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        renewed = await renew_job_lease(job_id, worker_id)
        if not renewed:
            return


def _job_to_dict(row: FoxhoundJob) -> dict:
    return {
        "job_id": row.id,
        "run_id": row.run_id,
        "job_type": row.job_type,
        "origin": row.origin,
        "priority": row.priority,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "queued_duration_ms": row.queued_duration_ms,
        "run_duration_ms": row.run_duration_ms,
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "canceled_at": row.canceled_at.isoformat() if row.canceled_at else None,
    }


# ---------------------------------------------------------------------------
# Signal Persistence — save raw docs to disk so they survive pipeline crashes
# ---------------------------------------------------------------------------

import pathlib as _pathlib

_SIGNALS_DIR = _pathlib.Path(__file__).resolve().parents[2] / "data" / "signals"


def _persist_raw_signals(run_id: str, topic: str, raw_docs: list[dict]) -> _pathlib.Path:
    _SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SIGNALS_DIR / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "topic": topic,
        "signal_count": len(raw_docs),
        "saved_at": datetime.now(UTC).isoformat(),
        "signals": raw_docs,
    }
    path.write_text(json.dumps(payload, default=str))
    logger.info("Persisted %d signals to %s", len(raw_docs), path)
    return path


def load_persisted_signals(run_id: str) -> list[dict] | None:
    path = _SIGNALS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        signals = data.get("signals", [])
        logger.info("Loaded %d persisted signals from %s", len(signals), path)
        return signals
    except Exception as e:
        logger.warning("Failed to load persisted signals: %s", e)
        return None
