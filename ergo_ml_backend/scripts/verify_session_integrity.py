"""Isolated regressions for session mode, upload validation and export deletion."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import wave

TEMP = tempfile.TemporaryDirectory(prefix="ergocare-integrity-")
ROOT = Path(TEMP.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'test.db').as_posix()}"
os.environ["AUDIO_UPLOAD_DIR"] = str(ROOT / "audio")
os.environ["RESEARCH_EXPORT_DIR"] = str(ROOT / "research")
os.environ["ADMIN_API_TOKEN"] = "isolated-test-admin"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.db.database import Base, engine
from app.domain.questions import QUESTIONS
from app.api.routes import answers
from app.research_export import CSV_SCHEMAS, _upsert_csv

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def audio_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 800)
    return stream.getvalue()


class SessionIntegrityTests(unittest.TestCase):
    def setUp(self):
        created = client.post("/api/sessions", json={"input_mode": "typed", "consent": True})
        self.assertEqual(created.status_code, 201)
        self.sid = created.json()["id"]
        self.headers = {"X-Session-Token": created.json()["access_token"]}
        self.url = f"/api/sessions/{self.sid}"

    def save(self, **changes):
        payload = {"question_id": 1, "question_text": "untrusted wording", "typed_answer": QUESTIONS[0]["options"][0]}
        payload.update(changes)
        return client.post(self.url + "/answers", json=payload, headers=self.headers)

    def upload(self, name="answer.wav", content=None, mime="audio/wav", qid=1):
        return client.post(self.url + f"/answers/{qid}/audio", headers=self.headers,
                           files={"file": (name, audio_bytes() if content is None else content, mime)})

    def test_voice_mode_is_persisted(self):
        r = client.patch(self.url + "/mode", json={"input_mode": "voice"}, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get(self.url, headers=self.headers).json()["input_mode"], "voice")

    def test_mode_change_requires_session_access(self):
        self.assertEqual(client.patch(self.url + "/mode", json={"input_mode": "voice"}).status_code, 401)

    def test_mode_cannot_change_after_answers(self):
        self.save()
        self.assertEqual(client.patch(self.url + "/mode", json={"input_mode": "voice"}, headers=self.headers).status_code, 409)

    def test_question_wording_is_server_authoritative(self):
        self.assertEqual(self.save().json()["question_text"], QUESTIONS[0]["text"])

    def test_unknown_question_rejected(self):
        self.assertEqual(self.save(question_id=999).status_code, 422)
        self.assertEqual(self.upload(qid=999).status_code, 422)

    def test_blank_answer_rejected(self):
        self.assertEqual(self.save(typed_answer=" ", transcript=" ").status_code, 422)

    def test_disguised_text_rejected(self):
        self.assertEqual(self.upload(content=b"not audio", mime="text/plain").status_code, 415)
        self.assertEqual(self.upload(content=b"not audio").status_code, 415)

    def test_extensionless_non_audio_rejected(self):
        self.assertEqual(self.upload(name="blob", content=b"plain text", mime="text/plain").status_code, 415)

    def test_audio_reference_survives_text_revision(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(self.save().json()["audio_url"], uploaded.json()["audio_url"])
        fetched = client.get(self.url, headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(len(fetched.json()["audio_files"]), 1)

    def test_oversized_upload_preserves_old_recording(self):
        first = self.upload().json()["audio_url"]
        before = answers.MAX_AUDIO_BYTES
        try:
            answers.MAX_AUDIO_BYTES = 64
            self.assertEqual(self.upload(content=audio_bytes() * 10).status_code, 413)
        finally:
            answers.MAX_AUDIO_BYTES = before
        self.assertEqual(client.get(self.url + "/audio", headers=self.headers).json()[0]["audio_url"], first)

    def test_reupload_replaces_old_file(self):
        first = self.upload().json()["audio_url"]
        second = self.upload().json()["audio_url"]
        self.assertNotEqual(first, second)
        self.assertEqual(len(list((ROOT / "audio" / self.sid).iterdir())), 1)

    def test_deletion_removes_research_export_rows(self):
        for name in CSV_SCHEMAS:
            _upsert_csv(name, [{"session_id": self.sid}, {"session_id": "keep-other-session"}])
        r = client.delete(self.url, headers={"X-Admin-Token": "isolated-test-admin"})
        self.assertEqual(r.status_code, 204)
        for name in CSV_SCHEMAS:
            with (ROOT / "research" / name).open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertFalse(any(row["session_id"] == self.sid for row in rows))
            self.assertTrue(any(row["session_id"] == "keep-other-session" for row in rows))


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    client.close()
    engine.dispose()
    TEMP.cleanup()
    sys.exit(not result.result.wasSuccessful())
