"""Local speech transcription with bounded decoding and one CPU inference at a time."""
from __future__ import annotations

import io
import os
from pathlib import Path
import threading

import numpy as np
from fastapi import HTTPException

_model = None
_model_lock = threading.Lock()
_inference_lock = threading.Lock()
MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
CACHE_DIR = Path(os.getenv("VOICE_MODEL_CACHE", str(Path(__file__).resolve().parents[2] / "models_cache" / "voice")))
MAX_SECONDS = 120


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=2,
                                  download_root=str(CACHE_DIR))
    return _model


def _decode(data: bytes):
    import av
    chunks = []
    count = 0
    try:
        with av.open(io.BytesIO(data)) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples = converted.to_ndarray().reshape(-1)
                    count += samples.size
                    if count > MAX_SECONDS * 16000:
                        raise HTTPException(status_code=413, detail="Recordings must be at most 120 seconds.")
                    chunks.append(samples)
            for converted in resampler.resample(None):
                chunks.append(converted.to_ndarray().reshape(-1))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This recording could not be decoded.") from exc
    if not chunks or sum(c.size for c in chunks) < 1600:
        raise HTTPException(status_code=422, detail="The recording is too short to transcribe.")
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    if audio.size > MAX_SECONDS * 16000:
        raise HTTPException(status_code=413, detail="Recordings must be at most 120 seconds.")
    return audio


def transcribe_audio(data: bytes, language: str) -> dict:
    if language not in {"en", "hi", "kn"}:
        raise HTTPException(status_code=422, detail="Unsupported transcription language.")
    if not _inference_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Transcription is busy. Retry shortly.", headers={"Retry-After": "5"})
    try:
        audio = _decode(data)
        try:
            segments, _ = get_model().transcribe(audio, language=language, beam_size=5,
                                                vad_filter=True, condition_on_previous_text=False)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Local transcription is unavailable. Run scripts/prepare_voice_model.py on the backend, then retry.") from exc
        if not text:
            raise HTTPException(status_code=422, detail="No clear speech was detected. Retry or enter the transcript.")
        return {"transcript": text, "language": language, "engine": "faster-whisper", "model": MODEL_NAME}
    finally:
        _inference_lock.release()


def validate_audio(data: bytes) -> None:
    """Reject undecodable or overlong clips before they become saved recordings."""
    _decode(data)
