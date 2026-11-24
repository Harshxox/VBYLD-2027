"""Export pseudonymized research CSVs; free text may still contain identifiers."""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app.domain.questions import QUESTIONS
from app.models.assessment import AssessmentSession
from app.models.sensors import SensorLink, SensorReading


EXPORT_DIR = Path(os.getenv("RESEARCH_EXPORT_DIR", "./research_data"))
READING_FIELDS = (
    "seq", "bpm", "bpm_avg", "finger", "ir", "gsr_raw", "gsr_mv",
    "gsr_contact", "tilt", "gyro", "acc_std", "moving", "pulse_ok", "mpu_ok",
)

CSV_SCHEMAS = {
    "sessions.csv": (
        ["session_id", "created_at", "completed_at", "input_mode", "age_band",
         "job_role", "device_id", "baseline_started_at", "baseline_bpm",
         "baseline_gsr", "questionnaire_overall", "posture_risk", "eye_strain",
         "workload_stress", "musculoskeletal_risk", "recovery_risk",
         "wearable_available", "objective_score", "combined_index",
         "export_version"],
        ["session_id"],
    ),
    "answers.csv": (
        ["session_id", "question_id", "category", "question_text", "answer",
         "transcript", "answer_recorded_at", "export_version"],
        ["session_id", "question_id"],
    ),
    "wearable_readings.csv": (
        ["session_id", "device_id", "measured_at", "received_at", "phase",
         *READING_FIELDS, "export_version"],
        ["session_id", "device_id", "seq", "measured_at"],
    ),
    "wearable_features.csv": (
        ["session_id", "reading_count", "first_reading_at", "last_reading_at",
         "baseline_bpm", "baseline_gsr", "mean_bpm", "median_bpm",
         "mean_gsr", "mean_orientation_change", "max_orientation_change",
         "moving_percent", "pulse_contact_percent", "gsr_contact_percent",
         "mpu_valid_percent", "objective_score", "combined_index",
         "export_version"],
        ["session_id"],
    ),
}

EXPORT_VERSION = "research-v1"
QUESTION_BY_ID = {q["id"]: q for q in QUESTIONS}


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _age_band(age: int | None) -> str:
    if age is None:
        return ""
    if age < 25:
        return "16-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    return "55+"


def _number(values: Iterable[Any], *, method: str = "mean") -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    if method == "median":
        nums.sort()
        middle = len(nums) // 2
        return nums[middle] if len(nums) % 2 else (nums[middle - 1] + nums[middle]) / 2
    return sum(nums) / len(nums)


