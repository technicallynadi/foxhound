import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.config import settings
from app.core.vertical_config import get_seed_urls, get_tool_terms, resolve_vertical
from app.services.evidence.taxonomy import classify_text_evidence_classes

logger = logging.getLogger(__name__)

SOURCE_FAMILY_REGISTRY = {
    "community": {
        "worker": "forum",
        "page_type": "reddit",
        "max_candidates": 6,
        "domains": (
            "reddit.com",
            "news.ycombinator.com",
            "lobste.rs",
            "indiehackers.com",
            "lemmy.ml",
            "lemmy.world",
            "x.com",
            "twitter.com",
        ),
        "evidence_class": "operator_practice",
    },
    "forums": {
        "worker": "forum",
        "page_type": "forum",
        "max_candidates": 5,
        "domains": (
            "biggerpockets.com",
            # Discourse-powered dev tool forums
            "community.fly.io",
            "forum.obsidian.md",
            "community.render.com",
            "forum.cursor.com",
            "community.cloudflare.com",
            "community.grafana.com",
            "forum.gitlab.com",
            "discuss.hashicorp.com",
            "discuss.kubernetes.io",
            "meta.discourse.org",
        ),
        "evidence_class": "operator_practice",
    },
    "developer_qa": {
        "worker": "forum",
        "page_type": "stackoverflow",
        "max_candidates": 5,
        "domains": ("stackoverflow.com", "stackexchange.com"),
        "evidence_class": "operator_practice",
    },
    "reviews": {
        "worker": "review",
        "page_type": "review",
        "max_candidates": 5,
        "domains": (
            "g2.com",
            "capterra.com",
            "trustradius.com",
            "alternativeto.net",
            "producthunt.com",
            "saasworthy.com",
            "stackshare.io",
        ),
        "evidence_class": "market_pull",
    },
    "code": {
        "worker": "github",
        "page_type": "github",
        "max_candidates": 4,
        "domains": ("github.com", "gitlab.com"),
        "evidence_class": "reliability",
    },
    "developer_blogs": {
        "worker": "workflow",
        "page_type": "blog",
        "max_candidates": 4,
        "domains": (
            "dev.to",
            "hashnode.com",
            "medium.com",
            # Developer newsletters
            "substack.com",
            # Company engineering blogs
            "netflixtechblog.com",
            "eng.uber.com",
            "engineering.atspotify.com",
        ),
        "evidence_class": "workflow",
    },
    "investor_signals": {
        "worker": "workflow",
        "page_type": "blog",
        "max_candidates": 3,
        "domains": (
            "ycombinator.com",
            "wellfound.com",
            "review.firstround.com",
            "a16z.com",
        ),
        "evidence_class": "market_pull",
    },
    "feature_boards": {
        "worker": "review",
        "page_type": "review",
        "max_candidates": 3,
        "domains": ("canny.io", "nolt.io", "uservoice.com"),
        "evidence_class": "market_pull",
    },
    "workflow": {
        "worker": "workflow",
        "page_type": "workflow",
        "max_candidates": 3,
        "domains": (),
        "evidence_class": "workflow",
    },
}


QUICK_SCAN_WORKERS = {"forum", "github"}


