"""Tests for Supabase Storage client: upload, download, public URL."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.storage.supabase_storage import upload_file, download_file, get_public_url


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_file_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    with patch("app.services.storage.supabase_storage.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        path = await upload_file("resumes", "user1/resume.pdf", b"PDF content", "application/pdf")

    assert path == "resumes/user1/resume.pdf"
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_upload_file_conflict_retries_with_put():
    conflict_resp = MagicMock()
    conflict_resp.status_code = 409

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.raise_for_status = MagicMock()

    with patch("app.services.storage.supabase_storage.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=conflict_resp)
        mock_client.put = AsyncMock(return_value=ok_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        path = await upload_file("bucket", "file.txt", b"data")

    assert path == "bucket/file.txt"
    mock_client.put.assert_called_once()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_file():
    mock_resp = MagicMock()
    mock_resp.content = b"file bytes here"
    mock_resp.raise_for_status = MagicMock()

    with patch("app.services.storage.supabase_storage.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        data = await download_file("resumes", "user1/resume.pdf")

    assert data == b"file bytes here"


# ---------------------------------------------------------------------------
# Public URL
# ---------------------------------------------------------------------------

def test_get_public_url():
    with patch("app.services.storage.supabase_storage.settings") as mock_settings:
        mock_settings.supabase_storage_url = "https://abc.supabase.co/storage/v1"
        url = get_public_url("screenshots", "user1/app1.png")
    assert url == "https://abc.supabase.co/storage/v1/object/public/screenshots/user1/app1.png"
