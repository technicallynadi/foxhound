import logging

from app.services.ingest.query_normalizer import normalize_query

logger = logging.getLogger(__name__)


def route_query(query: str) -> dict:
    """Return a minimal, query-first routing plan.

    All queries are treated the same. We do not inject verticals, communities,
    or seed URLs here.
    """
    normalized = normalize_query(query)
    plan = {
        "raw_query": query,
        "normalized_query": normalized,
        "resolved_vertical": None,
        "match_type": "query_first",
        "confidence": 1.0,
        "matched_terms": [],
        "main": [],
        "primary": [],
        "secondary": [],
        "fallback": [],
        "strategy": "broad_search",
    }
    logger.info("Query routed: '%s' -> query_first", query)
    return plan
