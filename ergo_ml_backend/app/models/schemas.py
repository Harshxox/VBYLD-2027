from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, EmailStr, Field


# ── Answers ───────────────────────────────────────────────────────────────────

class AnswerIn(BaseModel):
    question_id:   int
    question_text: str
    typed_answer:  Optional[str] = None
    transcript:    Optional[str] = None
    audio_url:     Optional[str] = None

class AnswerOut(BaseModel):
    id:            int
    session_id:    str
    question_id:   int
    question_text: str
    typed_answer:  Optional[str]
    transcript:    Optional[str]
    audio_url:     Optional[str]
    created_at:    datetime
    model_config = {"from_attributes": True}


# ── Scores ────────────────────────────────────────────────────────────────────

class RiskScores(BaseModel):
    posture_risk:         float
    eye_strain:           float
    workload_stress:      float
    musculoskeletal_risk: float
    recovery_risk:        float
    overall_risk:         float


# ── Report ────────────────────────────────────────────────────────────────────

class ReportData(BaseModel):
    level:                str           # Low | Moderate | High
    top_factors:          List[str]
    action_plan:          List[str]
    category_breakdown:   Dict[str, Any]
    detailed_findings:    List[str]
    positive_habits:      List[str]
    wearable:             Optional[Dict[str, Any]] = None   # body signals + ErgoCare Index (sensor_scoring.py)


# ── Sessions ──────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    """
    Matches exactly what index.html sends on registration + startAssessment.
    All client_* fields are optional so legacy callers without them still work.
    """
    input_mode:   str                   # 'typed' | 'voice'
    client_name:  Optional[str] = None
    client_email: Optional[EmailStr] = None   # Bug D fix: validates email format
    client_phone: Optional[str] = None
    client_age:   Optional[int] = None
    client_job:   Optional[str] = None
    consent:         bool = False            # must be True - enforced by the server
    consent_version: Optional[str] = None

class AudioFileOut(BaseModel):
    id:          int
    question_id: int
    file_name:   str
    audio_url:   str                    # relative URL e.g. /uploads/audio/{sid}/q3_rec.webm
    mime_type:   Optional[str]
    size_bytes:  Optional[int]
    created_at:  datetime
    model_config = {"from_attributes": True}

class SessionOut(BaseModel):
    id:                   str
    input_mode:           str
    created_at:           datetime
    completed_at:         Optional[datetime]
    client_name:          Optional[str]
    client_email:         Optional[str]
    client_phone:         Optional[str]
    client_age:           Optional[int]
    client_job:           Optional[str]
    overall_risk:         Optional[float]
    posture_risk:         Optional[float]
    eye_strain:           Optional[float]
    workload_stress:      Optional[float]
    musculoskeletal_risk: Optional[float]
    recovery_risk:        Optional[float]
    report_json:          Optional[dict]
    answers:              List[AnswerOut]  = []
    audio_files:          List[AudioFileOut] = []
    model_config = {"from_attributes": True}

class CompleteSessionOut(BaseModel):
    session_id: str
    scores:     RiskScores
    report:     ReportData


# ── Wearable sensors ──────────────────────────────────────────────────────────

class SensorReadingIn(BaseModel):
    """
    One reading from the ESP32 (firmware/ergocare_wearable), sent once per second
    over Wi-Fi or via firmware/usb_bridge.py. Defaults keep older firmware working.
    """
    device_id:   Optional[str] = None   # the URL's device_id is authoritative
    seq:         int   = 0
    uptime_ms:   int   = 0
    bpm:         float = 0
    bpm_avg:     float = 0
    finger:      bool  = False
    ir:          int   = 0
    gsr_raw:     float = 0
    gsr_mv:      float = 0
    gsr_contact: bool  = False
    tilt:        float = 0
    ax:          float = 0
    ay:          float = 0
    az:          float = 0
    gyro:        float = 0
    acc_std:     float = 0
    moving:      bool  = False
    pulse_ok:    bool  = True
    mpu_ok:      bool  = True
    wifi:        bool  = False
    age_ms:      int   = 0      # set by usb_bridge when delivering buffered readings

DEVICE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"

class DeviceLinkIn(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
