"""Extraction result caching.

Prevents re-extracting from the same URL when a pipeline run fails and is retried.
Cache files live under data/cache/extractions/ as JSON keyed by SHA256(url|prompt_name).
"""

import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache/extractions")


def _cache_key(url: str, prompt_name: str) -> str:
    return sha256(f"{url}|{prompt_name}".encode()).hexdigest()


def _cache_path(url: str, prompt_name: str) -> Path:
    return CACHE_DIR / f"{_cache_key(url, prompt_name)}.json"


def cache_extraction(
    url: str, prompt_name: str, items: list[dict], topic: str,
) -> None:
    """Save extraction results to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url, prompt_name)
    payload = {
        "url": url,
        "prompt_name": prompt_name,
        "topic": topic,
        "items": items,
        "cached_at": datetime.now(UTC).isoformat(),
        "item_count": len(items),
    }
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    logger.debug("Cached %d items for %s [%s] -> %s", len(items), url, prompt_name, path.name)


def get_cached_extraction(
    url: str, prompt_name: str, ttl_hours: int = 24,
) -> list[dict] | None:
    """Return cached items if present and fresh, else None."""
    path = _cache_path(url, prompt_name)
    if not path.exists():
        logger.debug("Cache miss (not found) for %s [%s]", url, prompt_name)
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache read error for %s [%s]: %s", url, prompt_name, exc)
        return None

    cached_at_str = data.get("cached_at")
    if not cached_at_str:
        logger.debug("Cache miss (no timestamp) for %s [%s]", url, prompt_name)
        return None

    cached_at = datetime.fromisoformat(cached_at_str)
    age_hours = (datetime.now(UTC) - cached_at).total_seconds() / 3600
    if age_hours > ttl_hours:
        logger.debug("Cache miss (stale, %.1fh old) for %s [%s]", age_hours, url, prompt_name)
        return None

    items = data.get("items", [])
    logger.info("Cache hit (%d items, %.1fh old) for %s [%s]", len(items), age_hours, url, prompt_name)
    return items


def clear_cache(topic: str | None = None) -> int:
    """Delete cache files, optionally filtered by topic. Returns count deleted."""
    if not CACHE_DIR.exists():
        return 0

    deleted = 0
    for path in CACHE_DIR.glob("*.json"):
        if topic is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("topic") != topic:
                    continue
            except (json.JSONDecodeError, OSError):
                continue
        path.unlink(missing_ok=True)
        deleted += 1

    logger.info("Cleared %d cache files%s", deleted, f" for topic={topic}" if topic else "")
    return deleted


def cache_stats() -> dict:
    """Return summary statistics about the extraction cache."""
    if not CACHE_DIR.exists():
        return {"total_files": 0, "total_items": 0, "oldest_cache": None, "newest_cache": None}

    total_files = 0
    total_items = 0
    oldest: datetime | None = None
    newest: datetime | None = None

    for path in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        total_files += 1
        total_items += data.get("item_count", 0)

        cached_at_str = data.get("cached_at")
        if cached_at_str:
            ts = datetime.fromisoformat(cached_at_str)
            if oldest is None or ts < oldest:
                oldest = ts
            if newest is None or ts > newest:
                newest = ts

    return {
        "total_files": total_files,
        "total_items": total_items,
        "oldest_cache": oldest.isoformat() if oldest else None,
        "newest_cache": newest.isoformat() if newest else None,
    }
