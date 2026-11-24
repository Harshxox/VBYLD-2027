"""Create ignored local configuration with unique secrets, without printing them."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
backend = root / "ergo_ml_backend"
env = backend / ".env"
if not env.exists():
    password = secrets.token_urlsafe(24)
    env.write_text("\n".join([
        "DATABASE_URL=sqlite:///./ergocare.db",
        "AUDIO_UPLOAD_DIR=./uploads/audio",
        "ADMIN_USERNAME=admin",
        f"ADMIN_PASSWORD={password}",
        f"ADMIN_SECRET={secrets.token_urlsafe(48)}",
        f"DEVICE_INGEST_TOKEN={secrets.token_urlsafe(32)}",
        "RESEARCH_EXPORT_DIR=./research_data",
        "SENSOR_RETENTION_S=21600",
    ]) + "\n", encoding="utf-8")
    (root / "LOCAL_ACCESS.txt").write_text(
        "Local ErgoCare administrator\nUsername: admin\nPassword: " + password
        + "\n\nPrivate local credentials. Do not share or commit this file.\n",
        encoding="utf-8",
    )
frontend = root / ".env"
if not frontend.exists():
    frontend.write_text("VITE_API_BASE=http://127.0.0.1:8000\n", encoding="utf-8")
print("Local configuration is ready. Private credentials are in LOCAL_ACCESS.txt.")
