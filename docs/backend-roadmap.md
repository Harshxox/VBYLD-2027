# Backend Roadmap

> **Superseded.** Early planning notes from before the build — several items here (XGBoost, Whisper, RAG, Postgres) were never implemented. The system as built is described in [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md).

This is the suggested backend plan for turning the current ErgoCare AI frontend prototype into a full product.

## 1. Backend Stack

Recommended:

- FastAPI with Python
- PostgreSQL database
- SQLAlchemy or SQLModel ORM
- Alembic migrations
- Local file storage first, then Supabase Storage or AWS S3 for audio
- Whisper or faster-whisper for speech-to-text
- XGBoost for validated scoring
- RAG pipeline for grounded ergonomic recommendations

Alternative:

- Node.js with Express or NestJS
- PostgreSQL with Prisma
- OpenAI or Whisper API for transcription

## 2. Required API Endpoints

```text
POST /api/sessions
  Create a new assessment session.

POST /api/sessions/{session_id}/answers
  Save one typed answer or transcript against one question.

POST /api/sessions/{session_id}/answers/{question_id}/audio
  Upload one voice recording for one question.

POST /api/transcribe
  Convert uploaded audio into text.

POST /api/sessions/{session_id}/complete
  Calculate final scores and generate the report.

GET /api/sessions/{session_id}
  Fetch a full session record.

GET /api/sessions/{session_id}/report.pdf
  Download the generated PDF report.
```

## 3. Database Tables

```text
assessment_sessions
  id
  input_mode
  created_at
  completed_at
  overall_risk
  posture_risk
  eye_strain
  workload_stress
  musculoskeletal_risk
  recovery_risk
  report_json

assessment_answers
  id
  session_id
  question_id
  question_text
  typed_answer
  transcript
  audio_url
  created_at

audio_files
  id
  session_id
  question_id
  file_name
  file_path
  mime_type
  size_bytes
  created_at
```

## 4. Voice Flow

1. Frontend records one answer per question.
2. Frontend uploads audio to backend.
3. Backend stores the audio file.
4. Backend runs speech-to-text.
5. Backend saves transcript beside the question answer.
6. At completion, the session has both raw voice evidence and clean text answers.

## 5. AI/ML Flow

Prototype stage:

- Use current rule-based scoring from `src/domain/scoring.ts`.
- Generate report text from predefined templates.

Advanced stage:

- Train XGBoost on labeled questionnaire records.
- Use SHAP to explain top risk drivers.
- Store ergonomic guidelines in a vector database.
- Use RAG to generate personalized recommendations grounded in trusted sources.
- Save final report JSON and export PDF.

## 6. Immediate Backend TODO

1. Create `/server` folder.
2. Add FastAPI project.
3. Add PostgreSQL schema and migrations.
4. Add session and answer APIs.
5. Add audio upload API.
6. Add transcription service.
7. Connect frontend `saveCurrentAnswer` flow to backend APIs.
8. Replace localStorage persistence with backend persistence.
9. Add PDF report generation.
10. Add authentication only after the core anonymous assessment flow works.
