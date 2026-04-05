"""Unified adapter — runs all platform API adapters in parallel.

Replaces DuckDuckGo-via-TinyFish for structured signal discovery.
Each platform adapter returns signals WITH engagement metrics (upvotes,
comments, stars) — something TinyFish search could never provide.

TinyFish is still used for browser-only extraction (blogs, comparison
sites, Canny boards) but is no longer the search engine.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def fetch_all_signals(
    topic: str,
    limit_per_source: int = 20,
    enrich_with_tinyfish: bool = True,
    tinyfish_top_n: int = 5,
) -> list[dict]:
    """Run all platform adapters in parallel, optionally enrich top URLs with TinyFish.

    Flow:
      1. Platform APIs find signals (fast, free, with engagement metrics)
      2. Rank by engagement → pick top N URLs worth reading deeply
      3. TinyFish reads those URLs → extracts detailed quotes, workarounds
      4. Merge everything → return to pipeline

    Returns a list of raw signal dicts compatible with the pipeline's
    _to_raw_document() conversion.
    """
    from app.services.ingest.adapters.discourse_adapter import fetch_discourse_signals
    from app.services.ingest.adapters.hn_adapter import fetch_hn_signals
    from app.services.ingest.adapters.stackoverflow_adapter import fetch_so_signals
    from app.services.ingest.github_adapter import fetch_github_discussions, fetch_github_issues
    from app.services.ingest.reddit_adapter import fetch_reddit_posts

    # Step 1: Run all platform adapters in parallel
    tasks = {
        "reddit": fetch_reddit_posts(topic, limit=limit_per_source),
        "github_issues": fetch_github_issues(topic, limit=limit_per_source),
        "github_discussions": fetch_github_discussions(topic, limit=limit_per_source // 2),
        "hackernews": fetch_hn_signals(topic, limit=limit_per_source),
        "stackoverflow": fetch_so_signals(topic, limit=limit_per_source // 2),
        "discourse": fetch_discourse_signals(topic, limit=limit_per_source // 2),
    }

    print(f"  Running {len(tasks)} platform adapters in parallel...", flush=True)
    results = await asyncio.gather(
        *[_run_adapter(name, coro) for name, coro in tasks.items()],
    )

    all_signals = []
    for name, signals in results:
        print(f"  [{name}]: {len(signals)} signals", flush=True)
        for sig in signals:
            normalized = _normalize_signal(sig, name)
            if normalized:
                all_signals.append(normalized)

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for sig in all_signals:
        url = sig.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(sig)
        elif not url:
            deduped.append(sig)

    # Filter by relevance — drop signals that don't mention any topic keywords
    topic_words = set(topic.lower().split())
    # Remove stop words
    stop = {"the", "a", "an", "for", "with", "and", "or", "in", "on", "of", "to", "is", "are",
            "too", "how", "do", "does", "what", "why", "i", "we", "my", "our", "not"}
    topic_words -= stop
    if len(topic_words) < 2:
        topic_words = set(topic.lower().split()[:3])

    unique = []
    filtered_count = 0
    for sig in deduped:
        text = (sig.get("text", "") + " " + sig.get("title", "")).lower()
        # Signal must contain at least 1 topic keyword
        if any(w in text for w in topic_words):
            unique.append(sig)
        else:
            filtered_count += 1

    if filtered_count:
        print(f"  Relevance filter: dropped {filtered_count} off-topic signals", flush=True)

    print(f"  API signals: {len(unique)} relevant from {len(tasks)} platforms", flush=True)

    # Step 2: Enrich top URLs with TinyFish for deeper extraction
    if enrich_with_tinyfish and unique:
        enriched = await _tinyfish_enrich_top_signals(unique, topic, top_n=tinyfish_top_n)
        unique.extend(enriched)
        print(f"  TinyFish enrichment: +{len(enriched)} deep signals", flush=True)

    print(f"  Total: {len(unique)} signals (API + TinyFish)", flush=True)
    return unique


async def _tinyfish_enrich_top_signals(
    signals: list[dict],
    topic: str,
    top_n: int = 5,
) -> list[dict]:
    """Send TinyFish to the highest-engagement URLs for deep content extraction.

    Platform APIs give us titles + engagement metrics but often not full content.
    TinyFish reads the actual page and extracts detailed quotes and breakpoints.
    """
    from app.core.config import settings
    if not settings.tinyfish_api_key:
        return []

    from app.services.ingest.tinyfish_adapter import GOAL_TEMPLATES_BY_PAGE_TYPE, _run_extraction

    # Rank signals by engagement and pick the top N
    scored = sorted(signals, key=lambda s: s.get("score", 0) + s.get("num_comments", 0), reverse=True)
    top_urls = []
    seen = set()
    for sig in scored:
        url = sig.get("url", "")
        if url and url not in seen and not _is_api_only_url(url):
            seen.add(url)
            top_urls.append(sig)
        if len(top_urls) >= top_n:
            break

    if not top_urls:
        return []

    print(f"  TinyFish: enriching {len(top_urls)} top URLs by engagement...", flush=True)

    # Run TinyFish extraction on each URL using single-page prompts
    enriched = []
    for sig in top_urls:
        url = sig["url"]
        page_type = _guess_page_type(url)
        template_entry = GOAL_TEMPLATES_BY_PAGE_TYPE.get(page_type)
        if not template_entry:
            continue

        _, goal_template = template_entry
        try:
            goal = goal_template.format(url=url, topic=topic)
        except KeyError:
            try:
                goal = goal_template.format(url=url)
            except KeyError:
                continue

        try:
            items = await _run_extraction(
                url=url, goal=goal,
                extraction_type="signals",
                topic=topic,
                max_retries=1,
            )
            for item in items:
                if isinstance(item, dict):
                    # TinyFish returns structured signals
                    if item.get("signals"):
                        for s in item["signals"]:
                            s["source_url"] = url
                            s["source_platform"] = sig.get("source_platform", page_type)
                            s["_tinyfish_enriched"] = True
                            s["_parent_score"] = sig.get("score", 0)
                            enriched.append(_normalize_signal(s, "tinyfish"))
                    else:
                        item["_tinyfish_enriched"] = True
                        item["_parent_score"] = sig.get("score", 0)
                        normalized = _normalize_signal(item, "tinyfish")
                        if normalized:
                            enriched.append(normalized)
        except Exception as e:
            logger.debug("TinyFish enrichment failed for %s: %s", url[:60], e)

    return enriched


def _is_api_only_url(url: str) -> bool:
    """URLs that are API endpoints, not browsable pages."""
    return any(p in url for p in ["/api/", "api.github.com", "api.stackexchange.com", "hn.algolia.com"])


def _guess_page_type(url: str) -> str:
    """Guess the page type from the URL for prompt selection."""
    lowered = url.lower()
    if "reddit.com" in lowered:
        return "reddit"
    if "github.com" in lowered:
        return "github"
    if "news.ycombinator.com" in lowered:
        return "forum"
    if "stackoverflow.com" in lowered:
        return "stackoverflow"
    if any(d in lowered for d in ["community.", "forum.", "discuss.", "answers."]):
        return "discourse"
    return "blog"


async def _run_adapter(name: str, coro) -> tuple[str, list[dict]]:
    """Run a single adapter with error handling."""
    try:
        results = await coro
        return (name, results or [])
    except Exception as e:
        logger.warning("Adapter [%s] failed: %s", name, e)
        return (name, [])


def _normalize_signal(sig: dict, source_name: str) -> dict | None:
    """Normalize a platform-specific signal to the pipeline's raw document format."""
    text = sig.get("text", "")
    if not text or len(text.strip()) < 20:
        return None

    return {
        "id": sig.get("source_id", ""),
        "source": source_name,
        "source_type": sig.get("source_type", source_name),
        "source_platform": sig.get("source_platform", source_name),
        "url": sig.get("url", ""),
        "source_url": sig.get("url", ""),
        "title": sig.get("title", ""),
        "text": text,
        "pain_excerpt": text[:500],
        "author": sig.get("author", ""),
        "created_at": sig.get("created_at"),
        "community": sig.get("community", ""),
        # Engagement metrics — this is what TinyFish couldn't provide
        "score": sig.get("score", 0),
        "num_comments": sig.get("num_comments", 0),
        "view_count": sig.get("view_count", 0),
        "tags": sig.get("tags", []),
        # Signal type hints from the platform
        "is_answered": sig.get("is_answered"),
        "parent_story_title": sig.get("parent_story_title", ""),
    }
