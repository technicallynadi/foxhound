from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.db.session import Base

TZDateTime = DateTime(timezone=True)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    referral_source = Column(String, nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
