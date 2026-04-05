"""Agent session and message models.

Each user has their own sessions. No shared state between users.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String, default="web")

    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
    last_message_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)

    role: Mapped[str] = mapped_column(String)
    # "user" | "assistant" | "tool_use" | "tool_result"

    content: Mapped[str] = mapped_column(Text, default="")

    # Tool call metadata
    tool_use_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which channel originated this message
    channel: Mapped[str] = mapped_column(String, default="web")

    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
