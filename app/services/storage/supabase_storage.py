"""Supabase Storage client for file uploads/downloads."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def upload_file(bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload a file to Supabase Storage. Returns the storage path."""
    url = f"{settings.supabase_storage_url}/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": content_type,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, content=data, headers=headers)
        if resp.status_code in (400, 409):
            # File already exists — overwrite it
            resp = await client.put(url, content=data, headers=headers)
        resp.raise_for_status()

    logger.info("Uploaded %s/%s (%d bytes)", bucket, path, len(data))
    return f"{bucket}/{path}"


async def download_file(bucket: str, path: str) -> bytes:
    """Download a file from Supabase Storage."""
    url = f"{settings.supabase_storage_url}/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def get_public_url(bucket: str, path: str) -> str:
    """Get the public URL for a file in Supabase Storage."""
    return f"{settings.supabase_storage_url}/object/public/{bucket}/{path}"


async def get_signed_url(bucket: str, path: str, expires_in: int = 3600) -> str:
    """Get a signed (temporary) URL for a private file.

    Used for resume injection — TinyFish fetches the PDF via this URL
    inside the browser. The URL expires after `expires_in` seconds.
    """
    url = f"{settings.supabase_storage_url}/object/sign/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json={"expiresIn": expires_in})
        resp.raise_for_status()

    signed_path = resp.json().get("signedURL", "")
    # signedURL is like /object/sign/bucket/path?token=...
    # Prepend the storage base URL
    return f"{settings.supabase_storage_url}{signed_path}"
