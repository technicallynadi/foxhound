from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)

    # --- Scoring breakdown ---
    match_score: Mapped[int] = mapped_column(Integer, index=True)

    title_score: Mapped[float] = mapped_column(Float, default=0)
    skills_score: Mapped[float] = mapped_column(Float, default=0)
    experience_score: Mapped[float] = mapped_column(Float, default=0)
    location_score: Mapped[float] = mapped_column(Float, default=0)
    salary_score: Mapped[float] = mapped_column(Float, default=0)
    recency_score: Mapped[float] = mapped_column(Float, default=0)

    disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    disqualify_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- User interaction ---
    user_action: Mapped[str] = mapped_column(String, default="none")
    user_feedback: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