async def ingest_topic(
    topic: str,
    sources: list[str] | None = None,
    review_urls: list[str] | None = None,
    discussion_urls: list[str] | None = None,
    discovery_config: dict | None = None,
    search_mode: str = "full",
) -> list[dict]:
    """Ingest documents for a topic using TinyFish search-first architecture.

    search_mode:
      "quick" — skip Google search if cache has URLs, budget 4, forum+github only
      "full"  — full discovery: Google search + seed navigation + all workers

    Default flow (TinyFish key set):
      Phase 1: Discover URLs (parallel) — Google search + seed navigation + GitHub + cached DB
      Phase 2: Batch extract from discovered URLs (parallel)
      Phase 3: User-provided URLs

    Fallback flow (no TinyFish key or explicit --sources):
      Use Reddit/GitHub API adapters
    """
    raw_docs: list[dict] = []
    has_tinyfish = bool(settings.tinyfish_api_key)
    is_quick = search_mode == "quick"
    (discovery_config or {}).get("budget_limit", 4 if is_quick else 10)
    use_api_fallback = not has_tinyfish or bool(sources)

    # --- API Fallback: explicit sources or no TinyFish key ---
    if use_api_fallback:
        fallback_sources = sources or ["reddit", "github"]
        if "reddit" in fallback_sources:
            from app.services.ingest.reddit_adapter import fetch_reddit_posts

            posts = await fetch_reddit_posts(topic)
            for post in posts:
                raw_docs.append(_to_raw_document(post, "reddit", topic))

        if "github" in fallback_sources:
            from app.services.ingest.github_adapter import (
                fetch_github_discussions,
                fetch_github_issues,
            )

            issues = await fetch_github_issues(topic)
            for issue in issues:
                raw_docs.append(_to_raw_document(issue, "github", topic))
            discussions = await fetch_github_discussions(topic)
            for disc in discussions:
                raw_docs.append(_to_raw_document(disc, "github", topic, source_type="github_discussion"))

    # --- Platform API + TinyFish Enrichment Flow ---
    # Platform APIs find signals (fast, free, with engagement metrics)
    # TinyFish reads the top URLs in depth (detailed quotes, workarounds)
    if has_tinyfish and not sources:
        import time as _time

        phase_start = _time.monotonic()

        vertical, _, _, _ = resolve_vertical(topic)

        from app.services.ingest.adapters.unified_adapter import fetch_all_signals

        # Quick scan: APIs only, no TinyFish enrichment
        # Full research: APIs + TinyFish enrichment on top 5 URLs
        tinyfish_top = 0 if is_quick else 5

        print(f"  Fetching signals via platform APIs{' + TinyFish enrichment' if tinyfish_top else ''}...", flush=True)
        api_signals = await fetch_all_signals(
            topic=topic,
            limit_per_source=10 if is_quick else 20,
            enrich_with_tinyfish=tinyfish_top > 0,
            tinyfish_top_n=tinyfish_top,
        )
        # ─── Convert API + TinyFish signals to raw documents ───
        for sig in api_signals:
            text = sig.get("text", "") or sig.get("pain_excerpt", "")
            text_lower = text.lower()

            # Detect signal type from content keywords
            has_workaround = any(
                w in text_lower
                for w in [
                    "workaround",
                    "hack",
                    "instead",
                    "we use",
                    "i just",
                    "ended up",
                    "switched to",
                    "wrote a script",
                    "built a",
                    "manual",
                    "spreadsheet",
                    "self-hosted",
                    "open source alternative",
                ]
            )
            has_request = any(
                w in text_lower
                for w in [
                    "wish",
                    "would be nice",
                    "feature request",
                    "should have",
                    "looking for",
                    "need a tool",
                    "anyone know",
                ]
            )
            has_failure = any(
                w in text_lower
                for w in [
                    "broken",
                    "doesn't work",
                    "failed",
                    "crash",
                    "unreliable",
                    "too expensive",
                    "bill shock",
                    "pricing",
                    "cost",
                ]
            )

            # Use title as breakpoint if text is mostly comments
            title = sig.get("title", "")
            breakpoint_text = title if len(title) > 30 else text[:200]

            doc = {
                "id": sig.get("id", f"sig_{uuid.uuid4().hex[:8]}"),
                "source": sig.get("source", sig.get("source_platform", "api")),
                "source_type": sig.get("source_type", "api"),
                "source_platform": sig.get("source_platform", ""),
                "url": sig.get("url", sig.get("source_url", "")),
                "source_url": sig.get("url", sig.get("source_url", "")),
                "text": text,
                "pain_excerpt": text[:500],
                "title": title,
                "signal_type": "workaround"
                if has_workaround
                else "request"
                if has_request
                else "incumbent_failure"
                if has_failure
                else "pain",
                "tools_mentioned": sig.get("tools_mentioned", []) or sig.get("tags", []),
                "breakpoint": breakpoint_text,
                "has_pain_signal": True,
                "has_workaround": has_workaround,
                "has_request_signal": has_request,
                "has_incumbent_failure": has_failure,
                "workaround_excerpt": text[:300] if has_workaround else "",
                "incumbent_failure_excerpt": text[:300] if has_failure else "",
                "persona": sig.get("author", "user"),
                "workflow": topic,
                # Engagement metrics from platform APIs
                "score": sig.get("score", 0),
                "num_comments": sig.get("num_comments", 0),
                "view_count": sig.get("view_count", 0),
                "_tinyfish_enriched": sig.get("_tinyfish_enriched", False),
            }
            raw_docs.append(doc)

        # Save discovered URLs for future cache
        discovered_for_save = [
            {"url": sig.get("url", ""), "page_type": sig.get("source_type", ""), "title": sig.get("title", "")}
            for sig in api_signals
            if sig.get("url")
        ]
        await _save_discovered_sources(discovered_for_save, raw_docs, topic, vertical)

        phase_elapsed = round(_time.monotonic() - phase_start, 1)
        print(f"  Ingest complete: {len(raw_docs)} docs in {phase_elapsed}s", flush=True)

        # Phase 3: User-provided URLs (parallel) — skipped in quick scan
        if review_urls and not is_quick:
            from app.services.ingest.tinyfish_adapter import fetch_reviews

            review_tasks = [fetch_reviews(url, topic) for url in review_urls]
            review_results = await asyncio.gather(*review_tasks, return_exceptions=True)
            for i, result in enumerate(review_results):
                if isinstance(result, Exception):
                    logger.warning("Review extraction failed for %s: %s", review_urls[i], result)
                elif isinstance(result, list):
                    for item in result:
                        raw_docs.append(_to_raw_document(item, "reviews", topic))

        if discussion_urls and not is_quick:
            from app.services.ingest.tinyfish_adapter import fetch_forum_signals

            disc_tasks = [fetch_forum_signals(url, topic) for url in discussion_urls]
            disc_results = await asyncio.gather(*disc_tasks, return_exceptions=True)
            for i, result in enumerate(disc_results):
                if isinstance(result, Exception):
                    logger.warning("Forum extraction failed for %s: %s", discussion_urls[i], result)
                elif isinstance(result, list):
                    for item in result:
                        raw_docs.append(_to_raw_document(item, "forum", topic))

    return raw_docs


