"""Tests for profile API routes: resume upload, CRUD, preferences."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Resume upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_resume_not_pdf(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/profile/resume/upload",
            files={"file": ("resume.txt", b"not a pdf", "text/plain")},
        )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_resume_too_large(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/profile/resume/upload",
            files={"file": ("big.pdf", b"x" * (11 * 1024 * 1024), "application/pdf")},
        )
    assert resp.status_code == 400
    assert "large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Profile GET
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_profile_not_found(user_id):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/profile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_profile_exists(db, sample_profile):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_name"] == "Test"
    assert data["email"] == "test@foxhound.com"
    assert "Python" in data["skills"]


# ---------------------------------------------------------------------------
# Profile PUT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_profile(db, sample_profile):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/profile",
            json={"first_name": "Updated", "skills": ["Rust", "Go"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_name"] == "Updated"
    assert data["skills"] == ["Rust", "Go"]


@pytest.mark.asyncio
async def test_update_profile_auto_creates(user_id):
    """Updating a nonexistent profile now auto-creates it (bootstrap)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/profile",
            json={"first_name": "Ghost"},
        )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Ghost"


# ---------------------------------------------------------------------------
# Preferences PUT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_preferences(db, sample_profile):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/profile/preferences",
            json={
                "target_titles": ["Principal Engineer"],
                "remote_preference": "remote_only",
                "salary_floor": 250000,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_titles"] == ["Principal Engineer"]
    assert data["remote_preference"] == "remote_only"
    assert data["salary_floor"] == 250000
