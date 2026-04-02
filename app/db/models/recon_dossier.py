"""ReconDossier model: cached company intelligence dossiers."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class ReconDossier(Base):
    __tablename__ = "recon_dossiers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_normalized: Mapped[str] = mapped_column(String, unique=True, index=True)
    company_display: Mapped[str] = mapped_column(String)

    # Raw source data (stored as JSON strings)
    careers_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Synthesized output (JSON string)
    synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    sources_completed: Mapped[str] = mapped_column(Text, default="[]")
    sources_failed: Mapped[str] = mapped_column(Text, default="[]")
    tinyfish_credits: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
