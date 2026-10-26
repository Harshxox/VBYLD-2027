"""
Wearable sensor tables.

Kept separate from assessment_sessions so existing databases need no migration —
create_all() simply adds these two new tables.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, JSON, Index
from app.db.database import Base
from app.models.assessment import now_utc


class SensorLink(Base):
    """Which wearable is attached to which assessment session, plus its baseline."""
    __tablename__ = "sensor_links"

    session_id          = Column(String, ForeignKey("assessment_sessions.id", ondelete="CASCADE"), primary_key=True)
    device_id           = Column(String, nullable=False, index=True)
    active              = Column(Boolean, nullable=False, default=True)   # still receiving readings
    linked_at           = Column(DateTime, default=now_utc)
    baseline_started_at = Column(DateTime, nullable=True)
    baseline            = Column(JSON, nullable=True)   # personal "normal": bpm, gsr, tilt

    __table_args__ = (
        # ingest_reading() runs once per second per device and looks the link up by
        # device_id + active; without this it is a full scan of every link ever made.
        Index("ix_sensor_links_device_active", "device_id", "active"),
    )


class SensorReading(Base):
    """One per-second reading from the wearable, stored against a session."""
    __tablename__ = "sensor_readings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String, ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    device_id   = Column(String, nullable=False)
    received_at = Column(DateTime, default=now_utc, nullable=False)
    seq         = Column(Integer)

    bpm         = Column(Float)      # last beat-to-beat interval
    bpm_avg     = Column(Float)      # median of recent beats (use this one)
    finger      = Column(Boolean)
    ir          = Column(Integer)
    gsr_raw     = Column(Float)
    gsr_mv      = Column(Float)
    gsr_contact = Column(Boolean)
    tilt        = Column(Float)      # degrees away from calibrated upright posture
    gyro        = Column(Float)
    acc_std     = Column(Float)
    moving      = Column(Boolean)
    pulse_ok    = Column(Boolean)
    mpu_ok      = Column(Boolean)

    __table_args__ = (Index("ix_sensor_readings_session_time", "session_id", "received_at"),)

    FIELDS = ("seq", "bpm", "bpm_avg", "finger", "ir", "gsr_raw", "gsr_mv", "gsr_contact",
              "tilt", "gyro", "acc_std", "moving", "pulse_ok", "mpu_ok")

    def as_dict(self) -> dict:
        """Plain dict used by app.domain.sensors / sensor_scoring."""
        d = {f: getattr(self, f) for f in self.FIELDS}
        d["received_at"] = self.received_at
        return d
