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
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from app.services.auth_service import get_current_user

# Sliding window store: key -> list of timestamps
_windows: dict[str, list[float]] = defaultdict(list)


def _prune_window(key: str, window_seconds: int, now: float) -> list[float]:
    window = [t for t in _windows[key] if now - t < window_seconds]
    _windows[key] = window
    return window


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

        window = _prune_window(key, window_seconds, now)

        if len(window) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {max_requests} requests per {window_seconds}s. Try again shortly.",
            )

        window.append(now)

    return _check


def rate_limit_user_or_device(
    scope: str,
    max_user_requests: int,
    window_seconds: int,
    *,
    max_device_requests: int | None = None,
    device_header: str = "x-foxhound-device-id",
) -> Callable:
    """Rate limit by both user and device (with IP fallback).

    This prevents one user from bypassing limits across devices and also
    prevents one noisy device/tab from monopolizing a user's quota.
    """

    device_limit = max_device_requests if max_device_requests is not None else max_user_requests

    async def _check(
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> None:
        user_id = user["user_id"]
        now = time.monotonic()

        user_key = f"{scope}:user:{user_id}"
        user_window = _prune_window(user_key, window_seconds, now)
        if len(user_window) >= max_user_requests:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {max_user_requests} requests per {window_seconds}s "
                    "for this account."
                ),
            )

        device_id = (request.headers.get(device_header) or "").strip()
        client_ip = request.client.host if request.client else "unknown"
        actor = device_id or f"ip:{client_ip}"
        device_key = f"{scope}:device:{user_id}:{actor}"
        device_window = _prune_window(device_key, window_seconds, now)
        if len(device_window) >= device_limit:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {device_limit} requests per {window_seconds}s "
                    "for this device."
                ),
            )

        user_window.append(now)
        device_window.append(now)

    return _check
