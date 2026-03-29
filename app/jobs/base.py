from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class TinyFishJob:
    job_type: str
    description: str
    extraction_fn: Callable
    default_profile: str | None = None
    supports_batch: bool = True
    supports_stream: bool = True


async def run_job(
    job_type: str,
    url: str,
    topic: str | None = None,
) -> dict:
    """Run a TinyFish job by type, returning the extraction results."""
    from app.jobs.tinyfish_jobs import get_job_registry

    job_registry = get_job_registry()
    job = job_registry.get(job_type)
    if not job:
        return {"error": f"Unknown job type: {job_type}", "job_type": job_type}

    fn = job.extraction_fn

    # discover_categories has a different signature (seed_url, vertical)
    if job_type == "category_discovery":
        items = await fn(url, topic or "general", topic=topic)
    elif job_type == "source_expansion":
        items = await fn(url)
    elif job_type == "preview_source_debug":
        from app.services.ingest.tinyfish_adapter import stream_extraction
        events = await stream_extraction(url, topic or "Debug extraction")
        return {"job_type": job_type, "url": url, "events": events}
    else:
        items = await fn(url, topic)

    return {
        "job_type": job_type,
        "url": url,
        "topic": topic,
        "items_count": len(items) if isinstance(items, list) else 0,
        "items": items if isinstance(items, list) else [],
    }