# =============================================================================
# Phase 1 helpers
# =============================================================================


async def _discover_via_search(topic: str) -> list[dict]:
    """Single Google search for high-quality pages. Uses best query from analyzer."""
    from app.services.ingest.query_analyzer import analyze_query
    from app.services.ingest.tinyfish_adapter import search_for_sources

    profile = analyze_query(topic)
    evidence_queries = profile.get("evidence_queries", [])
    if evidence_queries:
        first_query = evidence_queries[0]
        return await search_for_sources(
            first_query["query"],
            max_results=8,
            evidence_class=first_query.get("evidence_class"),
        )

    queries = profile.get("search_queries", [])
    query = queries[0] if queries else f"{topic} workflow operator practice reliability"
    return await search_for_sources(query, max_results=8)


async def _navigate_seed_urls(topic: str, vertical: str) -> list[dict]:
    """Browse YAML seed URLs with TinyFish to discover linked pages."""
    from app.services.ingest.tinyfish_adapter import discover_categories

    yaml_seeds = get_seed_urls(topic)
    if not yaml_seeds:
        return []

    seed_urls: list[str] = []
    for page_type, urls in yaml_seeds.items():
        if isinstance(urls, list):
            seed_urls.extend(urls)
        elif isinstance(urls, str):
            seed_urls.append(urls)

    if not seed_urls:
        return []

    # Browse 1 seed URL (each takes 30-60s, so limit to 1)
    try:
        results = [await discover_categories(seed_urls[0], vertical, topic=topic)]
    except Exception as e:
        logger.warning("Seed navigation failed for %s: %s", seed_urls[0], e)
        results = []

    discovered: list[dict] = []
    for result in results:
        if isinstance(result, list):
            discovered.extend(result)
    return discovered


def _generate_github_urls(topic: str) -> list[dict]:
    """Build quality-gated GitHub search URLs for TinyFish to navigate."""
    from app.services.ingest.query_analyzer import analyze_query

    profile = analyze_query(topic)
    tools = profile.get("tools_mentioned", [])

    # Also get tool terms from YAML
    yaml_tools = get_tool_terms(topic)
    all_tools = list(set(tools + yaml_tools[:3]))

    urls: list[dict] = []
    topic_encoded = topic.replace(" ", "+")

    # General topic search on GitHub
    urls.append(
        {
            "url": f"https://github.com/search?q={topic_encoded}&type=repositories&sort=stars",
            "page_type": "github",
            "title": f"GitHub repos: {topic}",
            "source": "github_search",
            "evidence_class": "market_pull",
        }
    )
    urls.append(
        {
            "url": f"https://github.com/search?q={topic_encoded}&type=issues&sort=comments",
            "page_type": "github",
            "title": f"GitHub issues: {topic}",
            "source": "github_search",
            "evidence_class": "reliability",
        }
    )

    # Tool-specific searches
    for tool in all_tools[:2]:
        tool_encoded = tool.replace(" ", "+")
        urls.append(
            {
                "url": f"https://github.com/search?q={tool_encoded}+bug+OR+feature+request&type=issues&sort=comments",
                "page_type": "github",
                "title": f"GitHub issues: {tool}",
                "source": "github_search",
                "evidence_class": "request",
            }
        )
        # Migration signals — people switching tools
        urls.append(
            {
                "url": f"https://github.com/search?q={tool_encoded}+migrate+OR+switch+OR+alternative&type=issues&sort=comments",
                "page_type": "github",
                "title": f"GitHub migration: {tool}",
                "source": "github_search",
                "evidence_class": "migration",
            }
        )

    # Breaking changes — signals tool friction
    urls.append(
        {
            "url": f"https://github.com/search?q={topic_encoded}+BREAKING+CHANGE&type=commits&sort=committer-date",
            "page_type": "github",
            "title": f"GitHub breaking changes: {topic}",
            "source": "github_search",
            "evidence_class": "reliability",
        }
    )

    # Discussions
    urls.append(
        {
            "url": f"https://github.com/search?q={topic_encoded}&type=discussions&sort=top",
            "page_type": "github",
            "title": f"GitHub discussions: {topic}",
            "source": "github_search",
            "evidence_class": "operator_practice",
        }
    )

    return urls


