"""
Answers route — v3.2
Fixes over v3.1:
  - Bug 4: Re-uploading audio for the same question now deletes the old file from disk
    before saving the new one (previously the old .webm was orphaned on disk).
"""
import os
import shutil
import uuid
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.assessment import AssessmentSession, AssessmentAnswer, AudioFile
from app.models.schemas import AnswerIn, AnswerOut
from app.domain.questions import QUESTIONS_BY_ID
from app.security import require_session_access, session_token_matches

router = APIRouter()

AUDIO_DIR        = os.getenv("AUDIO_UPLOAD_DIR", "./uploads/audio")
MAX_AUDIO_BYTES  = int(os.getenv("MAX_AUDIO_MB",  "10"))  * 1024 * 1024   # default 10 MB
MIN_FREE_BYTES   = int(os.getenv("MIN_FREE_MB",  "500")) * 1024 * 1024    # default 500 MB
ALLOWED_TYPES    = {
    "audio/webm", "audio/ogg", "audio/mp4",
    "audio/wav",  "audio/wave", "audio/x-wav",
    "audio/m4a",  "video/webm",                 # Chrome labels .webm as video/webm
}
ALLOWED_EXTS     = {".webm", ".ogg", ".mp4", ".wav", ".m4a", ".mp3"}
ALLOWED_TYPES.add("audio/mpeg")

