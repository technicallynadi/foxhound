"""AgentActivity: logs every autonomous agent action for the activity feed.

Each row is one event: application submitted, match discovered, ghost alert,
follow-up sent, brief ready, etc. The frontend activity feed reads this table.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class AgentActivity(Base):
    __tablename__ = "agent_activities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    # Types: application_submitted, application_skipped, matches_discovered,
    # briefing_sent, watchdog_check, followup_sent, followup_reminder,
    # ghost_alert, interview_detected, dossier_ready, questions_pending,
    # scan_completed, research_started, research_completed
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        index=True,
    )