def build_source_family_candidates(
    topic: str,
    routing_plan: dict,
    profile: dict,
    vertical: str | None,
) -> dict[str, list[dict]]:
    """Build source-family candidates without committing to broad search loops first."""
    routing_confidence = float(routing_plan.get("confidence", 0.0) or 0.0)
    if vertical and routing_confidence >= 0.6:
        communities = routing_plan.get("primary", [])[:3] + routing_plan.get("fallback", [])[:2]
    else:
        communities = routing_plan.get("fallback", [])[:3]
    families: dict[str, list[dict]] = defaultdict(list)
    encoded_query = topic.replace(" ", "%20")

    for community in communities:
        slug = community.strip().replace(" ", "")
        if not slug or len(slug) > 24 or slug.lower() == topic.replace(" ", "").lower():
            continue
        families["community"].append(
            {
                "url": f"https://www.reddit.com/r/{slug}/search/?q={encoded_query}&restrict_sr=1&sort=top",
                "title": f"Reddit community search: {community}",
                "page_type": "reddit",
                "reason": f"Community-targeted search for {community}",
                "source": "community_registry",
                "source_family": "community",
                "site_key": f"reddit:{slug.lower()}",
                "evidence_class": SOURCE_FAMILY_REGISTRY["community"]["evidence_class"],
            }
        )

    if vertical == "property_management" and routing_confidence >= 0.7:
        families["forums"].append(
            {
                "url": f"https://www.biggerpockets.com/search?utf8=%E2%9C%93&term={topic.replace(' ', '+')}",
                "title": "BiggerPockets search",
                "page_type": "forum",
                "reason": "Property-management forum search",
                "source": "forum_registry",
                "source_family": "forums",
                "site_key": "biggerpockets",
                "evidence_class": SOURCE_FAMILY_REGISTRY["forums"]["evidence_class"],
            }
        )

    yaml_seeds = get_seed_urls(topic)
    for urls in yaml_seeds.values():
        seed_list = urls if isinstance(urls, list) else [urls]
        for url in seed_list[:2]:
            domain = urlparse(url).netloc.lower().replace("www.", "")
            family = _family_from_domain(domain) or "reviews"
            families[family].append(
                {
                    "url": url,
                    "title": f"Seed source: {domain}",
                    "page_type": SOURCE_FAMILY_REGISTRY.get(family, {}).get("page_type", "workflow"),
                    "reason": "Vertical seed source",
                    "source": "seed_registry",
                    "source_family": family,
                    "site_key": domain,
                    "evidence_class": SOURCE_FAMILY_REGISTRY.get(family, {}).get("evidence_class"),
                }
            )

    for item in _generate_github_urls(topic)[:4]:
        item["source_family"] = "code"
        item["site_key"] = "github"
        families["code"].append(item)

    workflow_terms = profile.get("verbs", [])[:2] + profile.get("tools_mentioned", [])[:2]
    if workflow_terms:
        families["workflow"].append(
            {
                "url": f"https://www.google.com/search?q={topic.replace(' ', '+')}+workflow",
                "title": f"Workflow search: {topic}",
                "page_type": "workflow",
                "reason": "Workflow-oriented practitioner search",
                "source": "workflow_registry",
                "source_family": "workflow",
                "site_key": "workflow-search",
                "evidence_class": SOURCE_FAMILY_REGISTRY["workflow"]["evidence_class"],
            }
        )

    return {family: _dedupe_family_candidates(items, family) for family, items in families.items()}


# =============================================================================
# Worker Dispatcher
# =============================================================================

# Map TinyFish-assigned page_types to worker types
PAGE_TYPE_TO_WORKER = {
    "forum": "forum",
    "reddit": "forum",
    "stackoverflow": "forum",
    "discourse": "forum",
    "lobsters": "forum",
    "indiehackers": "forum",
    "twitter": "forum",
    "review": "review",
    "directory": "review",
    "product": "review",
    "producthunt": "review",
    "feature_board": "review",
    "comparison": "comparison",
    "alternatives": "comparison",
    "github": "github",
    "workflow": "workflow",
    "docs": "workflow",
    "blog": "workflow",
    "newsletter": "workflow",
    "engineering_blog": "workflow",
}

