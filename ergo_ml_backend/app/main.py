"""
ErgoCare AI Backend — v3
"""
import os
import app.config  # noqa: F401 - loads ergo_ml_backend/.env before settings are read
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

# IMPORTANT for production: set ALLOWED_ORIGINS env var in Render/Vercel dashboard
# e.g. ALLOWED_ORIGINS=https://your-app.vercel.app
# Leaving it as "*" allows any website to call this API — fine for local dev only.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
_allow_origins = [o.strip() for o in _raw_origins.split(",")] if _raw_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,   # Bug H fix: set ALLOWED_ORIGINS env var in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(answers.router,  prefix="/api/sessions", tags=["Answers"])
app.include_router(reports.router,  prefix="/api/sessions", tags=["Reports"])
app.include_router(sensors.router,  prefix="/api/sessions", tags=["Wearable"])
app.include_router(sensors.devices_router, prefix="/api/devices", tags=["Wearable"])
app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
app.include_router(admin.router,     prefix="/api/admin",     tags=["Admin"])

# Serve audio files directly — admin panel plays them via <audio src="...">
app.mount("/uploads/audio", StaticFiles(directory=AUDIO_DIR), name="audio")


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
