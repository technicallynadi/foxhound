"""Corpus ingestion job: uses TinyFish to discover existing solutions from
review sites, directories, comparison pages, and GitHub, then normalizes
and stores them in the solution corpus."""

import logging

from app.jobs.base import TinyFishJob

logger = logging.getLogger(__name__)

INGESTION_SOURCES = [
    {
        "label": "G2 reviews",
        "url": "https://www.g2.com/categories",
        "job_type": "review_harvest",
    },
    {
        "label": "Product Hunt",
        "url": "https://www.producthunt.com",
        "job_type": "category_discovery",
    },
    {
        "label": "AlternativeTo",
        "url": "https://alternativeto.net",
        "job_type": "comparison_extraction",
    },
]


async def run_corpus_ingestion(
    topic: str | None = None,
    sources: list[dict] | None = None,
    max_per_source: int = 20,
) -> dict:
    """Run a corpus ingestion pass. Discovers existing solutions from external
    sources and adds them to the corpus.

    Returns summary of what was ingested."""
    from app.jobs.tinyfish_jobs import get_job_registry
    from app.services.solution_corpus_service import add_solutions_batch

    job_registry = get_job_registry()
    sources = sources or INGESTION_SOURCES
    total_added = 0
    source_results = []

    for source_config in sources:
        job_type = source_config.get("job_type", "review_harvest")
        url = source_config.get("url", "")
        label = source_config.get("label", url)
        job = job_registry.get(job_type)

        if not job:
            logger.warning("Unknown job type %s for source %s", job_type, label)
            source_results.append({"source": label, "status": "skipped", "reason": f"unknown job type: {job_type}"})
            continue

        try:
            if job_type == "category_discovery":
                items = await job.extraction_fn(url, topic or "general", topic=topic)
            elif job_type == "source_expansion":
                items = await job.extraction_fn(url)
            else:
                items = await job.extraction_fn(url, topic)

            if not isinstance(items, list):
                items = []

            solutions = _normalize_extracted_items(items, label, url)[:max_per_source]
            if solutions:
                ids = await add_solutions_batch(solutions)
                total_added += len(ids)
                source_results.append({"source": label, "status": "ok", "extracted": len(items), "added": len(ids)})
            else:
                source_results.append({"source": label, "status": "ok", "extracted": len(items), "added": 0})

        except Exception as exc:
            logger.error("Corpus ingestion failed for %s: %s", label, exc)
            source_results.append({"source": label, "status": "error", "error": str(exc)})

    return {
        "topic": topic,
        "total_added": total_added,
        "sources": source_results,
    }


def _normalize_extracted_items(items: list, source_label: str, source_url: str) -> list[dict]:
    """Normalize TinyFish extraction results into corpus solution dicts."""
    solutions = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = (item.get("title") or item.get("name") or item.get("product_name") or item.get("tool") or "").strip()
        if not title or len(title) < 2:
            continue

        summary = (
            item.get("summary") or item.get("description") or item.get("snippet") or item.get("tagline") or ""
        ).strip()

        tags = []
        for tag_field in ("tags", "categories", "labels"):
            val = item.get(tag_field)
            if isinstance(val, list):
                tags.extend(str(t) for t in val if t)
            elif isinstance(val, str) and val:
                tags.append(val)

        category = item.get("category") or item.get("vertical") or None
        workflow_hints = []
        for wf_field in ("workflow_hints", "workflows", "use_cases"):
            val = item.get(wf_field)
            if isinstance(val, list):
                workflow_hints.extend(str(w) for w in val if w)

        item_url = item.get("url") or item.get("link") or item.get("source_url") or source_url

        solutions.append(
            {
                "title": title,
                "summary": summary or None,
                "tags": tags[:10],
                "category": category,
                "workflow_hints": workflow_hints[:5],
                "source": source_label,
                "source_url": item_url,
                "form_factor": item.get("form_factor"),
                "sector": item.get("sector") or category,
            }
        )

    # dedupe by title
    seen = set()
    unique = []
    for s in solutions:
        key = s["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def get_corpus_ingestion_job() -> TinyFishJob:
    return TinyFishJob(
        job_type="corpus_ingestion",
        description="Discover and ingest existing solutions into the comparison corpus",
        extraction_fn=run_corpus_ingestion,
        supports_batch=False,
        supports_stream=False,
    )