os.makedirs(AUDIO_DIR, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session_or_404(session_id: str, db: Session) -> AssessmentSession:
    session = db.query(AssessmentSession).filter(
        AssessmentSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _check_disk_space():
    """Refuse upload if free disk space is below MIN_FREE_BYTES."""
    try:
        free = shutil.disk_usage(AUDIO_DIR).free
    except Exception:
        return  # can't check — allow and move on
    if free < MIN_FREE_BYTES:
        free_mb  = free  // (1024 * 1024)
        limit_mb = MIN_FREE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=507,
            detail=(
                f"Server storage critically low ({free_mb} MB free). "
                f"Uploads are paused until at least {limit_mb} MB is available. "
                "Contact the administrator."
            ),
        )


def _check_file_type(file: UploadFile):
    """Reject non-audio MIME types and non-audio file extensions."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    ext  = _safe_ext(file.filename)

    mime_ok = mime in ALLOWED_TYPES
    ext_ok  = ext in ALLOWED_EXTS or ext == ""   # ext may be empty for blobs

    if not mime_ok or not ext_ok:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{mime}' (extension '{ext or 'none'}'). "
                f"Allowed formats: {', '.join(sorted(ALLOWED_EXTS))}."
            ),
        )


def _safe_ext(filename: str | None) -> str:
    """
    Lower-cased extension of a client-supplied filename, or "" if there isn't one.

    The extension is taken from the BASENAME only, so a name like
    "x/../../y.wav" cannot smuggle path separators into it.
    """
    base = os.path.basename(filename or "").replace("\\", "/").split("/")[-1]
    ext  = os.path.splitext(base)[1].lower()
    # Only ever keep a short, alphanumeric extension such as ".webm".
    if len(ext) > 6 or not ext.startswith(".") or not ext[1:].isalnum():
        return ""
    return ext


def _safe_audio_path(session_id: str, question_id: int, filename: str | None) -> str:
    """
    Build an ABSOLUTE path that is guaranteed to stay inside AUDIO_DIR/{session_id}.

    The stored name is fully server-generated — `q{question_id}_{uuid}{ext}` — so a
    malicious filename can never influence the path. The final realpath check is a
    belt-and-braces guard against symlinked session directories.
    """
    # session_id reaches us from the URL, so keep it to a safe charset.
    if not session_id or not all(c.isalnum() or c in "-_" for c in session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")

    ext = _safe_ext(filename)
    if ext not in ALLOWED_EXTS:
        ext = ".webm"
    safe_name = f"q{question_id}_{uuid.uuid4().hex}{ext}"
    file_path = os.path.abspath(os.path.join(AUDIO_DIR, session_id, safe_name))

    # Containment check: the resolved path must sit inside the session directory.
    session_root = os.path.abspath(os.path.join(AUDIO_DIR, session_id))
    if os.path.commonpath([file_path, session_root]) != session_root:
        raise HTTPException(status_code=400, detail="Invalid filename")

    return file_path


def _check_file_size(data: bytes):
    """Reject files that exceed MAX_AUDIO_BYTES."""
    if len(data) > MAX_AUDIO_BYTES:
        actual_mb = len(data) / (1024 * 1024)
        limit_mb  = MAX_AUDIO_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=(
                f"Audio file too large ({actual_mb:.1f} MB). "
                f"Maximum allowed size is {limit_mb} MB per clip. "
                "Please shorten your recording and try again."
            ),
        )


# ── Routes ────────────────────────────────────────────────────────────────────

def _check_audio_header(data: bytes):
    """Reject obvious disguised text; signatures do not validate an entire codec."""
    valid = (
        (data.startswith(b"RIFF") and data[8:12] == b"WAVE")
        or data.startswith(b"OggS")
        or data.startswith(b"\x1a\x45\xdf\xa3")
        or (len(data) >= 12 and data[4:8] == b"ftyp")
        or data.startswith(b"ID3")
        or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0)
    )
    if not valid:
        raise HTTPException(status_code=415, detail="The content is not a supported audio container.")


def _question_or_422(question_id: int):
    question = QUESTIONS_BY_ID.get(question_id)
    if question is None:
        raise HTTPException(status_code=422, detail="Unknown questionnaire question id.")
    return question


@router.post("/{session_id}/answers", response_model=AnswerOut, status_code=201)
def save_answer(
    session_id: str,
    payload:    AnswerIn,
    db:         Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller:     str = Depends(require_session_access),
):
    """
    Save or upsert a single typed/voice answer for one question.
    Called per-question as the user progresses through the assessment.
    """
    session = _get_session_or_404(session_id, db)
    if caller.startswith("session:") and not session_token_matches(session.access_token, x_session_token):
        raise HTTPException(status_code=403, detail="That access token belongs to a different session.")

    question = _question_or_422(payload.question_id)
    if not (payload.typed_answer or "").strip() and not (payload.transcript or "").strip():
        raise HTTPException(status_code=422, detail="An answer or transcript is required.")
    recording = db.query(AudioFile).filter(
        AudioFile.session_id == session_id,
        AudioFile.question_id == payload.question_id,
    ).first()
    audio_url = recording.audio_url if recording else None
    if payload.audio_url and payload.audio_url != audio_url:
        raise HTTPException(status_code=422, detail="Audio must be uploaded for this session and question.")
    answer = db.query(AssessmentAnswer).filter(
        AssessmentAnswer.session_id  == session_id,
        AssessmentAnswer.question_id == payload.question_id,
    ).first()
    if answer is None:
        answer = AssessmentAnswer(session_id=session_id, question_id=payload.question_id)
    answer.question_text = question["text"]
    answer.typed_answer = payload.typed_answer
    answer.transcript = payload.transcript
    answer.audio_url = audio_url
    answer.created_at = datetime.now(timezone.utc)
    db.add(answer)
    db.commit()
    db.refresh(answer)
    return answer


@router.post("/{session_id}/answers/{question_id}/audio", status_code=201)
async def upload_audio(
    session_id:  str,
    question_id: int,
    file:        UploadFile = File(...),
    transcript:  str        = Form(default=""),
    db:          Session    = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller:      str        = Depends(require_session_access),
):
    """
    Upload a voice recording for one question.

    Limits enforced (all return clear HTTP errors):
      - File type must be audio/webm, ogg, mp4, wav, or m4a  → 415
      - File size must be ≤ MAX_AUDIO_MB (default 10 MB)     → 413
      - Server must have ≥ MIN_FREE_MB disk space free        → 507

    On success:
      - Replaces old audio only after the new recording is committed
      - Saves file to  uploads/audio/{session_id}/q{n}_{uuid}{ext}
        (name is generated server-side; a client filename can never escape the folder)
      - Updates        assessment_answers row (audio_url + transcript)
      - Inserts        audio_files row for admin playback

    Requires this session's access token (X-Session-Token) or an admin token.
    """
    session = _get_session_or_404(session_id, db)
    if caller.startswith("session:") and not session_token_matches(session.access_token, x_session_token):
        raise HTTPException(status_code=403, detail="That access token belongs to a different session.")

    # ── Guard 1: file type ────────────────────────────────────────────────────
    question = _question_or_422(question_id)
    _check_file_type(file)

    # ── Guard 2: read into memory so we can size-check before touching disk ──
    data = await file.read(MAX_AUDIO_BYTES + 1)
    _check_file_size(data)
    _check_audio_header(data)

    # ── Guard 3: disk space ───────────────────────────────────────────────────
    _check_disk_space()

    # Preserve the existing recording until its replacement has committed.
    old_audio = db.query(AudioFile).filter(
        AudioFile.session_id  == session_id,
        AudioFile.question_id == question_id,
    ).first()
    old_path = old_audio.file_path if old_audio else None

    # ── Delete the old AudioFile DB row ───────────────────────────────────────
    db.query(AudioFile).filter(
        AudioFile.session_id  == session_id,
        AudioFile.question_id == question_id,
    ).delete()

    # ── Save new file to disk ─────────────────────────────────────────────────
    session_dir = os.path.join(AUDIO_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Path is fully server-generated and verified to stay inside session_dir.
    file_path = _safe_audio_path(session_id, question_id, file.filename)
    safe_name = os.path.basename(file_path)

    with open(file_path, "wb") as f:
        f.write(data)

    file_size = len(data)
    audio_url = f"/api/sessions/{session_id}/audio/{safe_name}"

    # ── Insert new audio_files row ────────────────────────────────────────────
    db.add(AudioFile(
        session_id  = session_id,
        question_id = question_id,
        file_name   = safe_name,
        file_path   = file_path,
        mime_type   = file.content_type,
        size_bytes  = file_size,
        created_at  = datetime.now(timezone.utc),
    ))

    # ── Update / create answer row ────────────────────────────────────────────
    existing = db.query(AssessmentAnswer).filter(
        AssessmentAnswer.session_id  == session_id,
        AssessmentAnswer.question_id == question_id,
    ).first()

    if existing:
        existing.audio_url = audio_url
        if transcript:
            existing.transcript = transcript
    else:
        db.add(AssessmentAnswer(
            session_id    = session_id,
            question_id   = question_id,
            question_text = question["text"],
            transcript    = transcript or None,
            audio_url     = audio_url,
            created_at    = datetime.now(timezone.utc),
        ))

    try:
        db.commit()
    except Exception:
        db.rollback()
        os.remove(file_path)
        raise

    if old_path and old_path != file_path and os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    limit_mb  = MAX_AUDIO_BYTES // (1024 * 1024)
    actual_mb = round(file_size / (1024 * 1024), 2)

    return {
        "message":   "Audio uploaded successfully",
        "audio_url": audio_url,
        "file_size": file_size,
        "size_mb":   actual_mb,
        "limit_mb":  limit_mb,
    }
