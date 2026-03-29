"""Hash-based deduplication for job listings."""

from __future__ import annotations

import hashlib


def compute_dedup_hash(company: str, title: str, location: str | None) -> str:
    """Compute a stable hash for deduplication.

    Normalizes: lowercase, strip whitespace, sort components.
    """
    parts = [
        (company or "").lower().strip(),
        (title or "").lower().strip(),
        (location or "").lower().strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
