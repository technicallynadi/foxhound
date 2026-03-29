import re


def normalize_query(raw_query: str) -> str:
    """Normalize a raw query for routing and matching."""
    q = raw_query.lower().strip()
    q = re.sub(r"[^a-z0-9 ]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q