def _percentage(values: Iterable[Any]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(bool(v) for v in items) * 100.0 / len(items)


def _phase(reading: SensorReading, link: SensorLink) -> str:
    if not link.baseline_started_at:
        return "assessment"
    elapsed = (reading.received_at - link.baseline_started_at).total_seconds()
    return "baseline" if 0 <= elapsed <= 60 else "assessment"


def _upsert_csv(filename: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / filename
    fieldnames, key_fields = CSV_SCHEMAS[filename]
    existing: dict[tuple[str, ...], dict[str, Any]] = {}
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing[tuple(row.get(k, "") for k in key_fields)] = row
    for row in rows:
        existing[tuple(_iso(row.get(k)) for k in key_fields)] = {
            field: _iso(row.get(field)) for field in fieldnames
        }

    fd, temp_name = tempfile.mkstemp(prefix=f"{filename}.", dir=EXPORT_DIR)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing.values())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def export_completed_session(
    session: AssessmentSession,
    answers: list[Any],
    readings: list[SensorReading],
    link: SensorLink | None,
    report: dict[str, Any],
) -> None:
    """Write or refresh all research CSV rows for one completed session.

    Direct identifiers (name, email, phone, audio) are intentionally excluded.
    The source database and authenticated report endpoints remain unchanged.
    """
    wearable = report.get("wearable") or {}
    combined = wearable.get("combined") or {}
    baseline = (link.baseline if link else None) or {}

    session_row = {
        "session_id": session.id,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
        "input_mode": session.input_mode,
        "age_band": _age_band(session.client_age),
        "job_role": session.client_job,
        "device_id": link.device_id if link else "",
        "baseline_started_at": link.baseline_started_at if link else None,
        "baseline_bpm": baseline.get("bpm"),
        "baseline_gsr": baseline.get("gsr"),
        "questionnaire_overall": session.overall_risk,
        "posture_risk": session.posture_risk,
        "eye_strain": session.eye_strain,
        "workload_stress": session.workload_stress,
        "musculoskeletal_risk": session.musculoskeletal_risk,
        "recovery_risk": session.recovery_risk,
        "wearable_available": wearable.get("available", False),
        "objective_score": wearable.get("objective_score"),
        "combined_index": combined.get("index"),
        "export_version": EXPORT_VERSION,
    }
    _upsert_csv("sessions.csv", [session_row])

    answer_rows = []
    for answer in answers:
        question = QUESTION_BY_ID.get(answer.question_id, {})
        answer_rows.append({
            "session_id": session.id,
            "question_id": answer.question_id,
            "category": question.get("category", ""),
            "question_text": answer.question_text,
            "answer": answer.typed_answer or answer.transcript or "",
            "transcript": answer.transcript or "",
            "answer_recorded_at": answer.created_at,
            "export_version": EXPORT_VERSION,
        })
    _upsert_csv("answers.csv", answer_rows)

    reading_rows = []
    for reading in readings:
        raw = reading.as_dict()
        reading_rows.append({
            "session_id": session.id,
            "device_id": reading.device_id,
            "measured_at": reading.received_at,
            "received_at": reading.received_at,
            "phase": _phase(reading, link) if link else "assessment",
            **{field: raw.get(field) for field in READING_FIELDS},
            "export_version": EXPORT_VERSION,
        })
    _upsert_csv("wearable_readings.csv", reading_rows)

    bpm = [r.bpm_avg for r in readings if r.bpm_avg and r.finger]
    gsr = [r.gsr_raw for r in readings if r.gsr_raw is not None and r.gsr_contact]
    orientation = [r.tilt for r in readings if r.tilt is not None and r.mpu_ok]
    features = {
        "session_id": session.id,
        "reading_count": len(readings),
        "first_reading_at": readings[0].received_at if readings else None,
        "last_reading_at": readings[-1].received_at if readings else None,
        "baseline_bpm": baseline.get("bpm"),
        "baseline_gsr": baseline.get("gsr"),
        "mean_bpm": _number(bpm),
        "median_bpm": _number(bpm, method="median"),
        "mean_gsr": _number(gsr),
        "mean_orientation_change": _number(orientation),
        "max_orientation_change": max(orientation) if orientation else None,
        "moving_percent": _percentage(r.moving for r in readings),
        "pulse_contact_percent": _percentage(r.finger for r in readings),
        "gsr_contact_percent": _percentage(r.gsr_contact for r in readings),
        "mpu_valid_percent": _percentage(r.mpu_ok for r in readings),
        "objective_score": wearable.get("objective_score"),
        "combined_index": combined.get("index"),
        "export_version": EXPORT_VERSION,
    }
    _upsert_csv("wearable_features.csv", [features])


def delete_session_exports(session_id: str) -> None:
    """Remove a session from the research copies without touching other rows."""
    for filename, (fieldnames, _) in CSV_SCHEMAS.items():
        path = EXPORT_DIR / filename
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8") as fh:
            rows = [row for row in csv.DictReader(fh) if row.get("session_id") != session_id]
        fd, temporary = tempfile.mkstemp(prefix=f"{filename}.", dir=EXPORT_DIR)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def write_data_dictionary() -> None:
    """Create a human-readable schema CSV once, without participant data."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "data_dictionary.csv"
    if path.exists():
        return
    rows = [
        ("sessions.csv", "session_id", "Pseudonymous application session identifier"),
        ("sessions.csv", "age_band", "Age range; exact age is not exported"),
        ("answers.csv", "answer", "Participant answer used for scoring"),
        ("wearable_readings.csv", "bpm_avg", "Median recent pulse estimate from the band"),
        ("wearable_readings.csv", "gsr_raw", "Raw skin-response reading"),
        ("wearable_readings.csv", "tilt", "Band-wrist orientation change from neutral calibration"),
        ("wearable_readings.csv", "phase", "baseline or assessment"),
        ("wearable_features.csv", "objective_score", "Baseline-relative body-signal score; not a clinical label"),
        ("wearable_features.csv", "combined_index", "Existing questionnaire + body-signal index; not ground truth"),
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "field", "description"])
        writer.writerows(rows)
