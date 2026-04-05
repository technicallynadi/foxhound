"""Supabase Auth service for Foxhound.

Handles user authentication via Supabase Auth (JWT-based).
Provides middleware for protecting API routes and extracting user context.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _get_jwks_url() -> str:
    """Build the JWKS URL from the Supabase project URL."""
    base = settings.supabase_url.rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


async def verify_supabase_token(token: str) -> dict:
    """Verify a Supabase JWT and return the user payload.

    Uses Supabase's /auth/v1/user endpoint for token verification,
    which is simpler and more reliable than local JWT validation.

    Returns:
        User dict with id, email, role, etc.

    Raises:
        HTTPException(401) if token is invalid or expired.
    """
    if not settings.supabase_url:
        raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")

    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/user"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
        )

    if resp.status_code == 200:
        user = resp.json()
        return {
            "user_id": user.get("id"),
            "email": user.get("email"),
            "role": user.get("role", "authenticated"),
            "app_metadata": user.get("app_metadata", {}),
            "user_metadata": user.get("user_metadata", {}),
            "created_at": user.get("created_at"),
        }

    if resp.status_code == 401:
        logger.info("Supabase auth rejected token with 401")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    logger.warning("Supabase auth check failed: %s %s", resp.status_code, resp.text[:200])
    raise HTTPException(status_code=401, detail="Authentication failed")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict:
    """FastAPI dependency: extract and verify the current user from Bearer token.

    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["user_id"]}
    """
    if not credentials:
        logger.info("Auth failed: missing authorization header")
        raise HTTPException(status_code=401, detail="Missing authorization header")

    return await verify_supabase_token(credentials.credentials)


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict | None:
    """FastAPI dependency: extract user if present, None if not.

    Use for routes that work both authenticated and unauthenticated.

    Usage:
        @router.get("/public-or-private")
        async def flexible_route(user: dict | None = Depends(get_optional_user)):
            if user:
                # Authenticated path
            else:
                # Public path
    """
    if not credentials:
        return None

    try:
        return await verify_supabase_token(credentials.credentials)
    except HTTPException:
        return None


async def get_user_tier(user: dict) -> str:
    """Determine the user's subscription tier.

    For now, returns 'free' for all users. Will be extended
    when Stripe integration is added.
    """
    # Check app_metadata for tier (set via Supabase admin or webhook)
    tier = user.get("app_metadata", {}).get("tier")
    if tier in ("free", "pro", "team"):
        return tier
    return "free"


# ---------------------------------------------------------------------------
# Admin helpers (use SUPABASE_SERVICE_KEY, not user tokens)
# ---------------------------------------------------------------------------

async def admin_get_user(user_id: str) -> dict | None:
    """Fetch a user by ID using the service role key (admin only)."""
    if not settings.supabase_service_key:
        return None

    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/admin/users/{user_id}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "apikey": settings.supabase_anon_key,
            },
        )

    if resp.status_code == 200:
        return resp.json()
    return None


async def admin_update_user_metadata(user_id: str, app_metadata: dict) -> bool:
    """Update a user's app_metadata (e.g., set tier, flags) using service role key."""
    if not settings.supabase_service_key:
        return False

    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/admin/users/{user_id}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={"app_metadata": app_metadata},
        )

    return resp.status_code == 200
