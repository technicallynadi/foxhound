"""Recon API routes.

POST /api/v1/recon/{job_id} — SSE streaming company intelligence dossier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recon_dossier import ReconDossier
from app.db.session import get_db
from app.services.auth_service import get_current_user
from app.services.recon.engine import ReconEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/recon", tags=["recon"])

# Rate limit: 10 recon operations per user per day
_DAILY_RECON_LIMIT = 10


@router.post("/{job_id}")
async def recon_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a company intelligence dossier via SSE.

    Launches TinyFish to scrape the company's careers and about pages
    in parallel, streams each result as it completes, then synthesizes
    with Claude Haiku.

    Rate limited to 10/day per user. Results cached for 24h.
    """
    user_id = user["user_id"]

    # Rate limit check
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    count_result = await db.execute(
        select(func.count())
        .select_from(ReconDossier)
        .where(ReconDossier.user_id == user_id, ReconDossier.created_at > day_ago)
    )
    recent_count = count_result.scalar() or 0

    if recent_count >= _DAILY_RECON_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Recon rate limit reached ({_DAILY_RECON_LIMIT}/day). Try again tomorrow.",
        )

    engine = ReconEngine(db=db, job_id=job_id, user_id=user_id)

    async def event_generator():
        async for event in engine.run():
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
