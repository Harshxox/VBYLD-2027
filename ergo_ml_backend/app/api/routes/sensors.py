"""
Wearable sensor routes.

Device side (ESP32 over Wi-Fi, or firmware/usb_bridge.py over USB):
  POST /api/devices/{device_id}/readings     one reading per second
  GET  /api/devices                          devices seen recently
  GET  /api/devices/{device_id}/latest       live reading before a session exists

Session side (the web app):
  POST   /api/sessions/{id}/device           attach a wearable to this session
  DELETE /api/sessions/{id}/device           detach it
  POST   /api/sessions/{id}/baseline/start   begin the 60 s relaxed baseline (+ zero posture)
  POST   /api/sessions/{id}/baseline/finish  compute the personal baseline
  GET    /api/sessions/{id}/sensors/latest   live values, streaks and on-screen warnings
  GET    /api/sessions/{id}/sensors/history  all readings, for the report graphs
"""
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.domain import sensors as S
from app.models.assessment import AssessmentSession, now_utc
from app.models.schemas import DEVICE_ID_PATTERN, DeviceLinkIn, SensorReadingIn
from app.models.sensors import SensorLink, SensorReading

devices_router = APIRouter()
router = APIRouter()

DEVICE_ID = Path(..., pattern=DEVICE_ID_PATTERN)
MAX_READING_AGE_MS = 180_000
READING_FIELDS = SensorReading.FIELDS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session(session_id: str, db: Session) -> AssessmentSession:
    session = db.query(AssessmentSession).filter(AssessmentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _get_link(session_id: str, db: Session) -> SensorLink:
    link = db.query(SensorLink).filter(SensorLink.session_id == session_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="No wearable linked to this session")
    return link


def _recent_rows(session_id: str, db: Session, limit: int = 200) -> List[SensorReading]:
    return (db.query(SensorReading)
            .filter(SensorReading.session_id == session_id)
            .order_by(SensorReading.received_at.desc(), SensorReading.id.desc())
            .limit(limit).all())


# ── Device side ───────────────────────────────────────────────────────────────

@devices_router.post("/{device_id}/readings")
def ingest_reading(payload: SensorReadingIn, device_id: str = DEVICE_ID, db: Session = Depends(get_db)):
    """
    Receive one reading. Always kept as the device's live value; also stored
    against the linked session when one is active. The reply tells the device
    to zero its posture when the app has started a baseline.
    """
    reading = payload.model_dump()
    reading["device_id"] = device_id
    S.registry.update(device_id, reading)

    link = (db.query(SensorLink)
            .filter(SensorLink.device_id == device_id, SensorLink.active.is_(True))
            .order_by(SensorLink.linked_at.desc())
            .first())
    if link:
        # Buffered readings (bridge was briefly cut off) keep the time they were measured
        age = timedelta(milliseconds=min(max(payload.age_ms, 0), MAX_READING_AGE_MS))
        db.add(SensorReading(session_id=link.session_id, device_id=device_id,
                             received_at=now_utc() - age, **{f: reading[f] for f in READING_FIELDS}))
        db.commit()

    return {"ok": True,
            "session_id": link.session_id if link else None,
            "calibrate": S.registry.pop_calibrate(device_id)}


@devices_router.get("")
def list_devices():
    """Devices that have sent data since the server started, newest first."""
    return sorted(
        [{"device_id": d, "age_s": age, "connected": age <= S.CONNECTED_WITHIN_S}
         for d, age in S.registry.devices()],
        key=lambda x: x["age_s"],
    )


@devices_router.get("/{device_id}/latest")
def device_latest(device_id: str = DEVICE_ID):
    """Live reading for the 'Connect wearable' screen (no session or baseline needed)."""
    reading, age = S.registry.latest(device_id)
    connected = age is not None and age <= S.CONNECTED_WITHIN_S
    return {
        "device_id": device_id,
        "connected": connected,
        "age_s":     age,
        "reading":   reading,
        "derived":   S.derive(reading, None) if reading else None,
        "warnings":  [w for w in S.warnings(reading, age, None, None, {}) if w["type"] != "baseline"],
    }


# ── Session side ──────────────────────────────────────────────────────────────

@router.post("/{session_id}/device")
def link_device(session_id: str, payload: DeviceLinkIn, db: Session = Depends(get_db)):
    """Attach a wearable. A device feeds one session at a time; older links are closed."""
    session = _get_session(session_id, db)
    if session.completed_at:
        raise HTTPException(status_code=409, detail="Session already completed")

    (db.query(SensorLink)
       .filter(SensorLink.device_id == payload.device_id, SensorLink.session_id != session_id)
       .update({"active": False}))

    link = db.query(SensorLink).filter(SensorLink.session_id == session_id).first()
    if link:
        link.device_id, link.active = payload.device_id, True
    else:
        link = SensorLink(session_id=session_id, device_id=payload.device_id, active=True, linked_at=now_utc())
        db.add(link)
    db.commit()

    _, age = S.registry.latest(payload.device_id)
    return {"session_id": session_id, "device_id": payload.device_id, "active": True,
            "device_connected": age is not None and age <= S.CONNECTED_WITHIN_S}


@router.delete("/{session_id}/device", status_code=204)
def unlink_device(session_id: str, db: Session = Depends(get_db)):
    link = _get_link(session_id, db)
    link.active = False
    db.commit()


@router.post("/{session_id}/baseline/start")
def baseline_start(session_id: str, db: Session = Depends(get_db)):
    """Start the relaxed baseline. The device zeroes its posture on its next reading."""
    link = _get_link(session_id, db)
    if not link.active:
        raise HTTPException(status_code=409, detail="Wearable is not active for this session")
    link.baseline_started_at = now_utc()
    link.baseline = None
    db.commit()
    S.registry.request_calibrate(link.device_id)
    return {"started": True, "duration_s": S.BASELINE_SECONDS,
            "message": "Sit upright and relax - keep your fingers on the sensors."}


@router.post("/{session_id}/baseline/finish")
def baseline_finish(session_id: str, db: Session = Depends(get_db)):
    """Compute and store the personal baseline from readings since baseline/start."""
    link = _get_link(session_id, db)
    if not link.baseline_started_at:
        raise HTTPException(status_code=409, detail="Baseline was not started")

    window_start = link.baseline_started_at + timedelta(seconds=S.BASELINE_SKIP_S)
    rows = (db.query(SensorReading)
            .filter(SensorReading.session_id == session_id, SensorReading.received_at >= window_start)
            .order_by(SensorReading.received_at).all())
    if len(rows) < S.BASELINE_MIN_READINGS:
        raise HTTPException(status_code=422,
                            detail=f"Only {len(rows)} readings received - is the wearable connected?")

    baseline = S.compute_baseline([r.as_dict() for r in rows])
    link.baseline = baseline
    db.commit()
    return baseline


@router.get("/{session_id}/sensors/latest")
def session_latest(session_id: str, db: Session = Depends(get_db)):
    """
    Everything the live panel needs, polled once per second:
    raw reading, values relative to baseline, streaks, and warnings to show.
    """
    link = _get_link(session_id, db)
    reading, age = S.registry.latest(link.device_id)
    connected = age is not None and age <= S.CONNECTED_WITHIN_S

    rows = [r.as_dict() for r in _recent_rows(session_id, db)]
    derived = S.derive(reading, link.baseline) if reading else None
    streak = S.streaks(rows, link.baseline) if rows and connected else None
    return {
        "device_id": link.device_id,
        "active":    link.active,
        "connected": connected,
        "age_s":     age,
        "reading":   reading,
        "baseline":  link.baseline,
        "derived":   derived,
        "streaks":   streak,
        "warnings":  S.warnings(reading, age, derived, streak, link.baseline),
    }


@router.get("/{session_id}/sensors/history")
def session_history(session_id: str,
                    max_points: int = Query(600, ge=10, le=5000),
                    db: Session = Depends(get_db)):
    """All readings for the session (evenly thinned to max_points), for report graphs."""
    _get_session(session_id, db)
    link = db.query(SensorLink).filter(SensorLink.session_id == session_id).first()
    baseline = link.baseline if link else None
    rows = (db.query(SensorReading)
            .filter(SensorReading.session_id == session_id)
            .order_by(SensorReading.received_at, SensorReading.id).all())
    hist = S.history_points([r.as_dict() for r in rows], baseline,
                            link.baseline_started_at if link else None, max_points)
    return {"session_id": session_id, "baseline": baseline, **hist}
