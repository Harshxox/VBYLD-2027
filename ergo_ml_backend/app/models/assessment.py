import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import relationship
from app.db.database import Base

def new_uuid(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"

    id           = Column(String, primary_key=True, default=new_uuid)
    input_mode   = Column(String, nullable=False)       # 'typed' | 'voice'
    created_at   = Column(DateTime, default=now_utc)
    completed_at = Column(DateTime, nullable=True)

    # ── Client profile (sent from registration form) ──────────────────────────
    client_name  = Column(String,  nullable=True)
    client_email = Column(String,  nullable=True)
    client_phone = Column(String,  nullable=True)
    client_age   = Column(Integer, nullable=True)
    client_job   = Column(String,  nullable=True)

    # ── Access token ───────────────────────────────────────────────────────────
    # Secret handed to the participant's own browser when the session is created.
    # Required (via X-Session-Token) on every route that returns this session's
    # personal data, so a guessed session UUID is not enough to read someone's
    # name, answers, report or voice recordings. Admins use their own token.
    access_token = Column(String, nullable=True, index=True)

    # ── Risk scores 0-100 ─────────────────────────────────────────────────────
    overall_risk         = Column(Float, nullable=True)
    posture_risk         = Column(Float, nullable=True)
    eye_strain           = Column(Float, nullable=True)
    workload_stress      = Column(Float, nullable=True)
    musculoskeletal_risk = Column(Float, nullable=True)
    recovery_risk        = Column(Float, nullable=True)

    # ── Full report JSON ──────────────────────────────────────────────────────
    report_json = Column(JSON, nullable=True)

    answers     = relationship("AssessmentAnswer", back_populates="session", cascade="all, delete-orphan")
    audio_files = relationship("AudioFile",         back_populates="session", cascade="all, delete-orphan")


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    session_id    = Column(String, ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    question_id   = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    typed_answer  = Column(Text, nullable=True)
    transcript    = Column(Text, nullable=True)
    audio_url     = Column(Text, nullable=True)   # relative URL served by FastAPI
    created_at    = Column(DateTime, default=now_utc)

    session = relationship("AssessmentSession", back_populates="answers")

    __table_args__ = (
        # save_answer() deletes the previous row for this pair on every re-answer,
        # and the report reads them back in question order.
        Index("ix_assessment_answers_session_q", "session_id", "question_id"),
    )


class AudioFile(Base):
    __tablename__ = "audio_files"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String, ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, nullable=False)
    file_name   = Column(String, nullable=False)
    file_path   = Column(String, nullable=False)
    mime_type   = Column(String, nullable=True)
    size_bytes  = Column(Integer, nullable=True)
    created_at  = Column(DateTime, default=now_utc)

    session = relationship("AssessmentSession", back_populates="audio_files")

    @property
    def audio_url(self) -> str:
        """
        Relative URL of this clip, served by the authenticated route in
        routes/sessions.py.

        This is a plain attribute, not a column, but AudioFileOut declares it and
        reads it with from_attributes - without it every response that serialises
        a session's audio_files fails validation and returns HTTP 500, which broke
        GET /api/sessions/{id} and the whole admin panel as soon as one person
        recorded a voice answer.
        """
        return f"/api/sessions/{self.session_id}/audio/{self.file_name}"

    __table_args__ = (
        Index("ix_audio_files_session_q", "session_id", "question_id"),
    )
