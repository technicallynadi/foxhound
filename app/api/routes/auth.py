"""Auth API routes — Supabase Auth integration.

All authentication is handled client-side via Supabase JS SDK.
These endpoints provide server-side session validation and user info.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.services.auth_service import get_current_user, get_user_tier

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


class UserResponse(BaseModel):
    user_id: str
    email: str | None
    role: str
    tier: str
    app_metadata: dict
    user_metadata: dict


class AuthConfigResponse(BaseModel):
    supabase_url: str
    supabase_anon_key: str


@router.get("/v1/auth/config")
async def get_auth_config() -> AuthConfigResponse:
    """Return Supabase config for the frontend to initialize the client.

    This is public — the anon key is designed to be exposed client-side.
    """
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Auth not configured")

    return AuthConfigResponse(
        supabase_url=settings.supabase_url,
        supabase_anon_key=settings.supabase_anon_key,
    )


@router.get("/v1/auth/me")
async def get_me(user: dict = Depends(get_current_user)) -> UserResponse:
    """Get the currently authenticated user's info."""
    tier = await get_user_tier(user)
    return UserResponse(
        user_id=user["user_id"],
        email=user.get("email"),
        role=user["role"],
        tier=tier,
        app_metadata=user.get("app_metadata", {}),
        user_metadata=user.get("user_metadata", {}),
    )


@router.post("/v1/auth/signout")
async def sign_out(user: dict = Depends(get_current_user)) -> dict:
    """Sign out the current user by revoking their Supabase session.

    The frontend should also call supabase.auth.signOut() client-side.
    This endpoint handles server-side cleanup if needed.
    """
    # Supabase handles session invalidation server-side automatically
    # when the token expires. For explicit logout, the frontend calls
    # supabase.auth.signOut() which revokes the refresh token.
    logger.info("User %s signed out", user["user_id"])
    return {"status": "ok"}
