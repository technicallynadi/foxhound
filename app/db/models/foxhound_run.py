from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class FoxhoundRun(Base):
    __tablename__ = "foxhound_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    query: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String, default="pipeline_run")
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str] = mapped_column(String, default="queued")
    premium: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_config_json: Mapped[str] = mapped_column(Text, default="{}")
    notification_destination_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    notification_destinations_json: Mapped[str] = mapped_column(Text, default="{}")
    notification_status_json: Mapped[str] = mapped_column(Text, default="{}")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    workers_json: Mapped[str] = mapped_column(Text, default="[]")
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    routing_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
