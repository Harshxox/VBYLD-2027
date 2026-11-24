"""Isolated speech-route regressions; optionally run a real synthetic speech fixture."""
from pathlib import Path
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import wave

TEMP=tempfile.TemporaryDirectory(prefix="ergocare-voice-")
ROOT=Path(TEMP.name)
os.environ["DATABASE_URL"]="sqlite:///"+(ROOT/"test.db").as_posix()
os.environ["AUDIO_UPLOAD_DIR"]=str(ROOT/"audio")
os.environ["RESEARCH_EXPORT_DIR"]=str(ROOT/"research")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import Base, engine
from app.domain import transcription
from app.domain.answer_matcher import match_answer
from app.domain.questions import QUESTIONS_BY_ID
Base.metadata.create_all(bind=engine)
client=TestClient(app)

def wav_bytes(seconds=1):
    out=io.BytesIO()
    with wave.open(out,"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
        w.writeframes(b"\0\0"*int(16000*seconds))
    return out.getvalue()

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.session=client.post('/api/sessions',json={'input_mode':'voice','consent':True}).json()
        self.headers={'X-Session-Token':self.session['access_token']}
        self.url=f"/api/sessions/{self.session['id']}/answers/1/transcribe"
    def send(self,headers=None,content=None,language='en',url=None):
        return client.post(url or self.url,headers=self.headers if headers is None else headers,
                           files={'file':('answer.wav',content or wav_bytes(),'audio/wav')},data={'language':language})
    def test_requires_session_access(self):
        self.assertEqual(self.send(headers={}).status_code,401)
    def test_other_session_cannot_transcribe(self):
        second=client.post('/api/sessions',json={'input_mode':'typed','consent':True}).json()
        self.assertEqual(self.send(headers={'X-Session-Token':second['access_token']}).status_code,403)
    def test_unknown_question_rejected(self):
        self.assertEqual(self.send(url=self.url.replace('/1/','/999/')).status_code,422)
    def test_bad_container_rejected(self):
        self.assertEqual(self.send(content=b'not an audio recording').status_code,415)
    def test_unknown_language_rejected(self):
        self.assertEqual(self.send(language='zz').status_code,422)
    def test_duration_is_bounded_before_inference(self):
        self.assertEqual(self.send(content=wav_bytes(121)).status_code,413)
    def test_transcript_is_returned_without_saving_an_answer(self):
        model=SimpleNamespace(transcribe=lambda *a,**k:([SimpleNamespace(text=' I take a break after one hour. ')],None))
        with patch.object(transcription,'get_model',return_value=model):
            response=self.send()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['transcript'],'I take a break after one hour.')
        record=client.get('/api/sessions/'+self.session['id'],headers=self.headers).json()
        self.assertEqual(record['answers'],[])
        self.assertEqual(record['audio_files'],[])
    def test_decoder_failure_is_clear(self):
        self.assertEqual(self.send(content=b'RIFF0000WAVEinvalid').status_code,422)
    def test_model_failure_keeps_route_available_for_retry(self):
        with patch.object(transcription,'get_model',side_effect=RuntimeError('unavailable')):
            self.assertEqual(self.send().status_code,503)
    def test_empty_speech_is_not_invented(self):
        with patch.object(transcription,'get_model',return_value=SimpleNamespace(transcribe=lambda *a,**k:([],None))):
            self.assertEqual(self.send().status_code,422)

if __name__=='__main__':
    fixture=None
    if '--fixture' in sys.argv:
        i=sys.argv.index('--fixture');fixture=Path(sys.argv[i+1]);del sys.argv[i:i+2]
    suite=unittest.main(verbosity=2,exit=False)
    if suite.result.wasSuccessful() and fixture:
        result=transcription.transcribe_audio(fixture.read_bytes(),'en')
        matched=match_answer(QUESTIONS_BY_ID[1],result['transcript'])
        print(json.dumps({'fixture':'synthetic TTS, not a participant recording',**result,'matched_option':matched.option},ensure_ascii=True))
        if matched.option!='1 hour':raise SystemExit('Synthetic speech did not resolve to the expected answer')
    client.close();engine.dispose();TEMP.cleanup()
    sys.exit(not suite.result.wasSuccessful())
