# Team Integration Handoff

Prepared for Shree Pranav G and Harshdeep on 24 November 2026.

## Delivery

Review and merge https://github.com/Harshxox/VBYLD-2027/pull/1.
The branch is `fix/session-integrity-handoff` on
https://github.com/culturedpotato04/VBYLD-2027. Upstream base is
`ff2a2bce91ac92654be2a414c167ca03956e153e`.

This revision finishes the application-side handoff. Optional wearable
interfaces are retained; physical hardware acceptance belongs to the receiving
team. The separate academic paper is application-only and is not changed here.
Its earlier snapshot needs alignment with the new transcription and completion
rules before final submission.

## Included Changes

- Authenticated typed/voice mode persistence and canonical question validation.
- Preserve answers and clips on failed saves; retry final report generation
  without saving the final answer a second time.
- Require all 40 answers before completing; keep completion idempotent.
- Match typed or spoken free text to an explicit confirmed option; no silent
  neutral score. Preserve raw text and previous answers.
- CPU-local multilingual Whisper transcription of recorded/uploaded clips,
  with model preparation, language validation and bounded decoding.
- Recorder final-chunk synchronization, correct MIME/extension, permission
  timeout, maximum duration and recoverable transcription failures.
- Validate clips before persistence; retain old clips on failed replacement.
  Remove deleted sessions from research exports.
- Authenticated participant/admin PDFs and admin recording playback, without
  putting access tokens into media URLs.
- Align browser composite scores with backend scoring, including 100 complete
  synthetic-session comparisons.
- Configured API URL, Windows launchers, private configuration generation and
  a reproducible 12-suite verification runner.

## Receiving Machine

```powershell
npm ci
python -m venv ergo_ml_backend/.venv
./ergo_ml_backend/.venv/Scripts/python.exe -m pip install -r ergo_ml_backend/requirements-dev.txt
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/prepare_voice_model.py
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/verify_handoff.py
```

Use Python 3.10+ and Node 22.12+. Initial voice-model preparation needs internet
and disk space; multilingual `base` is about 145 MB before cache duplication.
Set backend `WHISPER_MODEL` and `VOICE_MODEL_CACHE` if needed, then restart.
Run `Open-ErgoCare.bat` after preparation.

The launcher binds to loopback and does not start a band or publish the app.
Each developer needs unique configuration and credentials. Do not share
`.env`, `LOCAL_ACCESS.txt`, model caches, real records or recordings.

## Acceptance Before Merge/Deployment

1. Run the suite; inspect LOCAL_HANDOFF.md for test evidence and limits.
2. Speak into a real microphone in the target browser. Review/correct the
   transcript, confirm the option and verify each saved recording. Check
   Hindi/Kannada with native speakers, not only English fixtures.
3. Complete typed and voice sessions, reopen them as admin, play saved clips
   and download PDFs. Interrupt the API and verify retry preserves input.
4. Perform physical sensor/contact and firmware integration tests separately.
   Passing synthetic suites are not physical validation.
5. Configure HTTPS, backend URL, CORS, durable private storage, secrets, access
   control, backups and retention on the production host.

## Remaining Engineering Limits

Concurrent session-question upserts and cross-process CSV exports need stronger
database/queue coordination before multi-worker scaling. Speech inference is
single-flight CPU work; concurrent demand gets a visible retry response.
Translation, accessibility, real-device mobile checks, independent scoring and
clinical review, and a full backend vulnerability audit remain pending.

No participant data, secrets or generated academic files are required to review
or merge the code archive.
