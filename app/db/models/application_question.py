"""Application question model.

Tracks individual form questions that need answers during a job application.
Child of Application (not a separate conversation). Each question tracks
classification, draft answer, final answer, and resolution status.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(String, index=True)

    # The question
    question_index: Mapped[int] = mapped_column(Integer)
    field_label: Mapped[str] = mapped_column(String)
    field_name: Mapped[str | None] = mapped_column(String, nullable=True)
    field_type: Mapped[str] = mapped_column(String, default="text")

    # Classification: "auto" | "draft_and_approve" | "ask_directly"
    category: Mapped[str] = mapped_column(String)

    # Draft answer (for draft_and_approve)
    draft_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolution
    status: Mapped[str] = mapped_column(String, default="pending")
    # "pending" | "approved" | "answered" | "auto_filled"
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
