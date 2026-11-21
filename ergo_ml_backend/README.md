# ErgoCare AI — Backend (FastAPI)

Setup, hardware and the full picture are in the [main README](../README.md).

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          &REM then set ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_SECRET
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Interactive API docs: http://127.0.0.1:8000/docs · Tables are created automatically on start-up (SQLite by default, `DATABASE_URL` for Postgres).

## Automatic research export

When `POST /api/sessions/{id}/complete` succeeds, the backend upserts non-PII
research CSVs under `RESEARCH_EXPORT_DIR` (default: `./research_data`):

- `sessions.csv` — anonymised session metadata and scores
- `answers.csv` — questionnaire responses and timestamps
- `wearable_readings.csv` — raw per-reading band telemetry
- `wearable_features.csv` — session-level wearable features
- `data_dictionary.csv` — exported field descriptions

The export excludes name, email, phone and audio. To backfill sessions completed
before this feature, run:

```bat
.venv\Scripts\python scripts\export_research_data.py
```

Back up `research_data` securely. The existing report score is a derived
feature, not an independent training label; collect participant feedback or
another independent outcome before training a predictive model.

## Endpoints

| Area | Method + path | Notes |
|---|---|---|
| Sessions | `POST /api/sessions` | requires `"consent": true` |
| | `GET /api/sessions/{id}` · `GET /api/sessions/{id}/audio` | |
| Answers | `POST /api/sessions/{id}/answers` · `POST /api/sessions/{id}/answers/{qid}/audio` | 10 MB / type / disk-space checks |
| Report | `POST /api/sessions/{id}/complete` · `GET /api/sessions/{id}/report` · `GET /api/sessions/{id}/report.pdf` | includes the wearable section + ErgoCare Index |
| Wearable (device) | `POST /api/devices/{device_id}/readings` · `GET /api/devices` · `GET /api/devices/{device_id}/latest` | sent by the ESP32 / `usb_bridge.py` |
| Wearable (session) | `POST|DELETE /api/sessions/{id}/device` · `POST /api/sessions/{id}/baseline/start` · `/finish` · `GET /api/sessions/{id}/sensors/latest` · `/sensors/history` | live panel, warnings, report graphs |
| Answer matching | `POST /api/questions/{qid}/match` · `GET /api/questions/matcher` | free-form / Hindi / Kannada answers → option |
| Admin | `POST /api/admin/login` · `GET /api/admin/me` · `GET /api/sessions/admin` · `DELETE /api/sessions/{id}` | `Authorization: Bearer <token>` |

## Where the logic lives

| File | What |
|---|---|
| `app/domain/scoring.py`, `ml_engine.py` | questionnaire scoring (hand-set expert rules) |
| `app/domain/sensors.py` | thresholds, baseline, live warnings, graph data |
| `app/domain/sensor_scoring.py` | heart-rate / skin-response score, ErgoCare Index and "hidden stress" insight; wrist motion is descriptive only |
| `app/domain/answer_matcher.py`, `indic_lexicon.py` | understanding free-form, Hindi and Kannada answers (rules + MiniLM) |
| `app/security.py` | admin login, tokens, lock-out |

## Checks

```bat
.venv\Scripts\python scripts\verify_wearable.py   &REM PASS/FAIL for logic, scoring and the live wearable
.venv\Scripts\python scripts\eval_matcher.py      &REM answer-matcher accuracy (development + held-out)
```

## Existing databases

New tables (`sensor_links`, `sensor_readings`, `consents`) are added automatically. If an old `ergocare.db` predates the `client_*` columns, delete it (development) or add them:

```sql
ALTER TABLE assessment_sessions ADD COLUMN client_name TEXT;
ALTER TABLE assessment_sessions ADD COLUMN client_email TEXT;
ALTER TABLE assessment_sessions ADD COLUMN client_phone TEXT;
ALTER TABLE assessment_sessions ADD COLUMN client_age INTEGER;
ALTER TABLE assessment_sessions ADD COLUMN client_job TEXT;
```
