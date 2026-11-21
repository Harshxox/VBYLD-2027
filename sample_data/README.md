# Sample data

Ready-made inputs for trying and testing ErgoCare without the hardware or a participant.
All files are produced by [`generate_sample_data.py`](generate_sample_data.py) (deterministic — same output every run).

> ⚠️ The wearable readings are **simulated** (`"_simulated": true` in every line). Never present them as a measurement of a real person.

| File | What it is | Used by |
|---|---|---|
| [`wearable_session.jsonl`](wearable_session.jsonl) | 200 readings, one per second, in the exact JSON the ESP32 sends. Device `SAMPLE-01`. | `run_sample_session.py` |
| [`answers_low_risk.json`](answers_low_risk.json) | 40 answers — the healthiest option of every question (questionnaire score ≈ 0 %) | `run_sample_session.py`, API testing |
| [`answers_high_risk.json`](answers_high_risk.json) | 40 answers — the highest-risk option of every question | API testing |
| [`voice_answers.csv`](voice_answers.csv) | 100 free-form answers (English, Hindi, Kannada, romanised) and the option each must match | mirrors `ergo_ml_backend/scripts/eval_matcher.py` |
| [`run_sample_session.py`](run_sample_session.py) | End-to-end test: replays the files through a running backend and checks the report | — |
| [`voice_answers_500.csv`](voice_answers_500.csv) | **500** synthetic answers (200 English, 75 each Hindi/Kannada in script and romanised), expected option, what the matcher answered | `ergo_ml_backend/scripts/eval_matcher_500.py` (writes it) |
| [`participants_500.csv`](participants_500.csv) | **500** simulated participants: true risk level, wrist-turn / stress exposure, contact quality, scores, ErgoCare Index, insights, failed checks | `ergo_ml_backend/scripts/eval_500_participants.py` (writes it) |

Results of both 500-sample tests: [docs/TEST_CASES.md → 500-sample tests](../docs/TEST_CASES.md#500-sample-tests).

## The sample session's story

| Seconds | Phase | What the readings show |
|---|---|---|
| 0–60 | `baseline` | Calm: ~75 BPM, skin response ~450, band wrist calibrated to neutral |
| 60–100 | `calm` | Same, while answering |
| 100–140 | `wrist_turn` | Band wrist rotates from its neutral orientation; this is descriptive only |
| 140–180 | `stressed` | Skin response +45 % and heart rate +16 BPM |
| 180–200 | `calm` | Back to normal |

Fields starting with `_` (`_t`, `_phase`, `_simulated`) are notes for people; strip them before sending (the replay script does).

## Run the end-to-end test

```bat
cd ergo_ml_backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000
REM in a second window:
.venv\Scripts\python ..\sample_data\run_sample_session.py
```

It sends the 60-s baseline, the 40 low-risk answers and the wrist-turn + stress readings at the real rate (1 per second, ~2.5 minutes), then checks:

consent is enforced · data needs the session token · baseline is computed · wrist motion does not trigger a torso-posture warning · the ErgoCare Index uses questionnaire + baseline-relative heart-rate / skin-response score · the report keeps wrist observations separate · the PDF downloads · the test session is deleted.

The replay intentionally generates no posture warning or posture insight from band-wrist turns. Clean-up needs `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `ergo_ml_backend/.env`; if `DEVICE_INGEST_TOKEN` is set there, the script sends it automatically.

## Regenerate

```bat
ergo_ml_backend\.venv\Scripts\python sample_data\generate_sample_data.py
```
