"""ReconEngine: orchestrate sources, cache, and SSE streaming.

Runs TinyFish sources in parallel via asyncio.as_completed(), streams each
result as an SSE event as it finishes, then synthesizes with Claude Haiku.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recon_dossier import ReconDossier
from app.services.recon.sources import load_posting_data
from app.services.recon.synthesizer import synthesize_dossier

logger = logging.getLogger(__name__)

from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE

# 60-second timeout per TinyFish source
_SOURCE_TIMEOUT_S = 60

# Cache TTL: 24 hours
_CACHE_TTL = timedelta(hours=24)


def _normalize_company(name: str) -> str:
    """Normalize company name for cache key: lowercase, strip whitespace."""
    return name.strip().lower().replace(" ", "_")


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class ReconEngine:
    """Orchestrate company intelligence gathering.

    Usage:
        engine = ReconEngine(db=session, job_id="...", user_id="...")
        async for sse_line in engine.run():
            yield sse_line   # stream to client
    """

    def __init__(self, db: AsyncSession, job_id: str, user_id: str) -> None:
        self.db = db
        self.job_id = job_id
        self.user_id = user_id

    async def run(self) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE events as each source completes.

        Events: status, posting, careers, company, synthesis, error, done
        """
        async with TINYFISH_SEMAPHORE:
            t0 = time.perf_counter()

            # Load posting data first (free, instant) to get company info
            posting_data = await load_posting_data(self.db, self.job_id)
            if not posting_data:
                yield _sse_event("error", {"source": "posting", "reason": "job not found"})
                yield _sse_event("done", {"dossier_id": None, "cached": False, "duration_ms": 0})
                return

            company_name = posting_data.get("company", "Unknown")
            posting_data.get("company_url")
            normalized = _normalize_company(company_name)

            # Check cache
            cached = await self._check_cache(normalized)
            if cached:
                logger.info("Recon cache hit for %s", company_name)
                yield _sse_event("status", {"phase": "cached", "sources": ["careers", "company", "posting"]})
                # Stream cached data
                if cached.posting_data:
                    yield _sse_event("posting", json.loads(cached.posting_data))
                if cached.careers_data:
                    yield _sse_event("careers", json.loads(cached.careers_data))
                if cached.company_data:
                    yield _sse_event("company", json.loads(cached.company_data))
                if cached.synthesis:
                    yield _sse_event("synthesis", json.loads(cached.synthesis))
                duration_ms = int((time.perf_counter() - t0) * 1000)
                yield _sse_event("done", {"dossier_id": cached.id, "cached": True, "duration_ms": duration_ms})
                return

            # Stream posting data immediately (already loaded, free)
            yield _sse_event("status", {"phase": "starting", "sources": ["posting"]})
            yield _sse_event("posting", {
                "title": posting_data.get("title"),
                "company": company_name,
                "location": posting_data.get("location"),
                "remote_type": posting_data.get("remote_type"),
                "seniority": posting_data.get("seniority"),
                "salary_min": posting_data.get("salary_min"),
                "salary_max": posting_data.get("salary_max"),
            })

            # Quick brief — LLM only, no TinyFish (instant)
            # For deep research, the cascade calls TinyFish directly
            careers_data: dict[str, Any] | None = None
            company_data: dict[str, Any] | None = None
            sources_completed: list[str] = ["posting"]
            sources_failed: list[str] = []
            tinyfish_credits = 0

            # Synthesize from job posting data (instant, free)
            yield _sse_event("status", {"phase": "synthesizing"})
            synthesis = await synthesize_dossier(
                company_name, careers_data, company_data, posting_data
            )
            yield _sse_event("synthesis", synthesis)

            # Cache the dossier
            duration_ms = int((time.perf_counter() - t0) * 1000)
            dossier_id = f"rec_{uuid4().hex[:12]}"

            try:
                dossier = ReconDossier(
                    id=dossier_id,
                    company_normalized=normalized,
                    company_display=company_name,
                    careers_data=json.dumps(careers_data, default=str) if careers_data else None,
                    company_data=json.dumps(company_data, default=str) if company_data else None,
                    posting_data=json.dumps(posting_data, default=str) if posting_data else None,
                    synthesis=json.dumps(synthesis, default=str),
                    sources_completed=json.dumps(sources_completed),
                    sources_failed=json.dumps(sources_failed),
                    tinyfish_credits=tinyfish_credits,
                    duration_ms=duration_ms,
                )
                self.db.add(dossier)
                await self.db.commit()
            except Exception as e:
                logger.warning("Failed to cache dossier for %s: %s", company_name, str(e)[:200])
                # If it's a unique constraint violation, the cache was already written
                await self.db.rollback()

            yield _sse_event("done", {
                "dossier_id": dossier_id,
                "cached": False,
                "duration_ms": duration_ms,
            })

    async def run_sync(self) -> dict[str, Any]:
        """Collect all results synchronously (for agent tool use).

        Returns the full dossier as a single dict.
        """
        result: dict[str, Any] = {
            "posting": None,
            "careers": None,
            "company": None,
            "synthesis": None,
            "errors": [],
            "cached": False,
            "duration_ms": 0,
        }

        async for event_str in self.run():
            # Parse SSE event
            lines = event_str.strip().split("\n")
            event_type = ""
            data: dict[str, Any] = {}
            for line in lines:
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        data = {}

            if event_type == "posting":
                result["posting"] = data
            elif event_type == "careers":
                result["careers"] = data
            elif event_type == "company":
                result["company"] = data
            elif event_type == "synthesis":
                result["synthesis"] = data
            elif event_type == "error":
                result["errors"].append(data)
            elif event_type == "done":
                result["dossier_id"] = data.get("dossier_id")
                result["cached"] = data.get("cached", False)
                result["duration_ms"] = data.get("duration_ms", 0)

        return result

    async def _check_cache(self, company_normalized: str) -> ReconDossier | None:
        """Check for a cached dossier within the TTL window."""
        cutoff = datetime.now(UTC) - _CACHE_TTL
        result = await self.db.execute(
            select(ReconDossier).where(
                ReconDossier.company_normalized == company_normalized,
                ReconDossier.created_at > cutoff,
            )
        )
        return result.scalar_one_or_none()
