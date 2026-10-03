"""
Record of each participant's consent (which wording they agreed to, and when).
A separate table so existing databases need no migration.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey
from app.db.database import Base
from app.models.assessment import now_utc

CONSENT_VERSION = "2026-10-v1"


class Consent(Base):
    __tablename__ = "consents"

    session_id  = Column(String, ForeignKey("assessment_sessions.id"), primary_key=True)
    version     = Column(String, nullable=False)
    accepted_at = Column(DateTime, default=now_utc, nullable=False)
