import uuid
from collections import defaultdict
from datetime import UTC, datetime
from time import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from app.db.models.waitlist_entry import WaitlistEntry
from app.db.session import async_session, init_db

router = APIRouter(prefix="/v1/waitlist", tags=["waitlist"])

# Simple in-memory rate limiter: 5 requests per 60s per IP
_rate_hits: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60
_RATE_MAX = 5


def _check_rate(ip: str) -> bool:
    now = time()
    _rate_hits[ip] = [t for t in _rate_hits[ip] if now - t < _RATE_WINDOW]
    if len(_rate_hits[ip]) >= _RATE_MAX:
        return False
    _rate_hits[ip].append(now)
    return True


class WaitlistRequest(BaseModel):
    email: EmailStr
    referral_source: str | None = None


@router.post("")
async def join_waitlist(body: WaitlistRequest, req: Request):
    ip = req.client.host if req.client else "unknown"
    if not _check_rate(ip):
        raise HTTPException(429, "Too many requests. Try again in a minute.")

    await init_db()
    async with async_session() as session:
        existing = await session.execute(select(WaitlistEntry).where(WaitlistEntry.email == body.email))
        if existing.scalar_one_or_none():
            return {"status": "already_registered", "message": "You're already on the list."}

        entry = WaitlistEntry(
            id=f"wl_{uuid.uuid4().hex[:10]}",
            email=body.email,
            referral_source=body.referral_source,
            created_at=datetime.now(UTC),
        )
        session.add(entry)
        await session.commit()

    return {"status": "registered", "message": "You're on the list."}


@router.get("/count")
async def waitlist_count():
    await init_db()
    async with async_session() as session:
        result = await session.execute(select(func.count(WaitlistEntry.id)))
        count = result.scalar() or 0
    return {"count": count}
