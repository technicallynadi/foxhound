"""Ghost Job Detector API.

Public endpoints — no auth required for URL checks.
Rate limited to prevent abuse (10 checks/hour per IP).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ghost", tags=["ghost"])

# Simple in-memory rate limiter: IP → list of timestamps
_rate_limit: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 10  # checks per window
_RATE_LIMIT_WINDOW = 3600  # 1 hour


def _check_rate_limit(ip: str) -> bool:
    """Returns True if under limit, False if exceeded."""
    now = time.time()
    timestamps = _rate_limit[ip]
    # Remove expired entries
    _rate_limit[ip] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit[ip]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit[ip].append(now)
    return True


class GhostCheckRequest(BaseModel):
    url: str


@router.post("/check")
async def check_url(body: GhostCheckRequest, request: Request):
    """Public endpoint: check any job URL for ghost job risk.

    No auth required. Rate limited to 10 checks/hour per IP.
    Works with any job posting URL.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again in an hour.",
        )

    from app.services.ghost_detector import score_url

    result = await score_url(body.url)
    return result


@router.post("/deep-scan")
async def deep_scan_url(
    body: GhostCheckRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Deep scan: runs TinyFish agents for deeper ghost signals.

    Requires authentication. Uses TinyFish credits. Returns richer analysis.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    from app.services.ghost_detector import _check_url_via_browser

    result = await _check_url_via_browser(body.url)
    return result


@router.get("/job/{job_id}")
async def check_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Score a job in the database with full context.

    Uses watchdog history, company hiring velocity, and response rates.
    """
    from app.services.ghost_detector import score_job

    result = await score_job(db, job_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result
