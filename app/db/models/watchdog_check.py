"""WatchdogCheck model — stores the full history of posting checks.

Each row represents one TinyFish check of a job posting URL,
recording the result (active/removed/check_failed), any text diff,
and execution metadata.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class WatchdogCheck(Base):
    __tablename__ = "watchdog_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)

    # Check result
    check_status: Mapped[str] = mapped_column(String)  # active | removed | check_failed
    posting_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    status_changed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Transition
    previous_status: Mapped[str | None] = mapped_column(String, nullable=True)
    new_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # Content
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    removal_signal: Mapped[str | None] = mapped_column(String, nullable=True)

    # TinyFish execution
    tinyfish_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tinyfish_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    browser_profile: Mapped[str | None] = mapped_column(String, nullable=True)

    # Metadata
    current_url: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, default="scheduled")

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