WORKER_CONFIG = {
    "forum": {"extraction_type": "forum_signals", "max_items": 20},
    "review": {"extraction_type": "reviews", "max_items": 15},
    "comparison": {"extraction_type": "comparison", "max_items": 10},
    "github": {"extraction_type": "github", "max_items": 20},
    "workflow": {"extraction_type": "workflow_descriptions", "max_items": 10},
}


def _classify_urls(urls: list[dict]) -> dict[str, list[dict]]:
    """Group URLs by source type using TinyFish-assigned page_type."""
    groups: dict[str, list[dict]] = {}
    for page in urls:
        page_type = page.get("page_type", "")
        worker = page.get("recommended_extractor") or PAGE_TYPE_TO_WORKER.get(page_type)
        if worker == "skip":
            continue

        if not worker:
            url = page.get("url", "").lower()
            if "github.com" in url:
                worker = "github"
            elif any(s in url for s in ["/forum", "/thread", "/discussion", "/comments/"]):
                worker = "forum"
            elif any(s in url for s in ["/review", "/compare", "/vs", "/alternative"]):
                worker = "review"
            else:
                worker = "workflow"

        groups.setdefault(worker, []).append(page)

    return groups


async def _dispatch_workers(
    urls: list[dict],
    topic: str,
    budget: int,
    vertical: str | None,
    event_callback=None,
    allowed_workers: set[str] | None = None,
) -> list[dict]:
    """Dispatch URLs to specialized parallel workers by source type."""
    prepared_urls = prepare_urls_for_dispatch(urls, budget=budget)
    groups = _classify_urls(prepared_urls)

    # Filter to allowed worker types (e.g., quick scan only uses forum + github)
    if allowed_workers:
        groups = {k: v for k, v in groups.items() if k in allowed_workers}

    budget_per_worker = max(2, budget // max(len(groups), 1))

    workers = []
    for source_type, group_urls in groups.items():
        # Check cache — skip search if we have enough proven URLs for this type
        cached = await _get_cached_sources_by_type(vertical, source_type)
        if len(cached) >= WORKER_CONFIG.get(source_type, {}).get("max_items", 10) // 2:
            print(f"  Worker [{source_type}] using {len(cached)} cached URLs (skipping search)", flush=True)
            worker_urls = prepare_urls_for_dispatch(cached[:budget_per_worker], budget=budget_per_worker)
        else:
            worker_urls = prepare_urls_for_dispatch(group_urls[:budget_per_worker], budget=budget_per_worker)

        workers.append(_run_worker(source_type, worker_urls, topic, event_callback=event_callback))
        print(f"  Worker [{source_type}] dispatched with {len(worker_urls)} URLs", flush=True)

    results = await asyncio.gather(*workers, return_exceptions=True)

    all_docs: list[dict] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Worker failed: %s", result)
        elif isinstance(result, list):
            all_docs.extend(result)

    logger.info("All workers complete: %d total items from %d workers", len(all_docs), len(workers))
    return all_docs


def prepare_urls_for_dispatch(
    urls: list[dict],
    budget: int,
    max_per_domain: int = 2,
) -> list[dict]:
    """Early dedupe and per-domain caps before worker extraction starts."""
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = defaultdict(int)
    prepared: list[dict] = []

    for page in urls:
        url = page.get("url", "")
        if not url:
            continue
        if _should_skip_extraction_url(url):
            continue
        normalized = _normalize_dispatch_url(url)
        if normalized in seen_urls:
            continue
        domain = urlparse(url).netloc.lower().replace("www.", "")
        if domain_counts[domain] >= max_per_domain:
            continue
        seen_urls.add(normalized)
        domain_counts[domain] += 1
        prepared.append(page)
        if len(prepared) >= budget:
            break

    return prepared


def _should_skip_extraction_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        [
            "google.com/search?" in lowered,
            "reddit.com/" in lowered and "/search/" in lowered,
            "github.com/search?" in lowered,
        ]
    )


from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE as _TINYFISH_SEMAPHORE


