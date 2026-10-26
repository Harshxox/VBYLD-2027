"""
Sessions route — v4
Changes from v3:
  - REMOVED public GET /api/sessions (was leaking all client PII without auth)
  - GET  /api/sessions/admin  → now uses Depends(_require_admin) correctly (Bug 3 fix)
  - Admin routes now use a server-side login (see app/security.py)
  - DELETE /api/sessions/{id}         → admin only
  - GET  /api/sessions/{id}/audio     → list audio files for a session

v4.1 — participant data is no longer world-readable:
  - POST /api/sessions returns a per-session access_token.
  - GET /{id}, GET /{id}/report, GET /{id}/report.pdf and GET /{id}/audio now
    require that token (X-Session-Token) or an admin token. A session UUID alone
    no longer exposes a participant's name, answers, report or voice recordings.
  - The public /uploads/audio static mount was replaced by an authenticated
    GET /{id}/audio/{file_name} route.
"""
import os, shutil
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.models.assessment import AssessmentSession, AudioFile
from app.models.schemas import SessionCreate, SessionOut, SessionCreateOut
from app.models.sensors import SensorLink, SensorReading
from app.models.consent import Consent, CONSENT_VERSION
from app.security import (
    require_admin,
    require_session_access,
    session_token_matches,
    new_session_token,
)
import uuid

router = APIRouter()

AUDIO_DIR   = os.getenv("AUDIO_UPLOAD_DIR", "./uploads/audio")


def _authorized(session: AssessmentSession, caller: str, presented: Optional[str]) -> bool:
    """
    True when `caller` may read `session`.

    `caller` comes from require_session_access and is either "session:<token>"
    (an X-Session-Token header was sent) or an admin identity from a valid admin
    token. A session token only unlocks the session it was minted for.
    """
    if caller.startswith("session:"):
        return session_token_matches(session.access_token, presented)
    return True  # authenticated admin


def _get_session_for(db: Session, session_id: str, caller: str,
                     presented: Optional[str]) -> AssessmentSession:
    session = db.query(AssessmentSession).filter(AssessmentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _authorized(session, caller, presented):
        raise HTTPException(
            status_code=403,
            detail="That access token belongs to a different session.",
        )
    return session


# ── Create session ────────────────────────────────────────────────────────────

@router.post("", response_model=SessionCreateOut, status_code=201)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    """
    Create a new assessment session.
    Accepts optional client_* fields from the registration form in index.html.

    The response carries a one-time access_token. The browser keeps it and sends it
    as X-Session-Token on every later request for this session's data.
    """
    if payload.input_mode not in ("typed", "voice"):
        raise HTTPException(status_code=422, detail="input_mode must be 'typed' or 'voice'")
    if not payload.consent:
        raise HTTPException(status_code=422, detail="Consent is required before any data can be stored.")

    session = AssessmentSession(
        id=str(uuid.uuid4()),
        input_mode=payload.input_mode,
        created_at=datetime.now(timezone.utc),
        client_name=payload.client_name,
        client_email=payload.client_email,
        client_phone=payload.client_phone,
        client_age=payload.client_age,
        client_job=payload.client_job,
        access_token=new_session_token(),
    )
    db.add(session)
    # The version recorded is the one the SERVER was serving, never one supplied
    # by the client. Trusting payload.consent_version meant a caller could claim
    # acceptance of whatever wording the server has since replaced, which is
    # exactly the claim a consent record has to be able to prove.
    db.add(Consent(session_id=session.id, version=CONSENT_VERSION,
                   accepted_at=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(session)
    return session


# ── Admin: list all sessions with client info ─────────────────────────────────

@router.get("/admin", response_model=list[SessionOut])
def admin_list_sessions(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """
    Return ALL sessions (most recent first) including client details and scores.
    Requires admin login (Authorization: Bearer <token> from POST /api/admin/login).
    """
    return (
        db.query(AssessmentSession)
        .order_by(AssessmentSession.created_at.desc())
        .all()
    )


# ── Get single session ────────────────────────────────────────────────────────

@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    """
    Return one session with its client details, answers and audio files.

    Requires this session's access token (X-Session-Token) or an admin token.
    Without one the response is 401 - a session UUID on its own is not enough,
    because ids turn up in browser history, logs and screenshots.
    """
    session = _get_session_for(db, session_id, caller, x_session_token)
    return session


# ── Delete session (admin only) ───────────────────────────────────────────────

@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """
    Permanently delete a session, all its answers, and all audio files from disk.
    Requires admin login. Called by index.html deleteClient().
    """
    session = db.query(AssessmentSession).filter(AssessmentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Remove audio files from disk
    session_audio_dir = os.path.join(AUDIO_DIR, session_id)
    if os.path.isdir(session_audio_dir):
        shutil.rmtree(session_audio_dir, ignore_errors=True)

    db.query(SensorReading).filter(SensorReading.session_id == session_id).delete()
    db.query(SensorLink).filter(SensorLink.session_id == session_id).delete()
    db.query(Consent).filter(Consent.session_id == session_id).delete()
    db.delete(session)   # cascades to answers + audio_files rows
    db.commit()
    return


# ── List audio files for a session ───────────────────────────────────────────

@router.get("/{session_id}/audio")
def list_audio_files(
    session_id: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    """
    Return all audio clips recorded for a session.
    Each entry includes audio_url so the admin panel can play them back.
    Requires this session's access token or an admin token.
    """
    session = _get_session_for(db, session_id, caller, x_session_token)
    return [
        {
            "question_id": af.question_id,
            "file_name":   af.file_name,
            "audio_url":   f"/api/sessions/{session_id}/audio/{af.file_name}",
            "mime_type":   af.mime_type,
            "size_bytes":  af.size_bytes,
            "created_at":  af.created_at,
        }
        for af in session.audio_files
    ]


@router.get("/{session_id}/audio/{file_name}")
def get_audio_file(
    session_id: str,
    file_name: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    """
    Stream one recorded clip. Replaces the old public /uploads/audio static mount,
    which served every participant's voice recording to anyone with the URL.

    The filename is resolved against the AudioFile rows belonging to THIS session,
    and the final path is re-checked to be inside the session folder, so a crafted
    file_name cannot read arbitrary files.
    """
    session = _get_session_for(db, session_id, caller, x_session_token)

    wanted = os.path.basename(file_name)
    record = next(
        (af for af in session.audio_files if af.file_name == wanted),
        None,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Audio file not found")

    path = os.path.abspath(record.file_path)
    root = os.path.abspath(os.path.join(AUDIO_DIR, session_id))
    if os.path.commonpath([path, root]) != root or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        path,
        media_type=record.mime_type or "application/octet-stream",
        filename=wanted,
    )
