from app.jobs.base import TinyFishJob

_JOB_REGISTRY: dict[str, TinyFishJob] | None = None


def get_job_registry() -> dict[str, TinyFishJob]:
    global _JOB_REGISTRY
    if _JOB_REGISTRY is None:
        from app.services.ingest.tinyfish_adapter import (
            discover_categories,
            fetch_comparison_page,
            fetch_forum_signals,
            fetch_incumbent_gaps,
            fetch_reviews,
            fetch_workflow_descriptions,
            search_for_sources,
            stream_extraction,
        )

        _JOB_REGISTRY = {
            "category_discovery": TinyFishJob(
                job_type="category_discovery",
                description="Discover high-value pages in a vertical",
                extraction_fn=discover_categories,
            ),
            "review_harvest": TinyFishJob(
                job_type="review_harvest",
                description="Extract structured review intelligence from review pages",
                extraction_fn=fetch_reviews,
            ),
            "incumbent_gap": TinyFishJob(
                job_type="incumbent_gap",
                description="Extract failures and unmet needs from existing products",
                extraction_fn=fetch_incumbent_gaps,
            ),
            "forum_deep_harvest": TinyFishJob(
                job_type="forum_deep_harvest",
                description="Extract workflow pain signals from forum/discussion pages",
                extraction_fn=fetch_forum_signals,
            ),
            "comparison_extraction": TinyFishJob(
                job_type="comparison_extraction",
                description="Extract competitor intelligence from comparison pages",
                extraction_fn=fetch_comparison_page,
            ),
            "workflow_description_harvest": TinyFishJob(
                job_type="workflow_description_harvest",
                description="Extract workflow descriptions from operator blogs and docs",
                extraction_fn=fetch_workflow_descriptions,
                default_profile="lite",
            ),
            "source_expansion": TinyFishJob(
                job_type="source_expansion",
                description="Search for new review/comparison sources via web search",
                extraction_fn=search_for_sources,
                supports_batch=False,
            ),
            "preview_source_debug": TinyFishJob(
                job_type="preview_source_debug",
                description="Stream extraction for debugging and prompt iteration",
                extraction_fn=stream_extraction,
                supports_batch=False,
            ),
        }
        from app.jobs.corpus_ingestion import get_corpus_ingestion_job

        corpus_job = get_corpus_ingestion_job()
        _JOB_REGISTRY[corpus_job.job_type] = corpus_job

    return _JOB_REGISTRY
