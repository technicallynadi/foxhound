"""Object-level ownership enforcement helper."""

from __future__ import annotations

from fastapi import HTTPException


def assert_owner(resource_user_id: str | None, current_user_id: str) -> None:
    """Enforce object-level ownership. The backend uses the Supabase service_role
    key, which BYPASSES RLS, so every route that loads a row by id MUST verify the
    row belongs to the authenticated user. Raises 404 (not 403) to avoid leaking existence."""
    if resource_user_id != current_user_id:
        raise HTTPException(status_code=404, detail="Not found")
