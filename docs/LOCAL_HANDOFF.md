# Local Application Verification

Verified on Windows on 24 November 2026. This is local software validation,
not production deployment, clinical validation, or physical-device acceptance.

## Start

Follow README.md to install dependencies and prepare the voice model, then
double-click `Open-ErgoCare.bat`. Actual URLs are recorded in
`logs/local-run.json`. Stop only those servers with `Stop-Local.ps1`.
Continue without the optional wearable for an application-only assessment.

Each machine generates its own ignored configuration. Keep `.env`,
`LOCAL_ACCESS.txt`, databases, uploads and research exports private. The local
database may contain participant data; do not copy it into a handoff archive.

## Automated Checks

Run from the repository root:

```powershell
./ergo_ml_backend/.venv/Scripts/python.exe ergo_ml_backend/scripts/verify_handoff.py
```

The runner records output in ignored `logs/handoff-verification.json`. All 12
suites passed in the delivery run:

| Suite | Result |
|---|---|
| Frontend integrity, including parsing and media/save retries | 13/13 |
| Session integrity, including 40 clips and transcript persistence | 16/16 |
| Speech route authentication, decoding and failure handling | 10/10 |
| Questionnaire scoring | 27/27 |
| Frontend/backend parity | 206 option values and 100 complete sessions |
| Sensor security | 36/36 |
| Synthetic wearable logic | 20/20 |
| Synthetic real-HTTP integration | 30/30 |
| Hindi/Kannada/Latin PDF rendering | Pass |
| Installed Python dependency consistency | Pass |
| TypeScript | Pass |
| Vite production build | Pass |

These are synthetic fixtures, not recognition accuracy or medical effectiveness
measurements. Existing upstream matcher benchmarks were not repeated in this
delivery and are not Whisper speech-accuracy benchmarks.

## Browser Acceptance

- Completed all 40 questions in typed mode; previous-question navigation
  retained the original free text and confirmed option.
- Completed all 40 questions in voice mode. Question 1 used a synthetic English
  speech WAV; local Whisper produced its transcript and matched the one-hour
  option. The other 39 used confirmed options, not microphone recordings.
- Played the uploaded clip to completion without an audio-element error.
- Downloaded authenticated participant PDFs from both browser sessions.
- Signed in as admin, reopened the synthetic voice session, verified 40/40
  answers and its saved transcript, played its server-stored recording to
  completion and downloaded its protected PDF. Signed out afterward.
- A separate isolated API test saves and reads back 40 recordings and 40
  transcripts in one session; this is not 40 human-spoken browser answers.

## Limits

Real microphone capture was not established unattended: the test browser's
permission request did not resolve. A timeout now releases the control and
preserves existing audio. Real speakers, Hindi/Kannada speech accuracy,
mobile-device audio permissions, accessibility and physical sensor contact
still need acceptance tests on target devices.

Missing models, unclear speech, busy inference, invalid clips and network
failures produce visible retryable messages. No arbitrary neutral score or
silently substituted local report is generated. Prepare the model before a
demonstration. CPU transcription is serialized, not a scaled inference service.

Production review remains necessary: HTTPS, CORS, private persistent storage,
backups, deletion/retention policy, dependency security, concurrent database
upserts and multi-worker research-export coordination. Dependency consistency
is not a vulnerability audit. See TEAM_INTEGRATION.md for receiving steps.
