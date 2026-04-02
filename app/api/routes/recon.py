"""Recon API routes.

POST /api/v1/recon/{job_id} — SSE streaming company intelligence dossier.
"""

from __future__ import annotations

import logging
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import rate_limit_user_or_device
from app.db.session import get_db
from app.services.auth_service import get_current_user
from app.services.recon.engine import ReconEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/recon", tags=["recon"])


@router.post("/{job_id}")
async def recon_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(
        rate_limit_user_or_device(
            "recon_quick_report",
            max_user_requests=30,
            max_device_requests=12,
            window_seconds=60,
        )
    ),
):
    """Stream a company intelligence dossier via SSE.

    Streams posting + synthesized company intelligence and caches results.
    """
    user_id = user["user_id"]
    logger.info("Recon quick report requested: user_id=%s job_id=%s", user_id, job_id)
    engine = ReconEngine(db=db, job_id=job_id, user_id=user_id)

    async def event_generator():
        try:
            async for event in engine.run():
                yield event
        except Exception:
            logger.exception("Recon quick report stream failed: user_id=%s job_id=%s", user_id, job_id)
            yield f"event: error\ndata: {json.dumps({'source': 'recon', 'reason': 'internal_error'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'dossier_id': None, 'cached': False, 'duration_ms': 0})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
