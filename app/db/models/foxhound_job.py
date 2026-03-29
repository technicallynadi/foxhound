from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class FoxhoundJob(Base):
    __tablename__ = "foxhound_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    job_type: Mapped[str] = mapped_column(String, default="run_execution")
    origin: Mapped[str] = mapped_column(String, default="interactive", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    queued_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    recurring: Mapped[bool | None] = mapped_column(nullable=True, default=False)
    recurrence_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_scheduled_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)
