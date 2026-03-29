from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, index=True)

    # --- Parsed resume fields ---
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Structured extracted data (JSON blobs) ---
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    experience_json: Mapped[str] = mapped_column(Text, default="[]")
    education_json: Mapped[str] = mapped_column(Text, default="[]")
    certifications_json: Mapped[str] = mapped_column(Text, default="[]")

    # --- Job preferences (user-editable) ---
    target_titles_json: Mapped[str] = mapped_column(Text, default="[]")
    target_locations_json: Mapped[str] = mapped_column(Text, default="[]")
    remote_preference: Mapped[str] = mapped_column(String, default="any")
    salary_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String, default="USD")
    industries_json: Mapped[str] = mapped_column(Text, default="[]")
    company_size_preference: Mapped[str | None] = mapped_column(String, nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String, nullable=True)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_clearance: Mapped[bool] = mapped_column(Integer, default=0)
    visa_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Resume file reference ---
    resume_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Settings ---
    autopilot_enabled: Mapped[bool] = mapped_column(Integer, default=0)
    autopilot_threshold: Mapped[int] = mapped_column(Integer, default=75)
    daily_apply_limit: Mapped[int] = mapped_column(Integer, default=10)
    blacklisted_companies_json: Mapped[str] = mapped_column(Text, default="[]")
    whitelisted_companies_json: Mapped[str] = mapped_column(Text, default="[]")

    # --- Subscription ---
    tier: Mapped[str] = mapped_column(String, default="free")
    monthly_apply_limit: Mapped[int] = mapped_column(Integer, default=0)
    applications_this_month: Mapped[int] = mapped_column(Integer, default=0)
    billing_cycle_start: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    # --- Answer bank (cross-application memory) ---
    answer_bank_json: Mapped[str] = mapped_column(Text, default="{}")

    # --- Notification preferences ---
    notify_channels_json: Mapped[str] = mapped_column(Text, default='["email"]')
    notify_on_apply: Mapped[bool] = mapped_column(Integer, default=1)
    notify_daily_digest: Mapped[bool] = mapped_column(Integer, default=1)

    archetype: Mapped[str | None] = mapped_column(String, nullable=True)

    profile_complete: Mapped[bool] = mapped_column(Integer, default=0)
    onboarding_step: Mapped[str] = mapped_column(String, default="upload_resume")

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
