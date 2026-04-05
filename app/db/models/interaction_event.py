from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class InteractionEvent(Base):
    """Tracks user interactions with opportunities for ML feedback.

    Events are sent in batches from the frontend via POST /v1/feedback/events.
    Aggregated into relevance labels for LambdaRank training.
    """

    __tablename__ = "interaction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    query_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    ranker_variant: Mapped[str] = mapped_column(String, default="heuristic")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
