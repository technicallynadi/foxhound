"""Channel identity: links a Foxhound user to an external messaging identity."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_channel_external"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String, index=True)  # "slack" | "discord" | "sms"
    external_id: Mapped[str] = mapped_column(String, index=True)  # Slack user ID, Discord user ID, phone
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
