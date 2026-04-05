"""TinyFishBriefCache: stores raw scrape results from TinyFish for briefs.

Separated from ReconDossier (LLM-only quick briefs) and FoxhoundBrief
(synthesized full briefs). This table is the source of truth for what
TinyFish returned, so we never re-scrape the same company.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class TinyFishBriefCache(Base):
    __tablename__ = "tinyfish_brief_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    company_normalized: Mapped[str] = mapped_column(String, index=True)
    company_display: Mapped[str] = mapped_column(String)

    # Raw TinyFish scrape results (JSON strings)
    careers_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    sources_completed: Mapped[str] = mapped_column(Text, default="[]")
    sources_failed: Mapped[str] = mapped_column(Text, default="[]")
    tinyfish_credits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
