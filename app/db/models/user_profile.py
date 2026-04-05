from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
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
    has_clearance: Mapped[bool] = mapped_column(Boolean, default=False)
    clearance_type: Mapped[str | None] = mapped_column(String, nullable=True)
    visa_status: Mapped[str | None] = mapped_column(String, nullable=True)  # citizen, green_card, h1b, opt, need_sponsorship
    salary_expectation: Mapped[str | None] = mapped_column(String, nullable=True)
    notice_period: Mapped[str | None] = mapped_column(String, nullable=True)
    work_preference: Mapped[str | None] = mapped_column(String, nullable=True)  # remote, hybrid, office
    willing_to_relocate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # --- EEO demographics (auto-fill on applications) ---
    gender: Mapped[str | None] = mapped_column(String, nullable=True)  # male, female, non_binary, decline
    race: Mapped[str | None] = mapped_column(String, nullable=True)  # white, black, asian, native, pacific, two_or_more, decline
    hispanic_latino: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # True=yes, False=no, None=decline
    veteran_status: Mapped[str | None] = mapped_column(String, nullable=True)  # not_veteran, veteran, decline
    disability_status: Mapped[str | None] = mapped_column(String, nullable=True)  # no, yes, decline
    how_did_you_hear: Mapped[str | None] = mapped_column(String, nullable=True)  # linkedin, job_board, referral, etc.

    # --- Resume file reference ---
    resume_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Settings ---
    autopilot_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autopilot_threshold: Mapped[int] = mapped_column(Integer, default=70)
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
    notify_on_apply: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_daily_digest: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Slack integration ---
    slack_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    archetype: Mapped[str | None] = mapped_column(String, nullable=True)

    profile_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_step: Mapped[str] = mapped_column(String, default="upload_resume")

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
