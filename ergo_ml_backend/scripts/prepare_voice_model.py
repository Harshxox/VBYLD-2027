"""Download and load the configured local Whisper model before a demonstration."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from app.domain.transcription import MODEL_NAME, get_model

if __name__ == "__main__":
    print("Preparing local speech model:", MODEL_NAME, flush=True)
    get_model()
    print("Speech model is ready. Recordings are transcribed locally.")
