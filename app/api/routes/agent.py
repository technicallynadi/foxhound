"""FoxhoundAgent API routes.

POST /api/v1/agent       — SSE streaming response
POST /api/v1/agent/sync  — Synchronous response (for channel adapters)
GET  /api/v1/agent/history — Chat history
GET  /api/v1/agent/sessions — List sessions
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import rate_limit
from app.db.models.agent_session import AgentMessage, AgentSession
from app.db.session import get_db
from app.services.agent.agent import FoxhoundAgent
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

agent = FoxhoundAgent()


class AgentRequest(BaseModel):
    message: str
    session_id: str | None = None
    channel: str = "web"


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


@router.post("")
async def agent_stream(
    body: AgentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("agent", 30, 60)),  # 30 messages/min
):
    """Stream the agent's response via Server-Sent Events."""
    user_id = user["user_id"]
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async def event_generator():
        async for event in agent.respond_stream(
            db=db,
            user_id=user_id,
            message=body.message,
            session_id=body.session_id,
            channel=body.channel,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Sync (for channel adapters)
# ---------------------------------------------------------------------------


@router.post("/sync")
async def agent_sync(
    body: AgentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("agent", 30, 60)),  # 30 messages/min
):
    """Non-streaming response. Used by Slack/Discord/SMS adapters."""
    user_id = user["user_id"]
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    return await agent.respond(
        db=db,
        user_id=user_id,
        message=body.message,
        session_id=body.session_id,
        channel=body.channel,
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@router.get("/history")
async def agent_history(
    user: dict = Depends(get_current_user),
    session_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Get chat history for a user's session."""
    user_id = user["user_id"]
    if session_id:
        session = await db.get(AgentSession, session_id)
        if not session or session.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        result = await db.execute(
            select(AgentSession)
            .where(AgentSession.user_id == user_id)
            .order_by(AgentSession.last_message_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if not session:
            return {"session_id": None, "messages": []}

    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id)
        .order_by(AgentMessage.created_at)
        .limit(min(limit, 100))
    )
    messages = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_name": m.tool_name,
            "channel": m.channel,
            "created_at": m.created_at.isoformat(),
        }
        for m in result.scalars()
        if m.role in ("user", "assistant")
    ]

    return {"session_id": session.id, "messages": messages}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def agent_sessions(
    user: dict = Depends(get_current_user),
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """List a user's agent sessions."""
    user_id = user["user_id"]
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.user_id == user_id)
        .order_by(AgentSession.last_message_at.desc())
        .limit(min(limit, 50))
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "channel": s.channel,
                "created_at": s.created_at.isoformat(),
                "last_message_at": s.last_message_at.isoformat(),
            }
            for s in result.scalars()
        ]
    }
