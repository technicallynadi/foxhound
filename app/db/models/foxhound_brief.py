"""FoxhoundBrief: the flagship per-application intelligence artifact.

Assembled progressively from post-apply research cascade:
company brief, pathfinder, network map, dossier, watchdog status.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class FoxhoundBrief(Base):
    __tablename__ = "foxhound_briefs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    application_id: Mapped[str] = mapped_column(String, unique=True, index=True)

    status: Mapped[str] = mapped_column(String, default="assembling")
    # "assembling" | "partial" | "ready"

    # Sections (JSON blobs, each populated independently)
    company_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pathfinder_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_map_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dossier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    watchdog_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # LLM-generated recommendation
    recommended_next_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
