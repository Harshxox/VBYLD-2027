"""
ErgoCare AI Backend — v3
"""
import math
import os
import app.config  # noqa: F401 - loads ergo_ml_backend/.env before settings are read
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.db.database import create_db_tables
from app.api.routes import sessions, answers, reports, sensors, questions, admin
from app.domain.answer_matcher import warm_up

AUDIO_DIR = os.getenv("AUDIO_UPLOAD_DIR", "./uploads/audio")
os.makedirs(AUDIO_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_tables()
    warm_up()   # load the answer-matching model in the background
    yield


app = FastAPI(
    title="ErgoCare AI Backend",
    description=(
        "Backend for ErgoCare AI ergonomic assessment.\n\n"
        "**v4 additions:**\n"
        "- ML engine v4: fuzzy logic, weighted ensemble, decision tree, IQR anomaly detection\n"
        "- MiniLM sentence-embedding answer matcher (7-layer NLP pipeline)\n"
        "- GET /api/questions — list all 40 assessment questions\n"
        "- Client registration fields (name, email, phone, age, job) stored per session\n"
        "- GET /api/sessions/admin — admin list with all client data (admin login required)\n"
        "- DELETE /api/sessions/{id} — delete session + audio files from disk (admin login required)\n"
        "- PDF includes client info, all 40 Q&A answers, ML confidence score, and fuzzy memberships\n"
        "- ErgoCare Index = 60% questionnaire + 40% wearable body signals\n"
    ),
    version="4.0.0",
    lifespan=lifespan,
)

# CORS — set ALLOWED_ORIGINS to the web app's exact origin(s) in production, e.g.
#   ALLOWED_ORIGINS=https://your-app.vercel.app
#
# A bare "*" is NOT safe here even though it looks permissive-and-therefore-harmless.
# Starlette decides whether to echo the requesting origin by
# `not allow_all_origins or allow_credentials`; with allow_credentials=True that is
# always true, so a preflight from https://evil.example comes back with
# `Access-Control-Allow-Origin: https://evil.example` and credentials allowed. Combined
# with allow_credentials it is full cross-origin access from any website.
#
# So: "*" is accepted only for local development (loopback origins), and anywhere else
# it is a hard startup error rather than a silent wide-open API.
_local_dev = {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000",
              "http://127.0.0.1:8000", "http://localhost:4173", "http://127.0.0.1:4173"}


def _parse_origins() -> list[str]:
    raw = (os.getenv("ALLOWED_ORIGINS") or "").strip()
    if not raw:
        if os.getenv("RENDER") or os.getenv("PRODUCTION"):
            raise RuntimeError(
                "ALLOWED_ORIGINS must be set to your web app's exact origin in production "
                "(comma-separated). Refusing to start with an open CORS policy."
            )
        return sorted(_local_dev)
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if not origins:
        raise RuntimeError("ALLOWED_ORIGINS is set but empty - give at least one origin.")
    if "*" in origins:
        raise RuntimeError(
            'ALLOWED_ORIGINS="*" is not permitted with credentials. '
            "List the exact web app origin instead."
        )
    return origins


_allow_origins = _parse_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token",
                   "X-Admin-Token", "X-Device-Token"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(answers.router,  prefix="/api/sessions", tags=["Answers"])
app.include_router(reports.router,  prefix="/api/sessions", tags=["Reports"])
app.include_router(sensors.router,  prefix="/api/sessions", tags=["Wearable"])
app.include_router(sensors.devices_router, prefix="/api/devices", tags=["Wearable"])
app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
app.include_router(admin.router,     prefix="/api/admin",     tags=["Admin"])

# Audio is NO LONGER served from a public static mount. Every clip is streamed by
# GET /api/sessions/{id}/audio/{file_name}, which requires the session's access
# token or an admin token - a recording is personal health data, not a static file.
# The admin panel's <audio src="..."> requests carry the admin bearer token.


def _json_safe(value):
    """
    Replace non-finite floats with their string form, recursively.

    This exists because of a 500-on-500: Python's json module happily *decodes*
    a literal NaN or Infinity from a request body, and Pydantic echoes the
    offending value back inside the validation error. Starlette's JSONResponse
    serialises with allow_nan=False, so rendering that error raised
    ValueError("Out of range float values are not JSON compliant") and the
    request crashed instead of returning 422. Sanitising the error payload turns
    a client mistake into the correct 422 and keeps NaN out of every response.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, bool, type(None))):
        return value
    # Pydantic puts the original exception instance in the error context
    # (ctx={"error": ValueError(...)}), which JSONResponse cannot render.
    return repr(value)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": _json_safe(exc.errors())})


@app.get("/")
def root():
    return {
        "message": "ErgoCare AI API v4 is running",
        "docs":    "/docs",
        "questions": "GET /api/questions",
        "admin_endpoint": "GET /api/sessions/admin  (requires admin login: POST /api/admin/login)",
    }

@app.get("/health")
def health():
    return {"status": "ok", "version": "4.0.0"}