async def _run_worker(source_type: str, urls: list[dict], topic: str, event_callback=None) -> list[dict]:
    """Single worker: extracts from assigned URLs using the right prompt.

    URLs within a worker are extracted concurrently (not sequentially) to
    maximize throughput.  A shared semaphore caps total TinyFish concurrency.
    """
    from app.services.ingest.tinyfish_adapter import (
        COMPARISON_GOAL,
        FORUM_DEEP_HARVEST_GOAL,
        GITHUB_INTELLIGENCE_GOAL,
        REVIEW_HARVEST_GOAL,
        WORKFLOW_DESCRIPTION_GOAL,
        _run_extraction,
    )

    WORKER_GOALS = {
        "forum": FORUM_DEEP_HARVEST_GOAL,
        "review": REVIEW_HARVEST_GOAL,
        "comparison": COMPARISON_GOAL,
        "github": GITHUB_INTELLIGENCE_GOAL,
        "workflow": WORKFLOW_DESCRIPTION_GOAL,
    }

    config = WORKER_CONFIG.get(source_type, {"extraction_type": source_type, "max_items": 10})
    goal_template = WORKER_GOALS.get(source_type, FORUM_DEEP_HARVEST_GOAL)

    async def _extract_one(page: dict) -> list[dict]:
        url = page.get("url", "")
        if not url:
            return []
        try:
            goal = goal_template.format(url=url, topic=topic)
        except KeyError:
            goal = goal_template.format(url=url)
        goal = f"Research query: {topic}\nOnly extract content that is relevant to this query.\n\n{goal}"
        async with _TINYFISH_SEMAPHORE:
            return await _run_extraction(
                url=url,
                goal=goal,
                extraction_type=config["extraction_type"],
                topic=topic,
                event_callback=event_callback,
            )

    # Launch all URL extractions concurrently
    tasks = [_extract_one(page) for page in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: list[dict] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Worker [%s] extraction failed: %s", source_type, result)
        elif isinstance(result, list):
            all_items.extend(result)
        if len(all_items) >= config["max_items"]:
            break

    all_items = all_items[: config["max_items"]]
    print(f"  Worker [{source_type}] extracted {len(all_items)} items from {len(urls)} URLs (parallel)", flush=True)
    return all_items


async def _get_cached_sources_by_type(
    vertical: str | None,
    source_type: str,
    limit: int = 10,
) -> list[dict]:
    """Get cached URLs for a specific source type and vertical."""
    try:
        from sqlalchemy import select

        from app.db.models.discovered_source import DiscoveredSource
        from app.db.session import async_session

        if not vertical:
            return []

        async with async_session() as session:
            stmt = (
                select(DiscoveredSource)
                .where(DiscoveredSource.vertical == vertical)
                .where(DiscoveredSource.last_signal_count > 0)
                .order_by(DiscoveredSource.last_signal_count.desc())
                .limit(limit)
            )

            # Map source_type to page_types
            type_map = {
                "forum": ("forum", "reddit", "stackoverflow"),
                "review": ("review", "directory", "product"),
                "comparison": ("comparison", "alternatives"),
                "github": ("github",),
                "workflow": ("workflow",),
            }
            page_types = type_map.get(source_type, (source_type,))
            stmt = stmt.where(DiscoveredSource.page_type.in_(page_types))

            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [{"url": r.url, "page_type": r.page_type, "title": r.title or "", "source": "cached"} for r in rows]
    except Exception:
        return []


async def _get_cached_sources(topic: str, limit: int = 15) -> list[dict]:
    """Return known-good URLs from past runs, matched by vertical or keywords."""
    try:
        from sqlalchemy import select

        from app.db.models.discovered_source import DiscoveredSource
        from app.db.session import async_session

        vertical, _, _, _ = resolve_vertical(topic)
        set(topic.lower().split())

        async with async_session() as session:
            # Layer 1: Vertical match with proven signal
            stmt = (
                select(DiscoveredSource)
                .where(DiscoveredSource.last_signal_count > 0)
                .order_by(DiscoveredSource.last_signal_count.desc(), DiscoveredSource.times_used.desc())
                .limit(limit)
            )
            if vertical:
                stmt = stmt.where(DiscoveredSource.vertical == vertical)

            result = await session.execute(stmt)
            rows = result.scalars().all()

            cached = []
            for row in rows:
                cached.append(
                    {
                        "url": row.url,
                        "page_type": row.page_type,
                        "title": row.title or "",
                        "source": "cached",
                        "evidence_class": getattr(row, "evidence_class", None),
                    }
                )

            if cached:
                logger.info("Found %d cached sources for '%s' (vertical=%s)", len(cached), topic, vertical)
            return cached

    except Exception as e:
        logger.debug("Cached source lookup failed: %s", e)
        return []


def _keyword_overlap_score(topic_keywords: set[str], row_keywords: str | None, query: str) -> float:
    if not topic_keywords:
        return 0.0
    score = 0.0
    if row_keywords:
        stored = {token.strip() for token in row_keywords.split(",") if token.strip()}
        overlap = len(topic_keywords & stored)
        score += min(overlap / max(len(topic_keywords), 1), 1.0)
    if query and any(token in query.lower() for token in topic_keywords):
        score += 0.15
    return score


def _compute_source_quality(
    signal_count: int,
    times_used: int,
    success_count: int,
    failure_count: int,
) -> float:
    success_rate = success_count / max(success_count + failure_count, 1)
    avg_signal = signal_count / max(times_used, 1)
    return round((avg_signal * 0.6) + (success_rate * 2.0) + min(times_used / 10.0, 1.0), 3)


async def get_learned_sources(
    topic: str,
    vertical: str | None,
    limit: int = 12,
    page_types: tuple[str, ...] | None = None,
) -> list[dict]:
    """Return learned high-yield sources ordered by historical quality and topic fit."""
    try:
        from sqlalchemy import select

        from app.db.models.discovered_source import DiscoveredSource
        from app.db.session import async_session

        if not vertical:
            return []

        topic_keywords = {token for token in topic.lower().split() if token}

        async with async_session() as session:
            stmt = select(DiscoveredSource)
            if vertical:
                stmt = stmt.where(DiscoveredSource.vertical == vertical)
            if page_types:
                stmt = stmt.where(DiscoveredSource.page_type.in_(page_types))
            stmt = stmt.where(
                (DiscoveredSource.success_count > 0)
                | (DiscoveredSource.last_signal_count > 0)
                | (DiscoveredSource.total_signal_count > 0)
            )
            stmt = stmt.order_by(
                DiscoveredSource.quality_score.desc(),
                DiscoveredSource.last_signal_count.desc(),
                DiscoveredSource.times_used.desc(),
            ).limit(limit * 3)

            result = await session.execute(stmt)
            rows = result.scalars().all()

        learned = []
        for row in rows:
            topic_fit = _keyword_overlap_score(topic_keywords, row.keywords, row.query)
            historical_quality = row.quality_score or _compute_source_quality(
                signal_count=row.total_signal_count or row.last_signal_count or 0,
                times_used=row.times_used or 1,
                success_count=row.success_count or 0,
                failure_count=row.failure_count or 0,
            )
            learned_score = round((historical_quality * 0.75) + (topic_fit * 1.5), 3)
            learned.append(
                {
                    "url": row.url,
                    "page_type": row.page_type,
                    "title": row.title or "",
                    "source": "learned",
                    "source_class": row.source_class,
                    "reason": row.reason or "",
                    "search_query": row.search_query or "",
                    "evidence_class": getattr(row, "evidence_class", None),
                    "last_signal_count": row.last_signal_count,
                    "quality_score": historical_quality,
                    "learned_score": learned_score,
                    "success_count": row.success_count or 0,
                    "failure_count": row.failure_count or 0,
                }
            )

        learned.sort(
            key=lambda item: (
                item.get("learned_score", 0.0),
                item.get("quality_score", 0.0),
                item.get("last_signal_count", 0),
            ),
            reverse=True,
        )
        return learned[:limit]
    except Exception as e:
        logger.debug("Learned source lookup failed: %s", e)
        return []


async def _save_discovered_sources(
    all_urls: list[dict],
    extracted: list[dict],
    topic: str,
    vertical: str | None,
) -> None:
    """Save discovered URLs to DB for future reuse."""
    try:
        from sqlalchemy import select

        from app.db.models.discovered_source import DiscoveredSource
        from app.db.session import async_session

        url_signal_counts: dict[str, int] = {}
        for doc in extracted:
            url = doc.get("url", "")
            if url:
                url_signal_counts[url] = url_signal_counts.get(url, 0) + 1

        keywords = ",".join(sorted(set(topic.lower().split())))
        now = datetime.now(UTC)
        inserted = 0
        updated = 0

        async with async_session() as session:
            for page in all_urls:
                url = page.get("url", "")
                if not url:
                    continue

                domain = ""
                try:
                    domain = urlparse(url).netloc.replace("www.", "")
                except Exception:
                    pass

                signal_count = url_signal_counts.get(url, 0)
                source_class = page.get("source_class")
                evidence_class = page.get("evidence_class")
                success = 1 if signal_count > 0 else 0
                failure = 0 if signal_count > 0 else 1

                # Check if URL already exists
                existing = await session.execute(select(DiscoveredSource).where(DiscoveredSource.url == url))
                row = existing.scalar_one_or_none()

                if row:
                    updated += 1
                    row.times_used += 1
                    row.last_signal_count = signal_count
                    row.total_signal_count = (row.total_signal_count or 0) + signal_count
                    row.success_count = (row.success_count or 0) + success
                    row.failure_count = (row.failure_count or 0) + failure
                    row.last_used_at = now
                    row.query = topic
                    row.keywords = keywords
                    row.reason = page.get("reason", row.reason or "")
                    row.search_query = page.get("search_query", row.search_query or "")
                    row.source_class = source_class or row.source_class
                    if hasattr(row, "evidence_class"):
                        row.evidence_class = evidence_class or getattr(row, "evidence_class", None)
                    row.quality_score = _compute_source_quality(
                        signal_count=row.total_signal_count or row.last_signal_count or 0,
                        times_used=row.times_used,
                        success_count=row.success_count or 0,
                        failure_count=row.failure_count or 0,
                    )
                else:
                    session.add(
                        DiscoveredSource(
                            id=str(uuid.uuid4()),
                            url=url,
                            domain=domain,
                            page_type=page.get("page_type", "unknown"),
                            source_class=source_class,
                            title=page.get("title", ""),
                            vertical=vertical,
                            query=topic,
                            keywords=keywords,
                            reason=page.get("reason", ""),
                            search_query=page.get("search_query", ""),
                            evidence_class=evidence_class
                            if "evidence_class" in DiscoveredSource.__table__.columns
                            else None,
                            times_used=1,
                            last_signal_count=signal_count,
                            total_signal_count=signal_count,
                            success_count=success,
                            failure_count=failure,
                            quality_score=_compute_source_quality(
                                signal_count=signal_count,
                                times_used=1,
                                success_count=success,
                                failure_count=failure,
                            ),
                            last_used_at=now,
                            discovered_at=now,
                        )
                    )
                    inserted += 1

            await session.commit()
            logger.info(
                "Saved discovered sources to DB (inserted=%d, updated=%d, processed=%d)",
                inserted,
                updated,
                len(all_urls),
            )

    except Exception as e:
        logger.warning("Failed to save discovered sources: %s", e)


# =============================================================================
# Utilities
# =============================================================================

# Priority by page_type (from TinyFish classification, not hardcoded domains)
PAGE_TYPE_PRIORITY = {
    "forum": 1,
    "reddit": 1,
    "stackoverflow": 2,
    "github": 2,
    "comparison": 3,
    "alternatives": 3,
    "workflow": 3,
    "review": 4,
    "directory": 4,
    "product": 4,
}


def _prioritize_urls(urls: list[dict]) -> list[dict]:
    """Deduplicate and prioritize: cached first, then by page_type (forums > reviews)."""
    seen: set[str] = set()
    unique: list[dict] = []
    for page in urls:
        url = page.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(page)

    def _sort_key(page):
        is_cached = 0 if page.get("source") == "cached" else 1
        signal = -(page.get("last_signal_count", 0) or 0)
        priority = PAGE_TYPE_PRIORITY.get(page.get("page_type", ""), 3)
        return (is_cached, priority, signal)

    unique.sort(key=_sort_key)
    return unique


def _normalize_dispatch_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/') or '/'}"


def _family_from_domain(domain: str) -> str | None:
    normalized = domain.lower().replace("www.", "")
    for family, config in SOURCE_FAMILY_REGISTRY.items():
        if normalized in config.get("domains", ()):
            return family
    return None


def _dedupe_family_candidates(items: list[dict], family: str) -> list[dict]:
    seen_site_keys: set[str] = set()
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    max_candidates = SOURCE_FAMILY_REGISTRY.get(family, {}).get("max_candidates", 4)

    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        normalized = _normalize_dispatch_url(url)
        site_key = item.get("site_key") or urlparse(url).netloc.lower().replace("www.", "")
        if normalized in seen_urls or site_key in seen_site_keys:
            continue
        seen_urls.add(normalized)
        seen_site_keys.add(site_key)
        deduped.append(item)
        if len(deduped) >= max_candidates:
            break
    return deduped


def _to_raw_document(
    item: dict,
    source: str,
    topic: str,
    source_type: str | None = None,
) -> dict:
    source_id = item.get("source_id", str(uuid.uuid4()))
    doc_id = f"{source}_{source_id}"

    created_at = item.get("created_at") or item.get("created_utc")
    if isinstance(created_at, int | float):
        created_at = datetime.fromtimestamp(created_at, tz=UTC).isoformat()

    metadata = {
        k: v
        for k, v in item.items()
        if k not in ("source_id", "url", "title", "text", "author", "created_at", "created_utc", "community")
    }

    explicit_evidence_class = item.get("evidence_class")
    evidence_classes = list(
        dict.fromkeys(
            ([explicit_evidence_class] if explicit_evidence_class else [])
            + item.get("evidence_classes", [])
            + classify_text_evidence_classes(item.get("text", ""))
        )
    )

    return {
        "id": doc_id,
        "source": source,
        "source_type": source_type or SOURCE_TYPE_MAP.get(source, source),
        "source_id": source_id,
        "url": item.get("url", ""),
        "topic_hint": topic,
        "title": item.get("title", ""),
        "community": item.get("community", item.get("repo", "")),
        "author": item.get("author", ""),
        "created_at": created_at or "",
        "text": item.get("text", ""),
        "evidence_class": explicit_evidence_class,
        "evidence_classes": evidence_classes,
        "metadata": metadata,
    }


SOURCE_TYPE_MAP = {
    "reddit": "reddit_post",
    "github": "github_issue",
    "tinyfish": "tinyfish_extraction",
    "reviews": "product_review",
    "forum": "forum_signal",
    "cached": "cached_source",
}
