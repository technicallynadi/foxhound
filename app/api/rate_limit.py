"""Per-user rate limiting for API endpoints.

In-memory rate limiter using a sliding window. Suitable for single-worker
deployment. For multi-worker, migrate to Redis.

Usage:
    from app.api.rate_limit import rate_limit

    @router.post("/expensive")
    async def expensive_endpoint(
        user: dict = Depends(get_current_user),
        _: None = Depends(rate_limit("agent", 20, 60)),  # 20 req/min
    ):
        ...
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from fastapi import Depends, HTTPException, Request

from app.services.auth_service import get_current_user


# Sliding window store: key -> list of timestamps
_windows: dict[str, list[float]] = defaultdict(list)


def rate_limit(
    scope: str,
    max_requests: int,
    window_seconds: int,
) -> Callable:
    """Create a rate limit dependency for a given scope.

    Args:
        scope: Name for this rate limit bucket (e.g., "agent", "apply")
        max_requests: Max requests allowed in the window
        window_seconds: Window duration in seconds
    """

    async def _check(
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> None:
        user_id = user["user_id"]
        key = f"{scope}:{user_id}"
        now = time.monotonic()

        # Clean expired entries
        _windows[key] = [t for t in _windows[key] if now - t < window_seconds]

        if len(_windows[key]) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {max_requests} requests per {window_seconds}s. Try again shortly.",
            )

        _windows[key].append(now)

    return _check
