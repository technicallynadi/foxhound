import logging

logger = logging.getLogger(__name__)


def load_verticals() -> dict:
    """Curated vertical config is disabled for live routing."""
    return {}


def resolve_vertical(query: str) -> tuple[str | None, str, float, list[str]]:
    """Curated vertical resolution is disabled for live routing."""
    return None, "fallback", 0.1, []


def get_vertical(query: str) -> dict | None:
    return None


def get_vertical_key(query: str) -> str | None:
    return None


def get_communities(query: str) -> dict | None:
    return None


def get_domain_terms(query: str) -> list[str]:
    return []


def get_workflow_terms(query: str) -> list[str]:
    return []


def get_tool_terms(query: str) -> list[str]:
    return []


def get_hard_negatives(query: str) -> list[str]:
    return []


def get_role_terms(query: str) -> list[str]:
    return []


def get_seed_urls(query: str) -> dict:
    return {}
