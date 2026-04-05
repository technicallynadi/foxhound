from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class TinyFishRun(Base):
    __tablename__ = "tinyfish_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tinyfish_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    job_type: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    goal_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    streaming_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser_profile: Mapped[str | None] = mapped_column(String, nullable=True)
    items_extracted: Mapped[int] = mapped_column(Integer, default=0)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
