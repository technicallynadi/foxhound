from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class JobListing(Base):
    __tablename__ = "job_listings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # --- Core job data ---
    title: Mapped[str] = mapped_column(String, index=True)
    company: Mapped[str] = mapped_column(String, index=True)
    company_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    location: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_type: Mapped[str | None] = mapped_column(String, nullable=True)

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String, nullable=True)

    seniority: Mapped[str | None] = mapped_column(String, nullable=True)
    required_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    required_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_clearance: Mapped[bool] = mapped_column(Boolean, default=False)
    visa_sponsorship: Mapped[bool | None] = mapped_column(Integer, nullable=True)

    # --- Application metadata ---
    apply_url: Mapped[str] = mapped_column(String)
    ats_type: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    auto_apply_supported: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Source tracking ---
    source: Mapped[str] = mapped_column(String, index=True)
    source_url: Mapped[str] = mapped_column(String)

    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    # --- Processing state ---
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    dedup_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    custom_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Ghost job detection ---
    ghost_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ghost_risk: Mapped[str | None] = mapped_column(String, nullable=True)  # low | medium | high
    ghost_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ghost_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    repost_count: Mapped[int] = mapped_column(Integer, default=0)

    discovered_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
