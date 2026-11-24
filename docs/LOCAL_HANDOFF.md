# Local Setup and Handoff

Prepared on 23 November 2026 from repository commit
`ff2a2bce91ac92654be2a414c167ca03956e153e`.

## Open the App

Double-click `Open-ErgoCare.bat` in the repository root. This starts the backend
and frontend as hidden local processes, waits for readiness, and opens the app.
The launcher selects free ports starting at 8000 and 5173. It binds to loopback,
not the LAN. The current addresses and process identities are stored in
`logs/local-run.json`.

To stop the processes it started:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Stop-Local.ps1
```

Administrator credentials are in the ignored `LOCAL_ACCESS.txt` file. Unique
admin and device secrets were generated in the ignored backend `.env`. Keep
both files private. No real participant data was imported.

This launcher does not start a simulated or physical band. Use **Continue without
wearable** for a questionnaire-only session. To test a band, follow the firmware
instructions in README.md. Simulator readings must be labelled as simulated.

## Fixes in This Checkout

- Persist the selected typed/voice mode after registration, with authenticated
  access and rejection of mode changes after answers have been recorded.
- Stay on the same question after a failed answer save or recording upload;
  retain the entered answer and recording for retry.
- Do not replace a failed server report with a silently generated local report.
- Respect the configured production backend URL; Vite previously substituted the
  literal comparison as well as the meta tag, causing an unintended localhost fallback.
- Validate question IDs and retain authoritative server question wording.
- Preserve the recording link when a text response is revised; reject unrelated
  client-supplied recording URLs.
- Bound upload reads, check both media type and extension, and inspect common
  audio-container signatures. This is not full codec or malware validation.
- Keep the previous recording until the replacement is committed.
- Remove a deleted session from research CSV copies as well as the database.
  Research exports are pseudonymized, not guaranteed anonymous: free text can
  still contain identifiers and requires review and access controls.
- Update the frontend dependency lockfile within its existing version ranges;
  the npm audit now reports zero findings for this installed frontend tree.

## Verification Completed

| Check | Result |
|---|---|
| New backend session integrity regressions | 12/12 |
| New frontend parsing and save-failure checks | 6/6 |
| Existing questionnaire scoring | 27/27 |
| Existing frontend/backend scoring parity | 206 values across 40 questions |
| Existing sensor security checks | 36/36 |
| Existing wearable logic with simulated readings | 20/20 |
| Existing real-HTTP simulated wearable smoke test | 30/30 |
| Existing Hindi/Kannada PDF text round trip | Pass |
| Existing USB bridge unit test | 1/1 |
| Existing 500-answer synthetic matcher set | 492/500; 1 wrong, 7 abstentions |
| Existing 500 simulated participant rule checks | 500/500 |
| TypeScript and Vite production build | Pass |

The synthetic matcher set has already been used for tuning. Its 98.4% result is
not an unseen-data estimate, a speech-recognition result, or clinical accuracy.

Chrome UI verification reached registration, voice-mode selection, and sequential
saves through question 12. Later browser automation timed out, so a completed
40-question browser session and a fresh mobile visual audit are not claimed.
The full HTTP smoke test is separate from that partial browser check.

## Remaining Work

Physical sensor and contact testing, spoken-input testing with real speakers,
native-speaker translation review, mobile and accessibility review, independent
clinical evaluation, and production deployment/security review remain necessary.
The backend dependency set was installed as supplied; a comprehensive backend
dependency-security audit was not performed. Existing partial-session completion
behavior is unchanged. Multiple concurrent workers writing research CSVs need
cross-process locking or a database-backed export queue before scaling.

This document records local validation, not production deployment. Git history
and the associated pull request identify the published changes. Follow
`TEAM_INTEGRATION.md` for the integration checklist.

## Reproduce Focused Tests

```powershell
node scripts/verify_frontend_integrity.mjs
cd ergo_ml_backend
.\.venv\Scripts\python.exe scripts/verify_session_integrity.py
.\.venv\Scripts\python.exe scripts/verify_scoring.py
.\.venv\Scripts\python.exe scripts/verify_sensor_security.py
```

For a fresh environment install `ergo_ml_backend/requirements-dev.txt` and run
`npm ci`. Node.js 22.12+ is required for the current Vite tooling.
