from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    match_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Application state ---
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    trigger: Mapped[str] = mapped_column(String, default="manual")

    # --- Phase tracking ---
    phase: Mapped[str] = mapped_column(String, default="scan")
    # "scan" | "waiting_input" | "fill" | "done"
    submission_method: Mapped[str] = mapped_column(String, default="browser")
    # "api" | "browser"
    scan_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_tinyfish_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Form fill details ---
    fields_filled_json: Mapped[str] = mapped_column(Text, default="[]")
    custom_answers_json: Mapped[str] = mapped_column(Text, default="[]")
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_version_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- TinyFish execution ---
    tinyfish_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tinyfish_status: Mapped[str | None] = mapped_column(String, nullable=True)
    tinyfish_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tinyfish_streaming_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Screenshot receipt ---
    pre_submit_screenshot_path: Mapped[str | None] = mapped_column(String, nullable=True)
    screenshot_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    screenshot_captured_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True
    )

    # --- Error handling ---
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)

    # --- Follow-up tracking ---
    followup_day3_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_day7_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_day14_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Notification ---
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_sent_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True
    )

    # --- Watchdog monitoring ---
    posting_status: Mapped[str] = mapped_column(
        String, default="unknown"
    )  # active | removed | edited | reposted | unknown | check_failed
    last_watchdog_check_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True
    )
    posting_last_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    watchdog_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
    submitted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
