"""Temporary file serving for TinyFish resume injection.

TinyFish runs in a browser on greenhouse.io / lever.co / etc.
Those pages block cross-origin fetches to supabase.co (CORS).
This endpoint serves the resume from our own domain with permissive
CORS headers so TinyFish's browser can fetch it.

Tokens are 256-bit random, single-use, 10-min TTL, in-memory.
This endpoint is intentionally unauthenticated — TinyFish's browser
cannot carry our auth headers. See SECURITY.md exceptions section.

CONSTRAINT: In-memory store is per-worker. Must run single-worker
until migrated to Redis.
"""

from __future__ import annotations

import logging
import re
import secrets
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.storage.supabase_storage import download_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/files", tags=["files"])

# In-memory token store: {token: (bucket, path, created_at)}
_file_tokens: dict[str, tuple[str, str, float]] = {}
TOKEN_TTL = 600  # 10 minutes
MAX_TOKENS = 100  # Cap to prevent unbounded growth

# token_urlsafe(32) produces exactly 43 chars of [A-Za-z0-9_-]
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

# Max file size we'll serve (10MB — real resumes are 50-200KB)
MAX_FILE_SIZE = 10 * 1024 * 1024


def _cleanup_expired() -> None:
    """Remove expired tokens."""
    now = time.time()
    expired = [t for t, (_, _, created) in _file_tokens.items() if now - created > TOKEN_TTL]
    for t in expired:
        _file_tokens.pop(t, None)


def create_file_token(bucket: str, path: str) -> str:
    """Create a short-lived token for accessing a private file."""
    _cleanup_expired()

    # Evict oldest if at capacity
    if len(_file_tokens) >= MAX_TOKENS:
        oldest = min(_file_tokens, key=lambda t: _file_tokens[t][2])
        _file_tokens.pop(oldest)

    token = secrets.token_urlsafe(32)
    _file_tokens[token] = (bucket, path, time.time())
    return token


@router.get("/serve/{token}")
async def serve_file(token: str):
    """Serve a private file via a short-lived token.

    Used by TinyFish to fetch resumes during form fill.
    Returns the file with permissive CORS headers.

    Intentionally unauthenticated — access controlled by token.
    See SECURITY.md exceptions section.
    """
    # Fast-reject malformed tokens
    if not _TOKEN_RE.match(token):
        raise HTTPException(404, "Not found")

    _cleanup_expired()

    entry = _file_tokens.pop(token, None)  # Single-use: pop on access
    if not entry:
        logger.warning("Invalid or expired file token: %s...%s", token[:8], token[-4:])
        raise HTTPException(404, "File not found or token expired")

    bucket, path, created_at = entry
    if time.time() - created_at > TOKEN_TTL:
        logger.warning("Expired file token used: %s...%s", token[:8], token[-4:])
        raise HTTPException(410, "Token expired")

    # Only serve PDFs
    if not path.endswith(".pdf"):
        logger.warning("Non-PDF file requested via token: %s", path.split("/")[0])
        raise HTTPException(403, "Only PDF files can be served")

    try:
        data = await download_file(bucket, path)
    except Exception:
        logger.warning("File download failed: bucket=%s user=%s", bucket, path.split("/")[0])
        raise HTTPException(404, "File not found")

    if len(data) > MAX_FILE_SIZE:
        logger.warning("File too large: %d bytes", len(data))
        raise HTTPException(413, "File too large")

    logger.info(
        "File served: bucket=%s user=%s token=%s...%s size=%d",
        bucket, path.split("/")[0], token[:8], token[-4:], len(data),
    )

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
