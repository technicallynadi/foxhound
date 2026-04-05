"""Dossier model: comprehensive company intelligence reports.

Built in the background after a user applies or requests a report.
Each section populates independently as TinyFish sources complete.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class Dossier(Base):
    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    company_normalized: Mapped[str] = mapped_column(String, index=True)

    # --- Status ---
    # building | partial | ready | failed
    status: Mapped[str] = mapped_column(String, default="building")

    # --- Instant sections (Claude from job posting) ---
    # JSON: {tech_stack, insider_tip, role_analysis}
    instant_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Background sections (TinyFish) ---
    company_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    careers_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    glassdoor_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    reddit_interviews_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    reddit_culture_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    engineering_blog_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    levels_fyi_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Synthesized sections (Claude after all sources) ---
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: {linkedin_message, email_draft}
    outreach_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: {key_themes, likely_questions}
    interview_prep: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_process: Mapped[str | None] = mapped_column(Text, nullable=True)
    culture_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: {range, total_comp, median, source, by_level}
    salary_estimate: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Overlap (from Pathfinder) ---
    # JSON: {shared_skills, alignment}
    overlap_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Metadata ---
    # JSON arrays stored as Text: ["company", "careers", ...]
    sources_completed: Mapped[str] = mapped_column(Text, default="[]")
    sources_failed: Mapped[str] = mapped_column(Text, default="[]")
    tinyfish_credits: Mapped[int] = mapped_column(Integer, default=0)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
