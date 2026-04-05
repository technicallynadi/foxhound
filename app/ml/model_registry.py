import logging

from app.ml import lightgbm_ranker, setfit_relevance

logger = logging.getLogger(__name__)


def load_all_models() -> dict:
    """Load all available ML models."""
    results = {}

    results["relevance"] = setfit_relevance.load_model()
    results["ranker"] = lightgbm_ranker.load_model()

    loaded = sum(1 for v in results.values() if v)
    logger.info("ML models loaded: %d/%d", loaded, len(results))
    return results


def get_status() -> dict:
    """Get the status of all ML models."""
    return {
        "relevance": {"available": setfit_relevance.is_available()},
        "ranker": {"available": lightgbm_ranker.is_available()},
    }
